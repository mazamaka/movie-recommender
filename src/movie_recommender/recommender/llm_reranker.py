"""LLM-based reranker — uses Claude to refine top-N candidates using reaction history."""
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

from movie_recommender.core.config import settings

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = structlog.get_logger()


def _build_system_prompt(shortlist_size: int) -> str:
    return f"""Ты — опытный рекомендатель фильмов. Тебе дают:
1. Краткий профиль вкуса пользователя (что он любит, что бросил, что заблокировал).
2. Список из {shortlist_size} кандидатов на сегодняшнюю подборку с метаданными.

Твоя задача — выбрать ровно ТОП-10 фильмов, которые с наибольшей вероятностью понравятся пользователю.
Учитывай не только жанры, но и режиссёра, актёрский состав, описание, эпоху.

Отвечай СТРОГО валидным JSON без markdown:
{{
  "picks": [
    {{"rank": 1, "tmdb_id": <int>, "reason": "<1-2 предложения на русском почему именно этот фильм подходит>"}},
    ...всего 10 элементов
  ]
}}

Правила обоснований:
- Конкретно и по делу: ссылайся на любимые фильмы пользователя ("эпично, как Дюна, которую ты досмотрел").
- Если фильм рискованный — честно скажи ("если жанр не зашёл — пропусти").
- Не повторяйся, не льсти.
- Никогда не выходи за рамки JSON."""


def _get_anthropic_client() -> "AsyncAnthropic":
    """Lazily construct AsyncAnthropic client. Patched in tests."""
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds)


def _build_taste_summary(
    feedback: dict[str, dict],
    finished_movies: list[dict],
    dropped_movies: list[dict],
) -> str:
    """Build compact text summary of user's taste for the LLM prompt."""
    sections: list[str] = []

    if finished_movies:
        sections.append("ДОСМОТРЕЛ ДО КОНЦА В LAMPA (>80%, сильный позитив):")
        for m in finished_movies[:30]:
            genres = ", ".join(m.get("genres", [])[:3]) or "—"
            sections.append(f"  - {m.get('title_ru', '?')} ({m.get('year', '?')}) [{genres}]")
        sections.append("")

    if dropped_movies:
        sections.append("БРОСИЛ ПОСРЕДИНЕ В LAMPA (10-50%, не зашло):")
        for m in dropped_movies[:30]:
            genres = ", ".join(m.get("genres", [])[:3]) or "—"
            sections.append(f"  - {m.get('title_ru', '?')} ({m.get('year', '?')}) [{genres}]")
        sections.append("")

    favorites: list[str] = []
    likes: list[str] = []
    dislikes: list[str] = []
    blocks: list[str] = []

    for _tmdb_id, fb in feedback.items():
        title = fb.get("title", "?")
        genres = ", ".join(fb.get("genres", [])[:3]) or "—"
        line = f"  - {title} [{genres}]"
        if fb.get("favorites", 0) >= 1:
            favorites.append(line)
        elif fb.get("likes", 0) >= 1 and fb.get("dislikes", 0) == 0:
            likes.append(line)
        if fb.get("dislikes", 0) >= 1:
            dislikes.append(line)
        if fb.get("blocks", 0) >= 1:
            blocks.append(line)

    if favorites:
        sections.append("ЛЮБИМЫЕ В КАНАЛЕ (🔥/❤️/🏆/⚡):")
        sections.extend(favorites[:30])
        sections.append("")
    if likes:
        sections.append("ПОНРАВИЛИСЬ В КАНАЛЕ (👍/🎉/😍/💯):")
        sections.extend(likes[:30])
        sections.append("")
    if dislikes:
        sections.append("НЕ ПОНРАВИЛИСЬ В КАНАЛЕ (👎):")
        sections.extend(dislikes[:30])
        sections.append("")
    if blocks:
        sections.append("ЗАБЛОКИРОВАНЫ (💩 — не показывать похожее):")
        sections.extend(blocks[:30])
        sections.append("")

    return "\n".join(sections).strip() or "Профиль вкуса пуст."


def _build_candidate_list(candidates: list[dict]) -> str:
    """Numbered list of candidates with key metadata for the prompt."""
    lines: list[str] = ["КАНДИДАТЫ ДЛЯ ПОДБОРКИ НА СЕГОДНЯ (выбери ровно 10 лучших по моему вкусу):", ""]
    for i, c in enumerate(candidates, 1):
        genres = ", ".join(c.get("genres", [])[:4]) or "—"
        directors = ", ".join(c.get("directors", [])[:2]) or "—"
        actors = ", ".join(c.get("actors", [])[:4]) or "—"
        rating = c.get("rating_imdb")
        votes = c.get("vote_count", 0)
        rating_str = f"{rating:.1f}" if rating else "—"
        votes_str = f"{votes // 1000}K" if votes >= 1000 else str(votes)
        desc = (c.get("description") or "")[:300]

        lines.append(f"{i}. {c.get('title_ru', '?')} ({c.get('year', '?')})")
        lines.append(f"   tmdb_id: {c.get('tmdb_id')}")
        lines.append(f"   Жанры: {genres}")
        lines.append(f"   Режиссёр: {directors}")
        lines.append(f"   В ролях: {actors}")
        lines.append(f"   Рейтинг IMDB: {rating_str} ({votes_str} голосов)")
        lines.append(f"   Описание: {desc}")
        lines.append("")
    return "\n".join(lines)


def _parse_llm_response(raw: str, candidates: list[dict], top_n: int) -> list[dict]:
    """Parse Claude JSON, map tmdb_id → candidate dicts, fill from shortlist if needed.

    Returns list of length top_n. LLM-picked entries get llm_reason + llm_rank;
    fillers from shortlist do not.
    """
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0]
        data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning("llm_rerank_invalid_json", error=str(e), raw_preview=raw[:200])
        return candidates[:top_n]

    picks = data.get("picks")
    if not isinstance(picks, list):
        logger.warning("llm_rerank_no_picks", data_keys=list(data.keys()))
        return candidates[:top_n]

    candidate_by_id = {c.get("tmdb_id"): c for c in candidates if c.get("tmdb_id")}
    used_ids: set[int] = set()
    result: list[dict] = []

    for pick in picks[:top_n]:
        if not isinstance(pick, dict):
            continue
        tmdb_id = pick.get("tmdb_id")
        if not isinstance(tmdb_id, int) or tmdb_id not in candidate_by_id or tmdb_id in used_ids:
            logger.info("llm_rerank_unknown_tmdb_id", tmdb_id=tmdb_id)
            continue
        used_ids.add(tmdb_id)
        movie = dict(candidate_by_id[tmdb_id])
        movie["llm_rank"] = len(result) + 1
        reason = pick.get("reason")
        if isinstance(reason, str) and reason.strip():
            movie["llm_reason"] = reason.strip()
        result.append(movie)

    if len(result) < top_n:
        for c in candidates:
            cid = c.get("tmdb_id")
            if cid in used_ids or not cid:
                continue
            result.append(dict(c))
            used_ids.add(cid)
            if len(result) >= top_n:
                break
        logger.info("llm_rerank_filled_from_shortlist", picks=len(picks), final=len(result))

    return result[:top_n]


def _dump_debug(prompt_parts: list[dict], raw_response: str) -> None:
    """Optional: dump prompt + response to data/llm_debug/{date}.json for manual review."""
    if not settings.llm_debug_log:
        return
    try:
        debug_dir = Path("/app/data/llm_debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
        path.write_text(
            json.dumps({"prompt_parts": prompt_parts, "response": raw_response}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("llm_debug_dump_failed", error=str(e))


async def rerank_candidates(
    candidates: list[dict],
    feedback: dict[str, dict],
    finished_movies: list[dict],
    dropped_movies: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """Rerank candidates via Claude. Returns top_n with optional llm_reason/llm_rank.

    Falls back to candidates[:top_n] (без llm_reason) на любой ошибке.
    """
    if not settings.anthropic_api_key:
        logger.debug("llm_rerank_skipped", reason="no_api_key")
        return candidates[:top_n]
    if not settings.llm_rerank_enabled:
        logger.debug("llm_rerank_skipped", reason="disabled")
        return candidates[:top_n]
    if len(candidates) <= top_n:
        logger.debug("llm_rerank_skipped", reason="candidates_too_few", count=len(candidates))
        return candidates
    if not feedback and not finished_movies:
        logger.info("llm_rerank_skipped", reason="no_taste_signal")
        return candidates[:top_n]

    taste = _build_taste_summary(feedback, finished_movies, dropped_movies)
    cand_list = _build_candidate_list(candidates)

    logger.info(
        "llm_rerank_started",
        candidates=len(candidates),
        feedback_count=len(feedback),
        finished_count=len(finished_movies),
        dropped_count=len(dropped_movies),
    )

    prompt_parts = [
        {"type": "text", "text": _build_system_prompt(len(candidates)), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": taste},
        {"type": "text", "text": cand_list},
    ]

    try:
        client = _get_anthropic_client()
        response = await client.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            system=prompt_parts,
            messages=[{"role": "user", "content": "Выбери топ-10 как описано в системном промпте."}],
        )
        raw = response.content[0].text if response.content else ""
        _dump_debug(prompt_parts, raw)

        result = _parse_llm_response(raw, candidates, top_n)
        with_reason = sum(1 for m in result if m.get("llm_reason"))
        logger.info(
            "llm_rerank_completed",
            picked=len(result),
            with_reason=with_reason,
            model=settings.llm_model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return result
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning("llm_rerank_failed", error_type=type(e).__name__, error=str(e))
        return candidates[:top_n]
    except Exception as e:
        # Catches anthropic.APIStatusError, RateLimitError, APIConnectionError, etc.
        logger.warning("llm_rerank_failed", error_type=type(e).__name__, error=str(e))
        return candidates[:top_n]

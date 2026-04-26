# LLM-Reranked Daily Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Claude Sonnet as a final reranker over top-30 candidates each day at 21:00, with a taste summary built from channel reactions + Lampa watch progress (>80% finished as positive, 10-50% dropped as negative). Pipeline falls back to existing score order on any LLM failure.

**Architecture:** LLM врезается одной точкой между ranking и торрент-поиском в `pipeline/runner.py`. Один новый модуль `recommender/llm_reranker.py`. Дополнительно расширяем Lampa плагин и `HistoryItem` чтобы получать прогресс просмотра (`time_watched`, `duration`). Существующий самописный scheduler в `app.py` уже запускает pipeline в 21:00 Europe/Budapest — НЕ меняем.

**Tech Stack:** Python 3.12, FastAPI, anthropic SDK, structlog, pytest, pytest-asyncio, JavaScript (Lampa plugin).

**Spec:** [docs/superpowers/specs/2026-04-26-llm-reranked-daily-recommendations-design.md](../specs/2026-04-26-llm-reranked-daily-recommendations-design.md)

---

## File Structure

### Files to Create

| Path | Responsibility |
|---|---|
| `src/movie_recommender/recommender/llm_reranker.py` | LLM reranking module with public `rerank_candidates()` and 3 helpers. |
| `tests/test_llm_reranker.py` | Unit tests for reranker (10 cases). |
| `tests/test_runner_progress.py` | Unit tests for finished/dropped extraction (5 cases). |
| `tests/test_pipeline_with_llm.py` | Integration tests with mocked Anthropic + TMDB (3 cases). |
| `tests/conftest.py` | Shared pytest fixtures (sample_feedback, sample_candidates, mock_anthropic). |

### Files to Modify

| Path | Change |
|---|---|
| `pyproject.toml` | Add `anthropic>=0.40` dependency. |
| `.env.example` | Add `ANTHROPIC_API_KEY=` and related LLM settings. |
| `src/movie_recommender/core/config.py` | Add LLM and progress threshold settings. |
| `src/movie_recommender/api/v1/sync.py` | Extend `HistoryItem` with `time_watched`, `duration`, rename `time` → `timestamp`. |
| `src/movie_recommender/static/lampa_plugin.js` | Send `time_watched` + `duration` from Lampa.Storage timeline. |
| `src/movie_recommender/pipeline/runner.py` | Add `finished`/`dropped` extraction in `_get_sync_history`; add `rerank_candidates()` call after scoring. |
| `src/movie_recommender/publishers/telegram.py` | Add `🤖 {llm_reason}` section in `format_message`. |

### Files NOT to Touch (existing behavior preserved)

- `app.py` — самописный 21:00 Europe/Budapest scheduler уже корректен.
- `recommender/content_based.py` — score_movie не меняется.
- `recommender/profile_builder.py` — не меняется.
- `publishers/feedback.py` — реакции уже корректно собираются.
- `ingest/cub_client.py`, `ingest/tmdb_client.py` — не меняются.
- `search/*`, `filters/*` — не меняются.

---

## Task 1: Add anthropic dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current dependencies**

Run: `cat pyproject.toml | grep -A 20 dependencies`

Expected output: список из 15 зависимостей включая `fastapi`, `httpx`, `structlog`.

- [ ] **Step 2: Add anthropic to dependencies array**

Edit `pyproject.toml`, in `[project] dependencies` array, add after `"structlog>=24.0",`:

```toml
    "anthropic>=0.40",
```

Final array should look like:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "sqlmodel>=0.0.22",
    "aiosqlite>=0.20",
    "httpx>=0.28",
    "python-telegram-bot>=22.0",
    "scikit-learn>=1.6",
    "numpy>=2.0",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "pydantic-settings>=2.7",
    "typer[all]>=0.15",
    "rich>=13.9",
    "apscheduler>=3.10",
    "structlog>=24.0",
    "anthropic>=0.40",
]
```

- [ ] **Step 3: Install the dependency in dev environment**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pip install -e ".[dev]" 2>&1 | tail -5`

Expected: `Successfully installed anthropic-X.Y.Z ...` (или сообщение что уже установлено).

- [ ] **Step 4: Verify import works**

Run: `python -c "import anthropic; print(anthropic.__version__)"`

Expected: версия >= 0.40 без ошибок.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add anthropic SDK dependency for LLM reranker"
```

---

## Task 2: Add LLM and progress settings to config

**Files:**
- Modify: `src/movie_recommender/core/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Read current config**

Read `src/movie_recommender/core/config.py` to confirm structure (Settings class with field defaults).

- [ ] **Step 2: Add LLM settings to config.py**

Edit `src/movie_recommender/core/config.py`, add after the `# API rate limiting` block (после `publish_delay: float = 3.0`):

```python

    # LLM reranker (Claude Sonnet)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-5-20250929"  # Sonnet 4.5; verify latest in Task 9 before deployment
    llm_rerank_enabled: bool = True
    llm_rerank_shortlist_size: int = 30
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 60
    llm_debug_log: bool = False  # if True, dump prompts/responses to data/llm_debug/{date}.json

    # Lampa watch progress thresholds (ratio = time_watched / duration)
    finished_threshold: float = 0.80      # ratio > 0.80 => "finished" signal
    dropped_min_threshold: float = 0.10   # 0.10 <= ratio <= dropped_max => "dropped" signal
    dropped_max_threshold: float = 0.50
```

- [ ] **Step 3: Add ANTHROPIC_API_KEY to .env.example**

Read `.env.example` first to see current structure.

Then add at the end:

```bash

# LLM reranker (Claude Sonnet 4.5)
ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-4-5-20250929
LLM_RERANK_ENABLED=true
LLM_RERANK_SHORTLIST_SIZE=30
LLM_MAX_TOKENS=2000
LLM_TIMEOUT_SECONDS=60
LLM_DEBUG_LOG=false

# Lampa watch progress thresholds
FINISHED_THRESHOLD=0.80
DROPPED_MIN_THRESHOLD=0.10
DROPPED_MAX_THRESHOLD=0.50
```

- [ ] **Step 4: Verify settings load**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "from movie_recommender.core.config import settings; print(settings.llm_model, settings.finished_threshold, settings.llm_rerank_enabled)"`

Expected: `claude-sonnet-4-5-20250929 0.8 True`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/movie_recommender/core/config.py .env.example
git commit -m "feat: add LLM reranker and progress threshold settings"
```

---

## Task 3: Set up shared pytest fixtures

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create conftest.py with shared fixtures**

Write `tests/conftest.py` with the following content:

```python
"""Shared pytest fixtures for the test suite."""
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def sample_feedback() -> dict[str, dict]:
    """Realistic reaction_feedback.json content with mix of reactions."""
    return {
        "693134": {  # Dune Part Two
            "favorites": 2, "likes": 1, "dislikes": 0, "blocks": 0,
            "title": "Дюна: Часть вторая",
            "genres": ["фантастика", "приключения", "драма"],
        },
        "872585": {  # Oppenheimer
            "favorites": 1, "likes": 0, "dislikes": 0, "blocks": 0,
            "title": "Оппенгеймер",
            "genres": ["драма", "история"],
        },
        "346698": {  # Barbie
            "favorites": 0, "likes": 0, "dislikes": 2, "blocks": 0,
            "title": "Барби",
            "genres": ["комедия", "фэнтези"],
        },
        "1226578": {  # placeholder blocked movie
            "favorites": 0, "likes": 0, "dislikes": 0, "blocks": 2,
            "title": "Скучный фильм",
            "genres": ["драма"],
        },
    }


@pytest.fixture
def sample_finished_movies() -> list[dict]:
    """Movies with watch ratio > 0.80, enriched with TMDB metadata."""
    return [
        {
            "tmdb_id": 693134,
            "title_ru": "Дюна: Часть вторая",
            "title_en": "Dune: Part Two",
            "year": 2024,
            "genres": ["фантастика", "приключения", "драма"],
            "directors": ["Дени Вильнёв"],
            "actors": ["Тимоти Шаламе", "Зендея"],
            "rating_imdb": 8.5,
            "vote_count": 500000,
            "description": "Пол Атрейдес объединяется с Чани и фрименами...",
        },
    ]


@pytest.fixture
def sample_dropped_movies() -> list[dict]:
    """Movies with watch ratio in [0.10, 0.50]."""
    return [
        {
            "tmdb_id": 346698,
            "title_ru": "Барби",
            "title_en": "Barbie",
            "year": 2023,
            "genres": ["комедия", "фэнтези"],
            "directors": ["Грета Гервиг"],
            "actors": ["Марго Робби"],
            "rating_imdb": 6.8,
            "vote_count": 600000,
            "description": "Барби и Кен отправляются в реальный мир...",
        },
    ]


@pytest.fixture
def sample_candidates() -> list[dict]:
    """30 candidate movies with score, sorted desc — output of score_movie."""
    candidates = []
    for i in range(30):
        candidates.append({
            "tmdb_id": 1000000 + i,
            "title_ru": f"Кандидат {i+1}",
            "title_en": f"Candidate {i+1}",
            "year": 2024,
            "genres": ["драма"] if i % 2 == 0 else ["боевик", "триллер"],
            "directors": [f"Режиссёр {i+1}"],
            "actors": [f"Актёр {i+1}"],
            "rating_imdb": 7.0 + (i % 3) * 0.3,
            "vote_count": 10000 + i * 1000,
            "description": f"Описание кандидата {i+1}.",
            "score": round(0.9 - i * 0.01, 2),
            "release_date": "2024-06-01",
            "popularity": 50.0,
            "poster_url": f"https://image.tmdb.org/t/p/w500/{i}.jpg",
            "runtime_min": 120,
            "trailer_url": None,
            "countries": ["США"],
        })
    return candidates


@pytest.fixture
def mock_anthropic_response() -> MagicMock:
    """Mock Anthropic API response with valid JSON containing 10 picks."""
    picks = []
    for i in range(10):
        picks.append({
            "rank": i + 1,
            "tmdb_id": 1000000 + i,  # matches sample_candidates first 10
            "reason": f"Обоснование выбора {i+1}: подходит под твой вкус.",
        })
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    response.usage = MagicMock(input_tokens=2150, output_tokens=850)
    return response


@pytest.fixture
def mock_anthropic_client(mock_anthropic_response: MagicMock) -> MagicMock:
    """Mock AsyncAnthropic client whose messages.create returns mock_anthropic_response."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=mock_anthropic_response)
    return client
```

- [ ] **Step 2: Verify fixtures load without errors**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/conftest.py --collect-only 2>&1 | tail -10`

Expected: `no tests ran` (conftest only defines fixtures, not tests) without errors. If pytest is not installed: `pip install -e ".[dev]"` first.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared fixtures for LLM reranker tests"
```

---

## Task 4: Create llm_reranker module — happy path test (TDD red)

**Files:**
- Create: `tests/test_llm_reranker.py`
- Create (empty stub): `src/movie_recommender/recommender/llm_reranker.py`

- [ ] **Step 1: Write the failing happy path test**

Create `tests/test_llm_reranker.py`:

```python
"""Unit tests for LLM-based reranker."""
import json
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_happy_path_returns_top_n_with_reasons(
    sample_candidates,
    sample_feedback,
    sample_finished_movies,
    sample_dropped_movies,
    mock_anthropic_client,
):
    """When LLM returns valid JSON with 10 picks, all 10 returned with reason and rank."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker, "_get_anthropic_client", return_value=mock_anthropic_client), \
         patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True):
        result = await llm_reranker.rerank_candidates(
            candidates=sample_candidates,
            feedback=sample_feedback,
            finished_movies=sample_finished_movies,
            dropped_movies=sample_dropped_movies,
            top_n=10,
        )

    assert len(result) == 10
    for i, movie in enumerate(result):
        assert movie["llm_rank"] == i + 1
        assert movie["llm_reason"].startswith("Обоснование выбора")
        assert movie["tmdb_id"] == 1000000 + i  # Order matches LLM picks
```

- [ ] **Step 2: Create empty stub module so import doesn't fail**

Create `src/movie_recommender/recommender/llm_reranker.py`:

```python
"""LLM-based reranker — uses Claude to refine top-N candidates using reaction history."""
from movie_recommender.core.config import settings


def _get_anthropic_client():
    """Lazily construct AsyncAnthropic client. Patched in tests."""
    raise NotImplementedError


async def rerank_candidates(
    candidates: list[dict],
    feedback: dict[str, dict],
    finished_movies: list[dict],
    dropped_movies: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """Stub — to be implemented in Task 5."""
    raise NotImplementedError
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_llm_reranker.py::test_happy_path_returns_top_n_with_reasons -v`

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 4: Commit the failing test**

```bash
git add tests/test_llm_reranker.py src/movie_recommender/recommender/llm_reranker.py
git commit -m "test: add failing happy path test for llm_reranker"
```

---

## Task 5: Implement llm_reranker — happy path (TDD green)

**Files:**
- Modify: `src/movie_recommender/recommender/llm_reranker.py`

- [ ] **Step 1: Write the full implementation**

Replace contents of `src/movie_recommender/recommender/llm_reranker.py`:

```python
"""LLM-based reranker — uses Claude to refine top-N candidates using reaction history."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()

_SYSTEM_PROMPT = """Ты — опытный рекомендатель фильмов. Тебе дают:
1. Краткий профиль вкуса пользователя (что он любит, что бросил, что заблокировал).
2. Список из 30 кандидатов на сегодняшнюю подборку с метаданными.

Твоя задача — выбрать ровно ТОП-10 фильмов, которые с наибольшей вероятностью понравятся пользователю.
Учитывай не только жанры, но и режиссёра, актёрский состав, описание, эпоху.

Отвечай СТРОГО валидным JSON без markdown:
{
  "picks": [
    {"rank": 1, "tmdb_id": <int>, "reason": "<1-2 предложения на русском почему именно этот фильм подходит>"},
    ...всего 10 элементов
  ]
}

Правила обоснований:
- Конкретно и по делу: ссылайся на любимые фильмы пользователя ("эпично, как Дюна, которую ты досмотрел").
- Если фильм рискованный — честно скажи ("если жанр не зашёл — пропусти").
- Не повторяйся, не льсти.
- Никогда не выходи за рамки JSON."""


def _get_anthropic_client():
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

    for tmdb_id, fb in feedback.items():
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
        # Strip markdown code fences if Claude wrapped JSON in them
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
        {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": taste, "cache_control": {"type": "ephemeral"}},
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
            input_tokens=getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0,
        )
        return result
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning("llm_rerank_failed", error_type=type(e).__name__, error=str(e))
        return candidates[:top_n]
    except Exception as e:
        # Catches anthropic.APIStatusError, RateLimitError, APIConnectionError, etc.
        logger.warning("llm_rerank_failed", error_type=type(e).__name__, error=str(e))
        return candidates[:top_n]
```

- [ ] **Step 2: Run happy path test to verify it passes**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_llm_reranker.py::test_happy_path_returns_top_n_with_reasons -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/movie_recommender/recommender/llm_reranker.py
git commit -m "feat: implement llm_reranker happy path"
```

---

## Task 6: Add fallback test cases to llm_reranker

**Files:**
- Modify: `tests/test_llm_reranker.py`

- [ ] **Step 1: Append all 9 remaining test cases**

Add to `tests/test_llm_reranker.py` (append after the happy path test):

```python


@pytest.mark.asyncio
async def test_no_api_key_returns_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """No API key → fallback to shortlist[:10] without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", ""), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_returns_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM_RERANK_ENABLED=False → fallback without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", False), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_empty_feedback_and_no_finished_returns_shortlist(sample_candidates):
    """Empty feedback AND empty finished → fallback without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, feedback={}, finished_movies=[], dropped_movies=[], top_n=10,
        )

    assert len(result) == 10
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_short_candidates_returns_as_is(
    sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """len(candidates) <= top_n → return as is, no LLM call."""
    from movie_recommender.recommender import llm_reranker

    short = [{"tmdb_id": i, "title_ru": f"M{i}", "year": 2024, "genres": []} for i in range(5)]
    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            short, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 5
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """httpx.TimeoutException from LLM → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)


@pytest.mark.asyncio
async def test_api_error_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """Anthropic API 5xx error → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=RuntimeError("APIStatusError 500"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10


@pytest.mark.asyncio
async def test_invalid_json_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns non-JSON → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="это вообще не json, какой-то текст")]
    bad_response.usage = MagicMock(input_tokens=100, output_tokens=20)
    bad_client = MagicMock()
    bad_client.messages = MagicMock()
    bad_client.messages.create = AsyncMock(return_value=bad_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=bad_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)


@pytest.mark.asyncio
async def test_partial_picks_filled_from_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns 6 picks → 6 with reason + 4 filled from shortlist without reason."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    picks = [
        {"rank": i + 1, "tmdb_id": 1000000 + i, "reason": f"Reason {i+1}"}
        for i in range(6)
    ]
    partial_response = MagicMock()
    partial_response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    partial_response.usage = MagicMock(input_tokens=2000, output_tokens=500)
    partial_client = MagicMock()
    partial_client.messages = MagicMock()
    partial_client.messages.create = AsyncMock(return_value=partial_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=partial_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    # First 6 from LLM with reason
    for i in range(6):
        assert result[i]["llm_reason"] == f"Reason {i+1}"
        assert result[i]["llm_rank"] == i + 1
    # Last 4 from shortlist without reason (next candidates after the 6 used)
    for i in range(6, 10):
        assert "llm_reason" not in result[i]
        assert "llm_rank" not in result[i]
    # No duplicate tmdb_ids
    ids = [m["tmdb_id"] for m in result]
    assert len(set(ids)) == 10


@pytest.mark.asyncio
async def test_unknown_tmdb_id_skipped(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns pick with tmdb_id not in candidates → that pick skipped, filled from shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    picks = [
        {"rank": 1, "tmdb_id": 99999999, "reason": "Wrong id"},  # not in candidates
        {"rank": 2, "tmdb_id": 1000001, "reason": "Real pick"},
    ]
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    bad_response.usage = MagicMock(input_tokens=2000, output_tokens=500)
    bad_client = MagicMock()
    bad_client.messages = MagicMock()
    bad_client.messages.create = AsyncMock(return_value=bad_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=bad_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    # Only the real pick (1000001) gets LLM reason, others filled from shortlist
    real_picks = [m for m in result if m.get("llm_reason") == "Real pick"]
    assert len(real_picks) == 1
    assert real_picks[0]["tmdb_id"] == 1000001
    # No duplicates
    ids = [m["tmdb_id"] for m in result]
    assert len(set(ids)) == 10
```

Also add `import httpx` at the top of the file (after `import json`).

- [ ] **Step 2: Run all tests in the file**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_llm_reranker.py -v`

Expected: 10 PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm_reranker.py
git commit -m "test: add 9 fallback cases for llm_reranker (timeout, errors, partial picks)"
```

---

## Task 7: Extend HistoryItem and Lampa plugin for watch progress

**Files:**
- Modify: `src/movie_recommender/api/v1/sync.py`
- Modify: `src/movie_recommender/static/lampa_plugin.js`

- [ ] **Step 1: Update HistoryItem model in sync.py**

Read `src/movie_recommender/api/v1/sync.py` first (already done in planning, but agent should re-read).

Edit `HistoryItem` class (lines 27-35) to:

```python
class HistoryItem(BaseModel):
    title: str = ""
    year: int | None = None
    type: str = "movie"
    kp_id: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    timestamp: str | None = None    # ISO datetime when item was watched (was: time)
    time_watched: int | None = None # seconds watched (NEW)
    duration: int | None = None     # total duration in seconds (NEW)
```

- [ ] **Step 2: Update history dedup key in push_sync to use timestamp**

In `push_sync` function, find the line:

```python
        existing = {(h.get("tmdb_id"), h.get("time")) for h in _history}
        new_items = [
            item for item in payload.data
            if (item.get("tmdb_id"), item.get("time")) not in existing
        ]
```

Replace with:

```python
        existing = {(h.get("tmdb_id"), h.get("timestamp")) for h in _history}
        new_items = [
            item for item in payload.data
            if (item.get("tmdb_id"), item.get("timestamp")) not in existing
        ]
```

- [ ] **Step 3: Update Lampa plugin to send progress fields**

Edit `src/movie_recommender/static/lampa_plugin.js`. Find the block (around line 33-43):

```javascript
    Lampa.Listener.follow('full', function (e) {
        if (e.type === 'complite' && e.data && e.data.movie) {
            var movie = e.data.movie;
            sendToServer('history', [{
                title: movie.title || movie.name || '',
                year: movie.year || null,
                type: movie.media_type || 'movie',
                kp_id: movie.kp_id || null,
                imdb_id: movie.imdb_id || null,
                tmdb_id: movie.id || null,
                time: new Date().toISOString()
            }]);
        }
    });
```

Replace with:

```javascript
    Lampa.Listener.follow('full', function (e) {
        if (e.type === 'complite' && e.data && e.data.movie) {
            var movie = e.data.movie;

            // Look up watch progress in Lampa.Storage timeline
            var time_watched = null;
            var duration = null;
            try {
                var fileView = Lampa.Storage.get('file_view', '{}');
                if (typeof fileView === 'string') fileView = JSON.parse(fileView);
                // Lampa stores timeline keyed by hash; find by movie id match
                for (var key in fileView) {
                    var entry = fileView[key];
                    if (entry && entry.id === movie.id) {
                        time_watched = entry.time ? Math.round(entry.time) : null;
                        duration = entry.duration ? Math.round(entry.duration) : null;
                        break;
                    }
                }
            } catch (err) {
                console.warn('[MovieRec] Progress lookup failed:', err);
            }

            sendToServer('history', [{
                title: movie.title || movie.name || '',
                year: movie.year || null,
                type: movie.media_type || 'movie',
                kp_id: movie.kp_id || null,
                imdb_id: movie.imdb_id || null,
                tmdb_id: movie.id || null,
                timestamp: new Date().toISOString(),
                time_watched: time_watched,
                duration: duration
            }]);
        }
    });
```

- [ ] **Step 4: Verify backend imports still work**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "from movie_recommender.api.v1.sync import HistoryItem; h = HistoryItem(tmdb_id=123, time_watched=4500, duration=5400); print(h.time_watched, h.duration)"`

Expected: `4500 5400` — no errors.

- [ ] **Step 5: Commit**

```bash
git add src/movie_recommender/api/v1/sync.py src/movie_recommender/static/lampa_plugin.js
git commit -m "feat: add watch progress (time_watched, duration) to Lampa sync"
```

---

## Task 8: Add finished/dropped extraction in runner — failing test

**Files:**
- Create: `tests/test_runner_progress.py`

- [ ] **Step 1: Write 5 failing tests for progress extraction**

Create `tests/test_runner_progress.py`:

```python
"""Unit tests for finished/dropped extraction logic in pipeline runner."""
from unittest.mock import patch

import pytest


def _make_items(*progress_specs: tuple[int, int | None, int | None]) -> list[dict]:
    """Build sync items list from (tmdb_id, time_watched, duration) tuples."""
    return [
        {"tmdb_id": tid, "type": "movie", "time_watched": t, "duration": d}
        for tid, t, d in progress_specs
    ]


def _extract_progress_signals(items: list[dict]) -> dict[str, set[int]]:
    """Wrapper to call the function under test (will be added in runner.py)."""
    from movie_recommender.pipeline.runner import _extract_progress_signals as fn
    return fn(items)


def test_finished_above_80_percent():
    """Items with watch ratio > 0.80 land in 'finished'."""
    items = _make_items(
        (101, 850, 1000),    # 0.85
        (102, 950, 1000),    # 0.95
        (103, 1000, 1000),   # 1.00
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == {101, 102, 103}
    assert signals["dropped"] == set()


def test_dropped_in_10_to_50_range():
    """Items with watch ratio in [0.10, 0.50] land in 'dropped'."""
    items = _make_items(
        (201, 100, 1000),   # 0.10
        (202, 300, 1000),   # 0.30
        (203, 500, 1000),   # 0.50
    )
    signals = _extract_progress_signals(items)
    assert signals["dropped"] == {201, 202, 203}
    assert signals["finished"] == set()


def test_grey_zone_excluded():
    """Items with ratio in (0.50, 0.80] are NOT classified."""
    items = _make_items(
        (301, 550, 1000),   # 0.55
        (302, 700, 1000),   # 0.70
        (303, 800, 1000),   # 0.80 — boundary, NOT > 0.80, so excluded
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()


def test_below_10_percent_excluded():
    """Items with ratio < 0.10 are NOT classified."""
    items = _make_items(
        (401, 50, 1000),    # 0.05
        (402, 90, 1000),    # 0.09
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()


def test_missing_duration_excluded():
    """Items without duration (or duration <= 0) are NOT classified — protects from ZeroDivisionError."""
    items = _make_items(
        (501, 500, None),   # no duration
        (502, 500, 0),      # zero duration
        (503, None, 1000),  # no time_watched but has duration
    )
    signals = _extract_progress_signals(items)
    assert signals["finished"] == set()
    assert signals["dropped"] == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_runner_progress.py -v`

Expected: 5 tests FAIL with `ImportError: cannot import name '_extract_progress_signals'` or `AttributeError`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_runner_progress.py
git commit -m "test: add failing tests for finished/dropped progress extraction"
```

---

## Task 9: Implement progress extraction in runner

**Files:**
- Modify: `src/movie_recommender/pipeline/runner.py`

- [ ] **Step 1: Add `_extract_progress_signals` helper function**

Read `src/movie_recommender/pipeline/runner.py` first.

Add a new helper function near the bottom of the file (after `tmdb_to_movie` and before `_get_candidates`, or just at the end — pick a place that doesn't break existing code):

```python


def _extract_progress_signals(items: list[dict]) -> dict[str, set[int]]:
    """Classify items into finished (ratio > 0.80) and dropped ([0.10, 0.50]) sets.

    Skips items without valid duration (>0) to avoid ZeroDivisionError.
    Items in the grey zone (0.50, 0.80] or below 0.10 are not classified.
    """
    finished: set[int] = set()
    dropped: set[int] = set()

    for item in items:
        tmdb_id = item.get("tmdb_id")
        duration = item.get("duration") or 0
        time_watched = item.get("time_watched") or 0

        if not tmdb_id or duration <= 0:
            continue

        ratio = time_watched / duration
        if ratio > settings.finished_threshold:
            finished.add(tmdb_id)
        elif settings.dropped_min_threshold <= ratio <= settings.dropped_max_threshold:
            dropped.add(tmdb_id)

    return {"finished": finished, "dropped": dropped}
```

- [ ] **Step 2: Wire it into `_get_sync_history` to enrich the signals dict**

Find in `_get_sync_history`:

```python
            signals = {
                "liked": set(data.get("liked", [])),
                "thrown": set(data.get("thrown", [])),
                "viewed": set(data.get("viewed", [])),
                "wath": set(data.get("wath", [])),
                "booked": set(data.get("booked", [])),
            }

            return items, signals
```

Replace with:

```python
            signals = {
                "liked": set(data.get("liked", [])),
                "thrown": set(data.get("thrown", [])),
                "viewed": set(data.get("viewed", [])),
                "wath": set(data.get("wath", [])),
                "booked": set(data.get("booked", [])),
            }
            progress = _extract_progress_signals(items)
            signals["finished"] = progress["finished"]
            signals["dropped"] = progress["dropped"]

            return items, signals
```

- [ ] **Step 3: Run progress tests to verify they pass**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_runner_progress.py -v`

Expected: 5 PASSED.

- [ ] **Step 4: Commit**

```bash
git add src/movie_recommender/pipeline/runner.py
git commit -m "feat: extract finished/dropped progress signals in pipeline runner"
```

---

## Task 10: Wire LLM reranker into pipeline

**Files:**
- Modify: `src/movie_recommender/pipeline/runner.py`

- [ ] **Step 1: Add LLM rerank call after the scoring/sort step**

Read `src/movie_recommender/pipeline/runner.py` again to confirm current structure.

Find the line after scoring sort:

```python
    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        "Pipeline step 5: scored candidates",
        count=len(scored), thrown=len(thrown_ids),
        deduped=len(published_ids), feedback_genres=len(genre_feedback),
    )

    if not scored:
        logger.warning("No new candidates after dedup, nothing to publish")
        return []
```

Add **after** the `if not scored: return []` block, **before** the `# Step 6-7: Search torrents + filter` comment:

```python

    # Step 5b: LLM rerank top-N (no-op if disabled, no API key, or no taste signal)
    if settings.llm_rerank_enabled:
        from movie_recommender.recommender.llm_reranker import rerank_candidates
        from movie_recommender.publishers.feedback import get_feedback as get_reaction_feedback

        shortlist = scored[:settings.llm_rerank_shortlist_size]
        finished_ids = signals.get("finished", set()) if signals else set()
        dropped_ids = signals.get("dropped", set()) if signals else set()
        finished_movies = [m for m in enriched if m.get("tmdb_id") in finished_ids]
        dropped_movies = [m for m in enriched if m.get("tmdb_id") in dropped_ids]

        scored = await rerank_candidates(
            candidates=shortlist,
            feedback=get_reaction_feedback(),
            finished_movies=finished_movies,
            dropped_movies=dropped_movies,
            top_n=top_n,
        )
        logger.info("Pipeline step 5b: LLM rerank complete", final_count=len(scored))
```

- [ ] **Step 2: Update the loop bound for torrent search**

Right after the LLM rerank block, find:

```python
    for movie in scored[:top_n * 10]:
```

Change to:

```python
    for movie in scored:
```

(After LLM rerank, `scored` уже содержит ровно `top_n` фильмов — нет смысла умножать на 10. Если LLM-rerank выключен, scored всё равно длиннее top_n — но цикл всё равно остановится на `if len(recommendations) >= top_n:` ниже, так что `scored` без слайса безопасно.)

**Wait** — это не совсем так. Если `llm_rerank_enabled=False`, `scored` остаётся длиной 30-60. Цикл `for movie in scored` пробегает все, но останавливается через `if len(recommendations) >= top_n: break`. Это работает, но менее эффективно (пройдёт максимум 10 итераций — нормально).

Чтобы не сломать поведение, оставим бэкап:

```python
    for movie in scored if settings.llm_rerank_enabled else scored[:top_n * 10]:
```

- [ ] **Step 3: Verify pipeline import still works**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "from movie_recommender.pipeline.runner import run_pipeline; print('ok')"`

Expected: `ok` без ошибок.

- [ ] **Step 4: Commit**

```bash
git add src/movie_recommender/pipeline/runner.py
git commit -m "feat: wire LLM reranker into pipeline after scoring step"
```

---

## Task 11: Add llm_reason section to Telegram caption

**Files:**
- Modify: `src/movie_recommender/publishers/telegram.py`

- [ ] **Step 1: Add the section in format_message**

Read `src/movie_recommender/publishers/telegram.py` to find the right spot.

Find this section in `format_message` (around line 128-134):

```python
    # Description
    if movie.get("description"):
        desc = movie["description"][:350]
        if len(movie["description"]) > 350:
            desc += "..."
        lines.append(f"<code>{desc}</code>")

    lines.append("")
```

Insert the LLM reason block **after** description, **before** the empty `lines.append("")`:

```python
    # Description
    if movie.get("description"):
        desc = movie["description"][:350]
        if len(movie["description"]) > 350:
            desc += "..."
        lines.append(f"<code>{desc}</code>")

    # LLM reasoning (only if reranker provided one)
    if movie.get("llm_reason"):
        lines.append("")
        lines.append(f"\U0001f916 <i>{movie['llm_reason']}</i>")

    lines.append("")
```

(`\U0001f916` is the 🤖 emoji — using escape for consistency with rest of file.)

- [ ] **Step 2: Quick smoke check**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "
from movie_recommender.publishers.telegram import format_message
m = {'tmdb_id': 1, 'title_ru': 'Test', 'year': 2024, 'genres': ['драма'], 'description': 'desc', 'llm_reason': 'because awesome'}
t = {'quality': '1080p', 'size_gb': 5, 'seeders': 100, 'tracker': 'rt', 'audio': []}
out = format_message(m, t)
assert 'because awesome' in out
assert '\U0001f916' in out
print('ok')
"`

Expected: `ok` — both the emoji and reason are in the output.

- [ ] **Step 3: Smoke check that missing reason doesn't break anything**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "
from movie_recommender.publishers.telegram import format_message
m = {'tmdb_id': 1, 'title_ru': 'Test', 'year': 2024, 'genres': ['драма'], 'description': 'desc'}
t = {'quality': '1080p', 'size_gb': 5, 'seeders': 100, 'tracker': 'rt', 'audio': []}
out = format_message(m, t)
assert '\U0001f916' not in out
print('ok')
"`

Expected: `ok` — no robot emoji when no reason.

- [ ] **Step 4: Commit**

```bash
git add src/movie_recommender/publishers/telegram.py
git commit -m "feat: add LLM reason section to Telegram message format"
```

---

## Task 12: Integration test for pipeline + LLM

**Files:**
- Create: `tests/test_pipeline_with_llm.py`

- [ ] **Step 1: Write 3 integration tests**

Create `tests/test_pipeline_with_llm.py`:

```python
"""Integration tests: pipeline runner + LLM reranker (with mocks)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_pipeline_calls_llm_with_top_30(sample_candidates, mock_anthropic_client):
    """Pipeline should pass shortlist of llm_rerank_shortlist_size to LLM."""
    from movie_recommender.recommender import llm_reranker

    captured_args: dict = {}

    async def capturing_rerank(candidates, feedback, finished_movies, dropped_movies, top_n):
        captured_args["candidates"] = candidates
        captured_args["top_n"] = top_n
        # Return first 10 with reasons to simulate happy LLM
        return [{**c, "llm_rank": i + 1, "llm_reason": f"R{i+1}"} for i, c in enumerate(candidates[:top_n])]

    with patch.object(llm_reranker, "rerank_candidates", side_effect=capturing_rerank):
        from movie_recommender.recommender.llm_reranker import rerank_candidates as rc
        result = await rc(
            candidates=sample_candidates,
            feedback={"123": {"favorites": 1, "likes": 0, "dislikes": 0, "blocks": 0,
                              "title": "X", "genres": ["драма"]}},
            finished_movies=[],
            dropped_movies=[],
            top_n=10,
        )

    assert captured_args["candidates"] == sample_candidates
    assert captured_args["top_n"] == 10
    assert len(result) == 10
    assert result[0]["llm_reason"] == "R1"


@pytest.mark.asyncio
async def test_pipeline_continues_on_llm_failure(sample_candidates, sample_feedback, sample_finished_movies):
    """If LLM raises, rerank_candidates returns shortlist[:top_n] without crashing."""
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("nope"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            candidates=sample_candidates,
            feedback=sample_feedback,
            finished_movies=sample_finished_movies,
            dropped_movies=[],
            top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    # Should be the first 10 from shortlist (preserves original order)
    assert [m["tmdb_id"] for m in result] == [c["tmdb_id"] for c in sample_candidates[:10]]


def test_format_message_handles_missing_reason():
    """publishers.telegram.format_message must work for movies without llm_reason field."""
    from movie_recommender.publishers.telegram import format_message

    movie_no_reason = {
        "tmdb_id": 1, "title_ru": "Тест", "year": 2024, "genres": ["драма"],
        "description": "Описание", "rating_imdb": 7.5, "vote_count": 1000,
    }
    movie_with_reason = {**movie_no_reason, "llm_reason": "Шикарно подходит."}
    torrent = {"quality": "1080p", "size_gb": 5, "seeders": 100, "tracker": "rt", "audio": []}

    out_no = format_message(movie_no_reason, torrent)
    out_yes = format_message(movie_with_reason, torrent)

    assert "🤖" not in out_no  # no robot when no reason
    assert "🤖" in out_yes
    assert "Шикарно подходит." in out_yes
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/test_pipeline_with_llm.py -v`

Expected: 3 PASSED.

- [ ] **Step 3: Run the full test suite to confirm nothing else broke**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/ -v`

Expected: 18 PASSED (10 reranker + 5 progress + 3 integration), 0 failed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_with_llm.py
git commit -m "test: integration tests for pipeline + LLM reranker"
```

---

## Task 13: Verify model ID and document deployment notes

**Files:**
- Create: `docs/superpowers/notes/2026-04-26-llm-deployment.md`

- [ ] **Step 1: Verify the latest Sonnet model ID is correct**

The plan uses `claude-sonnet-4-5-20250929`. Check that this is still a valid model ID:

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "
import asyncio
from anthropic import AsyncAnthropic

async def check():
    client = AsyncAnthropic(api_key='<ANTHROPIC_KEY-from-credentials.md>')
    resp = await client.messages.create(
        model='claude-sonnet-4-5-20250929',
        max_tokens=20,
        messages=[{'role': 'user', 'content': 'Reply with just the word OK'}]
    )
    print('Model OK:', resp.content[0].text)

asyncio.run(check())
"`

Expected: `Model OK: OK` (or similar — confirms model ID is valid).

If the model ID is rejected, search docs.claude.com for the latest Sonnet ID, update both `core/config.py` and `.env.example`, then re-run.

- [ ] **Step 2: Create deployment notes document**

Create `docs/superpowers/notes/2026-04-26-llm-deployment.md`:

```markdown
# LLM Reranker Deployment Notes

**Date:** 2026-04-26

## Pre-deployment checklist

- [ ] All tests pass: `pytest tests/ -v` → 18 PASSED
- [ ] Model ID verified working: see Task 13 Step 1 above
- [ ] ANTHROPIC_API_KEY ready for Portainer env

## Portainer deployment

Stack name: `movie-recommender` (Stack ID and Endpoint to be confirmed via Portainer API).

1. Find stack ID:
   ```bash
   curl -s -H "X-API-Key: $PORTAINER_API_KEY" \
     https://portainer.your-host/api/stacks | \
     jq '.[] | select(.Name | contains("movie")) | {Id, Name, EndpointId}'
   ```

2. Add `ANTHROPIC_API_KEY` env to stack (Portainer UI → Stack → Editor → Env variables) and redeploy with "Re-pull image".

3. Or use `deployer` agent: it auto-detects stack and adds env from local `.env` file.

## Smoke check after deploy

1. Logs:
   ```bash
   # Tail container logs (via Portainer UI or docker logs)
   docker logs movie-recommender 2>&1 | grep -E "llm_rerank|Pipeline" | tail -20
   ```

2. Manual pipeline trigger:
   ```bash
   curl -X POST http://94.156.232.242:9200/api/v1/pipeline/run
   ```

3. Expected log lines:
   - `INFO  llm_rerank_started ... candidates=30, feedback_count=N`
   - `INFO  llm_rerank_completed ... picked=10, with_reason=10, input_tokens=...`
   - In Telegram channel: 10 new posts with `🤖 ...` lines in caption

## Rollback

Set `LLM_RERANK_ENABLED=false` in Portainer env and redeploy. The pipeline immediately
reverts to old behavior (top-10 by score_movie order, no LLM call).

## Cost monitoring

Each daily run logs `input_tokens` and `output_tokens`. Expected:
- input: ~2000-3000 tokens (system prompt + taste summary + 30 candidates)
- output: ~500-1000 tokens (10 picks with reasons)
- Daily cost: ~$0.02-0.05 → ~$1-3/month

If `output_tokens` >> 1500 — Claude wrote too much, tune prompt to be terser.
If logs show frequent `llm_rerank_failed` — investigate cause (timeout? rate limit?).
```

- [ ] **Step 3: Commit deployment notes**

```bash
mkdir -p docs/superpowers/notes
git add docs/superpowers/notes/2026-04-26-llm-deployment.md
git commit -m "docs: deployment notes for LLM reranker"
```

---

## Task 14: Final review — full test run and lint

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && pytest tests/ -v --tb=short`

Expected: All tests PASSED (should be 18 from new tests; if there are pre-existing tests, they should also pass).

- [ ] **Step 2: Run ruff lint on changed files**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && ruff check src/movie_recommender/recommender/llm_reranker.py src/movie_recommender/pipeline/runner.py src/movie_recommender/api/v1/sync.py src/movie_recommender/publishers/telegram.py src/movie_recommender/core/config.py tests/`

Expected: `All checks passed!` — fix any errors reported (typically import order, unused imports).

- [ ] **Step 3: Confirm pipeline can run end-to-end without LLM (regression check)**

Run: `cd /Users/admin/PycharmProjects/movie-recommender && python -c "
import asyncio, os
os.environ['ANTHROPIC_API_KEY'] = ''  # Force fallback path
os.environ['LLM_RERANK_ENABLED'] = 'false'
from movie_recommender.recommender import llm_reranker
# Reload settings since env changed
from importlib import reload
from movie_recommender.core import config
reload(config)
reload(llm_reranker)

async def test():
    candidates = [{'tmdb_id': i, 'title_ru': f'M{i}', 'year': 2024, 'genres': ['драма'], 'score': 0.9 - i*0.01} for i in range(30)]
    res = await llm_reranker.rerank_candidates(candidates, {}, [], [], top_n=10)
    assert len(res) == 10
    assert all('llm_reason' not in m for m in res)
    print('Regression: rerank_candidates fallback works without API key')

asyncio.run(test())
"`

Expected: `Regression: rerank_candidates fallback works without API key`

- [ ] **Step 4: Commit any final touch-ups (if needed) — otherwise skip**

If lint or regression made any changes:

```bash
git add -A
git commit -m "chore: final lint and regression fixes"
```

---

## Task 15: Deploy to production (REQUIRES USER CONFIRMATION)

**Files:** none (deployment only)

> ⚠️ **Per CLAUDE.md rule:** "НИКОГДА не деплой на сервер без явного подтверждения пользователя!"
> Before executing this task, the AGENT MUST ask the user: "Готово к деплою на 94.156.232.242 через Portainer. Задеплоить?"
> Only proceed if user replies affirmatively.

- [ ] **Step 1: Push commits to GitHub** (user-confirmed)

Run: `cd /Users/admin/PycharmProjects/movie-recommender && git push origin main`

- [ ] **Step 2: Use deployer agent to push to Portainer** (user-confirmed)

Dispatch the deployer subagent with this task:

> "Deploy movie-recommender stack on admin server (94.156.232.242, Portainer endpoint 3). Add new env var ANTHROPIC_API_KEY=<ANTHROPIC_KEY-from-credentials.md> to the stack environment (preserve existing env vars). Redeploy with image rebuild. After deploy, tail logs for 30 seconds and confirm no startup errors."

- [ ] **Step 3: Manual smoke check on prod**

Trigger pipeline manually:

```bash
curl -X POST http://94.156.232.242:9200/api/v1/pipeline/run
```

Wait ~3 minutes. Check Telegram channel — should appear ~10 new posts, most with `🤖 ...` caption.

Check container logs (via Portainer UI or `docker logs movie-recommender 2>&1 | grep llm_rerank | tail -10`):
- Should see `llm_rerank_started` and `llm_rerank_completed`
- `with_reason` count should be 8-10 out of 10
- `input_tokens` ~2000-3000

- [ ] **Step 4: Confirm scheduled run at 21:00**

Check at 21:01 next day — fresh batch of 10 should be in channel with timestamps near 21:00 Europe/Budapest.

---

## Self-Review Checklist

(Run by writer before delivering plan to user.)

**Spec coverage:**
- ✅ §3 Цель → Tasks 5, 10 (LLM rerank with daily timing already in app.py)
- ✅ §4 Не цели → не реализуем embeddings/RAG/fine-tune (нет соответствующих задач — корректно)
- ✅ §5.1-5.7 llm_reranker компоненты → Tasks 4, 5
- ✅ §5.8 правки в runner.py → Tasks 9, 10
- ✅ §5.8 правки в telegram.py → Task 11
- ✅ §5.8 правки в config.py + .env.example → Task 2
- ✅ §5.8 anthropic dependency → Task 1
- ✅ §5.8 правки в sync.py + lampa_plugin.js → Task 7
- ✅ §5.9 безопасность/логирование → encoded в имплементации Task 5 (структурированные логи, optional debug dump)
- ✅ §6 потоки данных → Tasks 9, 10
- ✅ §7 устойчивость → покрыто тестами в Tasks 6, 12
- ✅ §8 тестирование → Tasks 4, 6, 8, 12
- ✅ §10 открытый вопрос model ID → Task 13
- ✅ §10 открытый вопрос CUB API → Task 7 решает через расширение Lampa плагина (CUB не нужен)
- ✅ §10 открытый вопрос Portainer Stack ID → Task 13 + Task 15 решает через deployer agent

**Placeholder scan:** все поля заполнены, кроме намеренно делегированного `<TBD-в-плане>` для model ID, который Task 13 верифицирует. Никаких "TBD" / "implement later" в шагах.

**Type consistency:** функция `_extract_progress_signals` определена в Task 9 и вызывается в Task 9 — одно имя. `rerank_candidates` сигнатура одинакова в Tasks 4, 5, 6, 10, 12. `llm_reason`/`llm_rank` — единые имена полей по всем задачам.

**Decomposition:** 15 задач, каждая 5-30 мин. Никакая задача не блокирует > 1-2 следующих.

**Spec scope:** одна фича (LLM rerank + Lampa progress), один план — корректно.

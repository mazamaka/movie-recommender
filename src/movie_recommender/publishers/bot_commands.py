"""Telegram bot command handler for discussion group."""
import asyncio

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.ingest.cub_client import fetch_cub_reactions
from movie_recommender.ingest.tmdb_client import search_movie, search_tv

logger = structlog.get_logger()

# TMDB genre ID -> Russian name mapping
_GENRE_NAMES: dict[int, str] = {
    28: "боевик", 12: "приключения", 16: "мультфильм", 35: "комедия",
    80: "криминал", 99: "документальный", 18: "драма", 10751: "семейный",
    14: "фэнтези", 36: "история", 27: "ужасы", 10402: "музыка",
    9648: "детектив", 10749: "мелодрама", 878: "фантастика", 10770: "ТВ",
    53: "триллер", 10752: "военный", 37: "вестерн",
    10759: "боевик", 10762: "детский", 10763: "новости", 10764: "реалити",
    10765: "фантастика", 10766: "мыльная опера", 10767: "ток-шоу", 10768: "война",
}


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_votes(count: int) -> str:
    """Format vote count: 1500 -> '1.5K'."""
    if count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def _quality_badge(fire: int, shit: int) -> str:
    """Build quality badge from CUB reactions."""
    total = fire + shit
    if total == 0:
        return ""
    ratio = fire / total
    if ratio >= 0.8:
        badge = "\u2705"  # green check
    elif ratio >= 0.6:
        badge = "\U0001f7e1"  # yellow circle
    else:
        badge = "\u26a0\ufe0f"  # warning
    return f"Lampa: {badge} \U0001f525{fire} \U0001f4a9{shit} ({ratio:.0%})"


async def handle_command(message: dict) -> None:
    """Dispatch bot commands from discussion group messages."""
    text = message.get("text", "")
    if not text.startswith("/"):
        return

    chat = message.get("chat")
    if not chat:
        return
    chat_id = chat.get("id")
    msg_id = message.get("message_id")
    if not chat_id or not msg_id:
        return

    # Parse command and args: "/search Matrix" -> ("search", "Matrix")
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # strip @botname
    args = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/search":
        await _cmd_search(chat_id, args, msg_id)
    elif cmd == "/top":
        await _cmd_top(chat_id, msg_id)
    elif cmd in ("/help", "/start"):
        await _cmd_help(chat_id, msg_id)
    else:
        return

    logger.info("Bot command handled", cmd=cmd, args=args, chat_id=chat_id)


async def _cmd_search(chat_id: int, query: str, reply_to: int) -> None:
    """Search movies and TV shows on TMDB."""
    if not query:
        await _send_reply(chat_id, "Укажи название после /search\nПример: /search Матрица", reply_to)
        return

    try:
        movies, shows = await asyncio.gather(search_movie(query), search_tv(query))
    except Exception as e:
        logger.warning("TMDB search failed", error=type(e).__name__)
        await _send_reply(chat_id, "Ошибка поиска, попробуй позже", reply_to)
        return

    # Merge and deduplicate, prefer movies
    results: list[dict] = []
    seen_ids: set[str] = set()

    for m in movies[:5]:
        key = f"m{m['id']}"
        if key not in seen_ids:
            seen_ids.add(key)
            results.append({
                "type": "movie",
                "id": m["id"],
                "title": m.get("title", ""),
                "original": m.get("original_title", ""),
                "year": (m.get("release_date") or "")[:4],
                "rating": m.get("vote_average", 0),
                "votes": m.get("vote_count", 0),
                "genres": [_GENRE_NAMES.get(g, "") for g in m.get("genre_ids", [])],
            })

    for s in shows[:3]:
        key = f"t{s['id']}"
        if key not in seen_ids:
            seen_ids.add(key)
            results.append({
                "type": "tv",
                "id": s["id"],
                "title": s.get("name", ""),
                "original": s.get("original_name", ""),
                "year": (s.get("first_air_date") or "")[:4],
                "rating": s.get("vote_average", 0),
                "votes": s.get("vote_count", 0),
                "genres": [_GENRE_NAMES.get(g, "") for g in s.get("genre_ids", [])],
            })

    # Sort by rating descending, take top 5
    results.sort(key=lambda x: x["rating"], reverse=True)
    results = results[:5]

    if not results:
        safe_q = _escape_html(query)
        await _send_reply(chat_id, f'По запросу "{safe_q}" ничего не найдено', reply_to)
        return

    # Fetch CUB community reactions
    movie_ids = [r["id"] for r in results if r["type"] == "movie"]
    cub = await fetch_cub_reactions(movie_ids) if movie_ids else {}

    safe_q = _escape_html(query)
    lines = [f'<b>Результаты поиска: "{safe_q}"</b>\n']
    for i, r in enumerate(results, 1):
        icon = "\U0001f3ac" if r["type"] == "movie" else "\U0001f4fa"
        rating = f'{r["rating"]:.1f}' if r["rating"] else "—"
        votes = r.get("votes", 0)
        genres = ", ".join(g for g in r["genres"] if g)
        year = r["year"] or "?"

        title = _escape_html(r["title"])
        line = f'{icon} <b>{i}. {title}</b> ({year})'
        line += f'  \u2b50 {rating}'
        if votes:
            line += f' ({_format_votes(votes)})'
        lines.append(line)

        if r["original"] and r["original"] != r["title"]:
            lines.append(f'   {_escape_html(r["original"])}')

        # CUB quality line
        c = cub.get(r["id"], {})
        cub_fire = c.get("fire", 0)
        cub_shit = c.get("shit", 0)
        if cub_fire or cub_shit:
            quality = _quality_badge(cub_fire, cub_shit)
            lines.append(f'   {quality}')

        if genres:
            lines.append(f'   {genres}')
        lines.append("")

    await _send_reply(chat_id, "\n".join(lines), reply_to)


async def _cmd_top(chat_id: int, reply_to: int) -> None:
    """Show current published recommendations."""
    from movie_recommender.publishers.feedback import get_published, get_feedback

    published = get_published()
    feedback = get_feedback()

    if not published:
        await _send_reply(chat_id, "Пока нет опубликованных рекомендаций", reply_to)
        return

    # Build list sorted by score
    items = []
    for msg_id, info in published.items():
        tmdb_id = str(info.get("tmdb_id", ""))
        fb = feedback.get(tmdb_id, {})
        likes = fb.get("favorites", 0) + fb.get("likes", 0)
        dislikes = fb.get("dislikes", 0) + fb.get("blocks", 0)
        items.append({**info, "likes": likes, "dislikes": dislikes})

    items.sort(key=lambda x: x.get("likes", 0) - x.get("dislikes", 0), reverse=True)
    items = items[:10]

    lines = ["<b>\U0001f3c6 Текущий топ рекомендаций</b>\n"]
    for i, m in enumerate(items, 1):
        title = _escape_html(m.get("title", "Без названия"))
        year = m.get("year", "?")
        rating = m.get("vote_average")
        rating_str = f'{rating:.1f}' if rating else "—"
        likes = m.get("likes", 0)
        dislikes = m.get("dislikes", 0)

        line = f'<b>{i}. {title}</b> ({year}) \u2b50 {rating_str}'
        if likes or dislikes:
            line += f'  \U0001f44d{likes} \U0001f44e{dislikes}'
        lines.append(line)

    await _send_reply(chat_id, "\n".join(lines), reply_to)


async def _cmd_help(chat_id: int, reply_to: int) -> None:
    """Show available commands."""
    text = (
        "<b>Доступные команды:</b>\n\n"
        "/search &lt;название&gt; — поиск фильмов и сериалов\n"
        "/top — текущий топ рекомендаций\n"
        "/help — список команд"
    )
    await _send_reply(chat_id, text, reply_to)


async def _send_reply(chat_id: int, text: str, reply_to: int | None = None) -> None:
    """Send a reply message via Telegram Bot API."""
    if not settings.telegram_bot_token:
        return

    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json=payload,
            )
            result = resp.json()
            if not result.get("ok"):
                logger.warning("Bot reply failed", error=result.get("description"))
    except Exception as e:
        logger.warning("Bot reply error", error=type(e).__name__)


async def register_bot_commands() -> None:
    """Register bot commands menu via setMyCommands."""
    if not settings.telegram_bot_token:
        return

    commands = [
        {"command": "search", "description": "Поиск фильмов и сериалов"},
        {"command": "top", "description": "Текущий топ рекомендаций"},
        {"command": "help", "description": "Список команд"},
    ]

    scopes: list[dict] = [
        {"type": "default"},
        {"type": "all_group_chats"},
    ]
    if settings.telegram_discussion_group_id:
        scopes.append({"type": "chat", "chat_id": int(settings.telegram_discussion_group_id)})
    if settings.telegram_channel_id:
        scopes.append({"type": "chat", "chat_id": int(settings.telegram_channel_id)})

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for scope in scopes:
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyCommands",
                    json={"commands": commands, "scope": scope},
                )
                result = resp.json()
                if not result.get("ok"):
                    logger.warning("setMyCommands failed", scope=scope["type"], error=result.get("description"))
            # Set bot description (shown when opening bot profile)
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyDescription",
                json={"description": "Умный рекомендатор фильмов и сериалов.\n\nИщу фильмы, показываю топ рекомендаций с рейтингами и отзывами. Работаю в группе обсуждения канала."},
            )
            # Set short description (shown in bot list / chat header)
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/setMyShortDescription",
                json={"short_description": "Поиск и рекомендации фильмов"},
            )
            logger.info("Bot commands and description registered", count=len(commands))
    except Exception as e:
        logger.warning("Failed to register bot commands", error=type(e).__name__)

"""Telegram reaction feedback tracker."""
import asyncio
import json

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.core.storage import load_json, save_json

logger = structlog.get_logger()

# Persisted data
_published: dict[str, dict] = {}  # message_id -> movie info
_feedback: dict[str, dict] = {}   # tmdb_id -> {likes, dislikes, genres}
_poll_offset: int = 0
_poll_paused: bool = False
_lock = asyncio.Lock()  # guards _poll_offset / _feedback mutations in poll_reactions

FAVORITE_EMOJIS = {"🔥", "❤️", "🏆", "⚡"}  # Super liked - strong positive boost
LIKE_EMOJIS = {"👍", "🎉", "😍", "💯"}  # Liked
DISLIKE_EMOJIS = {"👎"}  # Disliked
BLOCK_EMOJIS = {"💩"}  # Block similar genres from recommendations


def init_feedback():
    """Load persisted feedback data.

    Uses .clear() + .update() to mutate in-place so that any module
    that imported the dict reference sees the updated data.
    """
    global _poll_offset
    _published.clear()
    _published.update(load_json("published_messages", {}))
    _feedback.clear()
    _feedback.update(load_json("reaction_feedback", {}))
    _poll_offset = load_json("poll_offset", {"offset": 0}).get("offset", 0)


def save_published(message_id: int, movie: dict):
    """Save mapping of Telegram message_id to movie data.

    NOTE: This is intentionally sync -- called from sync context in runner.py.
    ``_published`` is also read inside ``poll_reactions`` (via ``_process_reaction``
    / ``_process_reaction_count``), but writes here happen only between poll
    cycles (publish pauses the poll loop), so no data-race in practice.
    """
    poster = movie.get("poster_url", "")
    poster_path = poster.replace("https://image.tmdb.org/t/p/w500", "") if poster else ""
    _published[str(message_id)] = {
        "tmdb_id": movie.get("tmdb_id"),
        "title": movie.get("title_ru", ""),
        "original_title": movie.get("title_en", ""),
        "genres": movie.get("genres", []),
        "score": movie.get("score"),
        "year": movie.get("year"),
        "vote_average": movie.get("rating_imdb"),
        "vote_count": movie.get("vote_count", 0),
        "poster_path": poster_path,
        "countries": movie.get("countries", []),
    }
    save_json("published_messages", _published)


def get_published() -> dict[str, dict]:
    """Get all published messages: {message_id: movie_info}."""
    return _published


def get_published_tmdb_ids() -> set[int]:
    """Get set of already published tmdb_ids to avoid duplicates."""
    ids = set()
    for msg_data in _published.values():
        tmdb_id = msg_data.get("tmdb_id")
        if tmdb_id:
            ids.add(tmdb_id)
    return ids


def get_feedback() -> dict[str, dict]:
    """Get all feedback data: {tmdb_id: {likes, dislikes, genres, title}}."""
    return _feedback


def get_genre_feedback() -> dict[str, float]:
    """Get genre scores from feedback: {genre: score}.

    Positive score = users like this genre, negative = dislike.
    Favorites give 2x weight, blocks give -3x penalty.
    """
    genre_scores: dict[str, float] = {}
    for tmdb_id, fb in _feedback.items():
        favorites = fb.get("favorites", 0)
        likes = fb.get("likes", 0)
        dislikes = fb.get("dislikes", 0)
        blocks = fb.get("blocks", 0)
        total = favorites + likes + dislikes + blocks
        if total == 0:
            continue
        # Weighted score: favorites=+2, likes=+1, dislikes=-1, blocks=-3
        score = (favorites * 2 + likes - dislikes - blocks * 3) / total
        for genre in fb.get("genres", []):
            if genre not in genre_scores:
                genre_scores[genre] = 0.0
            genre_scores[genre] += score
    return genre_scores


def get_blocked_genres() -> set[str]:
    """Get genres blocked by 💩 reactions."""
    blocked: dict[str, int] = {}
    for tmdb_id, fb in _feedback.items():
        if fb.get("blocks", 0) > 0:
            for genre in fb.get("genres", []):
                blocked[genre] = blocked.get(genre, 0) + fb["blocks"]
    # Block genre if it has 2+ block reactions total
    return {g for g, count in blocked.items() if count >= 2}


async def poll_reactions():
    """Poll Telegram for reaction updates on published messages."""
    global _poll_offset

    if not settings.telegram_bot_token:
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    params = {
        "offset": _poll_offset,
        "timeout": 5,
        "allowed_updates": json.dumps(["message", "message_reaction", "message_reaction_count", "channel_post"]),
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        if not data.get("ok"):
            logger.warning("Telegram getUpdates failed", response=data)
            return

        async with _lock:
            for update in data.get("result", []):
                _poll_offset = update["update_id"] + 1
                reaction_count = update.get("message_reaction_count")
                if reaction_count:
                    _process_reaction_count(reaction_count)
                reaction = update.get("message_reaction")
                if reaction:
                    _process_reaction(reaction)

            # Save offset
            save_json("poll_offset", {"offset": _poll_offset})

    except Exception as e:
        logger.warning("Reaction poll error", error=str(e))


def _process_reaction(reaction_data: dict):
    """Process message_reaction update (personal, non-anonymous reactions)."""
    msg = reaction_data.get("message_id") or reaction_data.get("message", {}).get("message_id")
    message_id = str(msg or "")
    movie_info = _published.get(message_id)
    if not movie_info:
        return

    tmdb_id = str(movie_info.get("tmdb_id", message_id))
    # Get current feedback or create new
    fb = _feedback.get(tmdb_id, {
        "favorites": 0, "likes": 0, "dislikes": 0, "blocks": 0,
        "title": movie_info.get("title", ""), "genres": movie_info.get("genres", []),
    })

    # new_reaction list contains added reactions
    for r in reaction_data.get("new_reaction", []):
        emoji = r.get("emoji", "")
        if emoji in FAVORITE_EMOJIS:
            fb["favorites"] = fb.get("favorites", 0) + 1
        elif emoji in LIKE_EMOJIS:
            fb["likes"] = fb.get("likes", 0) + 1
        elif emoji in DISLIKE_EMOJIS:
            fb["dislikes"] = fb.get("dislikes", 0) + 1
        elif emoji in BLOCK_EMOJIS:
            fb["blocks"] = fb.get("blocks", 0) + 1

    # old_reaction list contains removed reactions
    for r in reaction_data.get("old_reaction", []):
        emoji = r.get("emoji", "")
        if emoji in FAVORITE_EMOJIS:
            fb["favorites"] = max(fb.get("favorites", 0) - 1, 0)
        elif emoji in LIKE_EMOJIS:
            fb["likes"] = max(fb.get("likes", 0) - 1, 0)
        elif emoji in DISLIKE_EMOJIS:
            fb["dislikes"] = max(fb.get("dislikes", 0) - 1, 0)
        elif emoji in BLOCK_EMOJIS:
            fb["blocks"] = max(fb.get("blocks", 0) - 1, 0)

    fb["title"] = movie_info.get("title", "")
    fb["genres"] = movie_info.get("genres", [])
    _feedback[tmdb_id] = fb
    save_json("reaction_feedback", _feedback)

    logger.info(
        "Personal reaction updated",
        title=movie_info.get("title"),
        favorites=fb["favorites"], likes=fb["likes"],
        dislikes=fb["dislikes"], blocks=fb["blocks"],
    )


def _process_reaction_count(reaction_data: dict):
    """Process message_reaction_count update."""
    message_id = str(reaction_data.get("message_id", ""))
    reactions = reaction_data.get("reactions", [])

    # Find which movie this message belongs to
    movie_info = _published.get(message_id)
    if not movie_info:
        return

    tmdb_id = str(movie_info.get("tmdb_id", message_id))
    favorites = 0
    likes = 0
    dislikes = 0
    blocks = 0

    for r in reactions:
        emoji = r.get("type", {}).get("emoji", "")
        count = r.get("total_count", 0)
        if emoji in FAVORITE_EMOJIS:
            favorites += count
        elif emoji in LIKE_EMOJIS:
            likes += count
        elif emoji in DISLIKE_EMOJIS:
            dislikes += count
        elif emoji in BLOCK_EMOJIS:
            blocks += count

    _feedback[tmdb_id] = {
        "favorites": favorites,
        "likes": likes,
        "dislikes": dislikes,
        "blocks": blocks,
        "title": movie_info.get("title", ""),
        "genres": movie_info.get("genres", []),
    }
    save_json("reaction_feedback", _feedback)

    logger.info(
        "Reaction feedback updated",
        title=movie_info.get("title"),
        favorites=favorites, likes=likes,
        dislikes=dislikes, blocks=blocks,
    )


def pause_poll():
    """Pause poll loop during pipeline publish to avoid getUpdates conflict."""
    global _poll_paused
    _poll_paused = True


def resume_poll():
    """Resume poll loop after pipeline publish."""
    global _poll_paused
    _poll_paused = False


def get_poll_offset() -> int:
    return _poll_offset


def advance_offset(new_offset: int):
    global _poll_offset
    _poll_offset = new_offset
    save_json("poll_offset", {"offset": _poll_offset})


async def reaction_poll_loop():
    """Background loop that polls for reactions every 30 seconds."""
    init_feedback()
    logger.info("Reaction poll loop started")
    while True:
        if not _poll_paused:
            await poll_reactions()
        await asyncio.sleep(30)

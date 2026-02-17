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

LIKE_EMOJIS = {"👍", "❤️", "🔥", "🎉", "😍", "⚡", "🏆", "💯"}
DISLIKE_EMOJIS = {"👎", "💩", "😢", "🤮", "😐"}


def init_feedback():
    """Load persisted feedback data."""
    global _published, _feedback, _poll_offset
    _published = load_json("published_messages", {})
    _feedback = load_json("reaction_feedback", {})
    _poll_offset = load_json("poll_offset", {"offset": 0}).get("offset", 0)


def save_published(message_id: int, movie: dict):
    """Save mapping of Telegram message_id to movie data."""
    _published[str(message_id)] = {
        "tmdb_id": movie.get("tmdb_id"),
        "title": movie.get("title_ru", ""),
        "genres": movie.get("genres", []),
        "score": movie.get("score"),
    }
    save_json("published_messages", _published)


def get_feedback() -> dict[str, dict]:
    """Get all feedback data: {tmdb_id: {likes, dislikes, genres, title}}."""
    return _feedback


def get_genre_feedback() -> dict[str, float]:
    """Get genre scores from feedback: {genre: score}.

    Positive score = users like this genre, negative = dislike.
    """
    genre_scores: dict[str, float] = {}
    for tmdb_id, fb in _feedback.items():
        likes = fb.get("likes", 0)
        dislikes = fb.get("dislikes", 0)
        if likes + dislikes == 0:
            continue
        # Score from -1 to +1
        score = (likes - dislikes) / (likes + dislikes)
        for genre in fb.get("genres", []):
            if genre not in genre_scores:
                genre_scores[genre] = 0.0
            genre_scores[genre] += score
    return genre_scores


async def poll_reactions():
    """Poll Telegram for reaction updates on published messages."""
    global _poll_offset

    if not settings.telegram_bot_token:
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    params = {
        "offset": _poll_offset,
        "timeout": 5,
        "allowed_updates": json.dumps(["message_reaction_count"]),
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        if not data.get("ok"):
            logger.warning("Telegram getUpdates failed", response=data)
            return

        for update in data.get("result", []):
            _poll_offset = update["update_id"] + 1
            reaction_count = update.get("message_reaction_count")
            if reaction_count:
                _process_reaction_count(reaction_count)

        # Save offset
        save_json("poll_offset", {"offset": _poll_offset})

    except Exception as e:
        logger.warning("Reaction poll error", error=str(e))


def _process_reaction_count(reaction_data: dict):
    """Process message_reaction_count update."""
    message_id = str(reaction_data.get("message_id", ""))
    reactions = reaction_data.get("reactions", [])

    # Find which movie this message belongs to
    movie_info = _published.get(message_id)
    if not movie_info:
        return

    tmdb_id = str(movie_info.get("tmdb_id", message_id))
    likes = 0
    dislikes = 0

    for r in reactions:
        emoji = r.get("type", {}).get("emoji", "")
        count = r.get("total_count", 0)
        if emoji in LIKE_EMOJIS:
            likes += count
        elif emoji in DISLIKE_EMOJIS:
            dislikes += count

    _feedback[tmdb_id] = {
        "likes": likes,
        "dislikes": dislikes,
        "title": movie_info.get("title", ""),
        "genres": movie_info.get("genres", []),
    }
    save_json("reaction_feedback", _feedback)

    logger.info(
        "Reaction feedback updated",
        title=movie_info.get("title"),
        likes=likes,
        dislikes=dislikes,
    )


async def reaction_poll_loop():
    """Background loop that polls for reactions every 30 seconds."""
    init_feedback()
    logger.info("Reaction poll loop started")
    while True:
        await poll_reactions()
        await asyncio.sleep(30)

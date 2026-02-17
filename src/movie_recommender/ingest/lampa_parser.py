"""Parser for Lampa watch history (CUB sync / backup JSON / TorrServer)."""
import json

import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()


async def fetch_cub_history(token: str) -> list[dict]:
    """Fetch watch history from Lampa CUB cloud sync."""
    # CUB API endpoint for bookmarks/history
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://cub.watch/api/v1/bookmarks",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


async def parse_lampa_backup(file_path: str) -> list[dict]:
    """Parse Lampa backup JSON file."""
    with open(file_path) as f:
        data = json.load(f)

    history = []
    # Lampa backup contains "history" key with watched items
    for item in data.get("history", []):
        history.append({
            "title": item.get("title", ""),
            "year": item.get("year"),
            "type": item.get("type", "movie"),
            "kp_id": item.get("kp_id"),
            "imdb_id": item.get("imdb_id"),
            "tmdb_id": item.get("tmdb_id"),
            "watched_at": item.get("time"),
        })
    return history


async def fetch_torrserver_history() -> list[dict]:
    """Get recently played torrents from TorrServer."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.torrserver_url}/torrents",
            json={"action": "list"},
        )
        resp.raise_for_status()
        torrents = resp.json() or []

    return [
        {
            "title": t.get("title", ""),
            "info_hash": t.get("hash", ""),
            "added_at": t.get("timestamp"),
        }
        for t in torrents
    ]


async def sync_history() -> list[dict]:
    """Sync watch history from all available sources."""
    history: list[dict] = []

    if settings.lampa_cub_token:
        logger.info("Syncing from CUB")
        cub_history = await fetch_cub_history(settings.lampa_cub_token)
        history.extend(cub_history)

    ts_history = await fetch_torrserver_history()
    if ts_history:
        logger.info("Got TorrServer history", count=len(ts_history))
        history.extend(ts_history)

    logger.info("Total history items", count=len(history))
    return history

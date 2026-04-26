"""Lampa sync API -- принимает историю и закладки из Lampa."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import structlog

from movie_recommender.core.storage import load_json, save_json

logger = structlog.get_logger()
router = APIRouter(prefix="/sync", tags=["sync"])

# Load persisted data on import
_history: list[dict] = load_json("sync_history", [])
_bookmarks: dict[str, list] = load_json("sync_bookmarks", {
    "card": [], "like": [], "wath": [], "book": [], "history": [],
    "look": [], "viewed": [], "scheduled": [], "continued": [], "thrown": [],
})


class SyncPayload(BaseModel):
    uid: str = "default"
    type: str = "full"  # full / history / bookmark
    data: dict | list | None = None


class HistoryItem(BaseModel):
    title: str = ""
    year: int | None = None
    type: str = "movie"
    kp_id: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    timestamp: str | None = None    # ISO datetime when item was watched (was: time)
    time_watched: int | None = None  # seconds watched (NEW)
    duration: int | None = None      # total duration in seconds (NEW)


@router.post("/push")
async def push_sync(payload: SyncPayload):
    """Lampa отправляет данные сюда."""
    logger.info(
        "Sync push received",
        uid=payload.uid,
        type=payload.type,
        data_size=len(str(payload.data or "")),
    )

    if payload.type == "full" and isinstance(payload.data, dict):
        for key in _bookmarks:
            if key in payload.data:
                _bookmarks[key] = payload.data[key]
        save_json("sync_bookmarks", _bookmarks)
        logger.info("Full sync saved", keys=list(payload.data.keys()))

    elif payload.type == "history" and isinstance(payload.data, list):
        # Deduplicate by tmdb_id + timestamp
        existing = {(h.get("tmdb_id"), h.get("timestamp")) for h in _history}
        new_items = [
            item for item in payload.data
            if (item.get("tmdb_id"), item.get("timestamp")) not in existing
        ]
        _history.extend(new_items)
        save_json("sync_history", _history)
        logger.info("History items added", count=len(new_items))

    return {"status": "ok", "received": payload.type}


@router.get("/pull")
async def pull_sync(uid: str = "default"):
    """Lampa запрашивает данные отсюда."""
    return {"uid": uid, "bookmarks": _bookmarks, "history_count": len(_history)}


@router.get("/history")
async def get_history():
    """Получить всю историю и реакции из Lampa для pipeline."""
    # Direct history from plugin events
    items = list(_history)

    # Bookmarks - extract tmdb_ids
    bookmark_ids = set()
    for item in _bookmarks.get("history", []):
        if isinstance(item, int):
            bookmark_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            bookmark_ids.add(item["id"])

    # Liked movies - strong positive signal
    liked_ids = set()
    for item in _bookmarks.get("like", []):
        if isinstance(item, int):
            liked_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            liked_ids.add(item["id"])

    # Bookmarked movies - positive signal
    booked_ids = set()
    for item in _bookmarks.get("book", []):
        if isinstance(item, int):
            booked_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            booked_ids.add(item["id"])

    # Want to watch - positive signal
    wath_ids = set()
    for item in _bookmarks.get("wath", []):
        if isinstance(item, int):
            wath_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            wath_ids.add(item["id"])

    # Viewed movies - watched completely
    viewed_ids = set()
    for item in _bookmarks.get("viewed", []):
        if isinstance(item, int):
            viewed_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            viewed_ids.add(item["id"])

    # Thrown/dropped - NEGATIVE signal
    thrown_ids = set()
    for item in _bookmarks.get("thrown", []):
        if isinstance(item, int):
            thrown_ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            thrown_ids.add(item["id"])

    # Card data - full movie info from Lampa
    cards = {}
    for item in _bookmarks.get("card", []):
        if isinstance(item, dict) and item.get("id"):
            cards[item["id"]] = {
                "tmdb_id": item.get("id"),
                "title": item.get("title") or item.get("name", ""),
                "original_title": item.get("original_title") or item.get("original_name", ""),
                "year": _extract_year(item),
                "rating": item.get("vote_average"),
                "poster": item.get("poster_path"),
                "genres": item.get("genre_ids", []),
                "overview": item.get("overview", ""),
                "type": item.get("media_type", "movie"),
            }

    return {
        "items": items,
        "bookmarks": list(bookmark_ids),
        "liked": list(liked_ids),
        "booked": list(booked_ids),
        "wath": list(wath_ids),
        "viewed": list(viewed_ids),
        "thrown": list(thrown_ids),
        "cards": cards,
        "total": len(items) + len(bookmark_ids) + len(liked_ids),
    }


def _extract_year(item: dict) -> int | None:
    """Extract year from Lampa card data."""
    if item.get("year"):
        return item["year"]
    for key in ("release_date", "first_air_date"):
        val = item.get(key, "")
        if val and len(val) >= 4:
            try:
                return int(val[:4])
            except ValueError:
                pass
    return None


@router.post("/backup/import")
async def import_backup(request: Request):
    """Импортировать JSON backup из Lampa."""
    body = await request.json()

    imported = 0
    for key in _bookmarks:
        if key in body:
            items = body[key]
            if isinstance(items, list):
                _bookmarks[key] = items
                imported += len(items)

    save_json("sync_bookmarks", _bookmarks)
    logger.info("Backup imported", items=imported)
    return {"status": "ok", "imported": imported}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "history_count": len(_history),
        "bookmarks": {k: len(v) for k, v in _bookmarks.items()},
    }

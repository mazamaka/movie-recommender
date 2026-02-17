"""Lampa sync API -- принимает историю и закладки из Lampa."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/sync", tags=["sync"])

# In-memory storage (будет заменён на SQLite)
_history: list[dict] = []
_bookmarks: dict[str, list] = {"card": [], "like": [], "wath": [], "book": [], "history": []}


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
    time: str | None = None  # ISO datetime


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
        for key in ["card", "like", "wath", "book", "history"]:
            if key in payload.data:
                _bookmarks[key] = payload.data[key]
        logger.info("Full sync saved", keys=list(payload.data.keys()))

    elif payload.type == "history" and isinstance(payload.data, list):
        _history.extend(payload.data)
        logger.info("History items added", count=len(payload.data))

    return {"status": "ok", "received": payload.type}


@router.get("/pull")
async def pull_sync(uid: str = "default"):
    """Lampa запрашивает данные отсюда."""
    return {"uid": uid, "bookmarks": _bookmarks, "history_count": len(_history)}


@router.get("/history")
async def get_history():
    """Получить всю историю просмотров (для movie-recommender)."""
    return {
        "items": _history,
        "bookmarks": _bookmarks.get("history", []),
        "total": len(_history) + len(_bookmarks.get("history", [])),
    }


@router.post("/backup/import")
async def import_backup(request: Request):
    """Импортировать JSON backup из Lampa."""
    body = await request.json()

    imported = 0
    for key in ["card", "like", "wath", "book", "history"]:
        if key in body:
            items = body[key]
            if isinstance(items, list):
                _bookmarks[key] = items
                imported += len(items)

    logger.info("Backup imported", items=imported)
    return {"status": "ok", "imported": imported}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "history_count": len(_history),
        "bookmarks": {k: len(v) for k, v in _bookmarks.items()},
    }

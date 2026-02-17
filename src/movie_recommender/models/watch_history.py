from datetime import datetime

from sqlmodel import SQLModel, Field


class WatchHistory(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movie.id")
    watched_at: datetime = Field(default_factory=datetime.utcnow)
    watch_duration_pct: float | None = None
    source: str = "lampa"

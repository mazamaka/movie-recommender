from datetime import datetime

from sqlmodel import SQLModel, Field


class Recommendation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movie.id")
    score: float = 0.0
    reason: str = ""
    torrent_id: int | None = Field(default=None, foreign_key="torrentresult.id")
    status: str = "pending"  # pending / published / skipped
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

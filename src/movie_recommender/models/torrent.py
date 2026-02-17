from datetime import datetime

from sqlmodel import SQLModel, Field


class TorrentResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movie.id")
    title: str
    tracker: str
    magnet_link: str
    info_hash: str = ""
    size_gb: float = 0.0
    seeders: int = 0
    leechers: int = 0
    quality: str = ""
    hdr: bool = False
    audio_tracks: str = "[]"  # JSON array
    speed_mbps: float | None = None
    tested_at: datetime | None = None
    found_at: datetime = Field(default_factory=datetime.utcnow)

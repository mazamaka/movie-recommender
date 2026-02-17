from datetime import datetime

from sqlmodel import SQLModel, Field


class Movie(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title_ru: str
    title_en: str | None = None
    year: int
    type: str = "movie"  # movie / series / cartoon
    kp_id: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None
    rating_kp: float | None = None
    rating_imdb: float | None = None
    genres: str = "[]"  # JSON array
    directors: str = "[]"
    actors: str = "[]"
    countries: str = "[]"
    description: str | None = None
    poster_url: str | None = None
    runtime_min: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

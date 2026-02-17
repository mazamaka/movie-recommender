from datetime import datetime

from sqlmodel import SQLModel, Field


class UserProfile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    genre_weights: str = "{}"  # JSON
    actor_weights: str = "{}"
    director_weights: str = "{}"
    avg_rating_kp: float | None = None
    preferred_years: str = "[]"
    updated_at: datetime = Field(default_factory=datetime.utcnow)

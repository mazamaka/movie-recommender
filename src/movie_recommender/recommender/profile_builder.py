"""Build user preference profile from watch history."""
import json
from collections import Counter

import structlog

logger = structlog.get_logger()


def build_profile(movies: list[dict]) -> dict:
    """Build preference profile from watched movies."""
    genre_counter: Counter[str] = Counter()
    actor_counter: Counter[str] = Counter()
    director_counter: Counter[str] = Counter()
    years: list[int] = []
    ratings: list[float] = []

    for m in movies:
        genres = json.loads(m.get("genres", "[]")) if isinstance(m.get("genres"), str) else m.get("genres", [])
        actors = json.loads(m.get("actors", "[]")) if isinstance(m.get("actors"), str) else m.get("actors", [])
        directors = (
            json.loads(m.get("directors", "[]")) if isinstance(m.get("directors"), str) else m.get("directors", [])
        )

        genre_counter.update(genres)
        actor_counter.update(actors[:5])
        director_counter.update(directors)

        if m.get("year"):
            years.append(m["year"])
        if m.get("rating_kp"):
            ratings.append(m["rating_kp"])

    total_genres = sum(genre_counter.values()) or 1
    total_actors = sum(actor_counter.values()) or 1
    total_directors = sum(director_counter.values()) or 1

    return {
        "genre_weights": {g: c / total_genres for g, c in genre_counter.most_common(20)},
        "actor_weights": {a: c / total_actors for a, c in actor_counter.most_common(30)},
        "director_weights": {d: c / total_directors for d, c in director_counter.most_common(15)},
        "avg_rating_kp": sum(ratings) / len(ratings) if ratings else None,
        "preferred_years": [min(years), max(years)] if years else [],
    }

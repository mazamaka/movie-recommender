"""Content-based movie recommender using TF-IDF + cosine similarity."""
import json

import structlog

logger = structlog.get_logger()


def score_movie(movie: dict, profile: dict) -> float:
    """Score a candidate movie against user profile. Returns 0.0-1.0."""
    genre_sim = _genre_similarity(movie, profile)
    actor_bonus = _actor_bonus(movie, profile)
    director_bonus = _director_bonus(movie, profile)
    rating_score = _rating_score(movie)
    freshness = _freshness_score(movie)

    score = (
        0.35 * genre_sim
        + 0.15 * actor_bonus
        + 0.10 * director_bonus
        + 0.25 * rating_score
        + 0.15 * freshness
    )
    return min(max(score, 0.0), 1.0)


def _genre_similarity(movie: dict, profile: dict) -> float:
    genres = json.loads(movie.get("genres", "[]")) if isinstance(movie.get("genres"), str) else movie.get("genres", [])
    weights = profile.get("genre_weights", {})
    if not genres or not weights:
        return 0.0
    return sum(weights.get(g, 0.0) for g in genres) / max(len(genres), 1)


def _actor_bonus(movie: dict, profile: dict) -> float:
    actors = json.loads(movie.get("actors", "[]")) if isinstance(movie.get("actors"), str) else movie.get("actors", [])
    weights = profile.get("actor_weights", {})
    if not actors or not weights:
        return 0.0
    return sum(weights.get(a, 0.0) for a in actors[:5]) / 5


def _director_bonus(movie: dict, profile: dict) -> float:
    directors = (
        json.loads(movie.get("directors", "[]"))
        if isinstance(movie.get("directors"), str)
        else movie.get("directors", [])
    )
    weights = profile.get("director_weights", {})
    if not directors or not weights:
        return 0.0
    return sum(weights.get(d, 0.0) for d in directors)


def _rating_score(movie: dict) -> float:
    kp = movie.get("rating_kp") or 0
    imdb = movie.get("rating_imdb") or 0
    rating = max(kp, imdb)
    return min(rating / 10.0, 1.0)


def _freshness_score(movie: dict) -> float:
    year = movie.get("year") or 2020
    if year >= 2026:
        return 1.0
    if year >= 2024:
        return 0.8
    if year >= 2022:
        return 0.6
    if year >= 2020:
        return 0.4
    return 0.2

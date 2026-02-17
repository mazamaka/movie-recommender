"""TMDB API client for movie metadata."""
import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()

TMDB_BASE = "https://api.themoviedb.org/3"

_genre_cache: dict[str, int] = {}


async def search_movie(title: str, year: int | None = None) -> list[dict]:
    """Search for a movie on TMDB."""
    params: dict[str, str] = {"api_key": settings.tmdb_api_key, "query": title, "language": "ru-RU"}
    if year:
        params["year"] = str(year)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{TMDB_BASE}/search/movie", params=params)
        resp.raise_for_status()
        return resp.json().get("results", [])


async def search_tv(title: str, year: int | None = None) -> list[dict]:
    """Search for a TV show on TMDB."""
    params: dict[str, str] = {"api_key": settings.tmdb_api_key, "query": title, "language": "ru-RU"}
    if year:
        params["first_air_date_year"] = str(year)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{TMDB_BASE}/search/tv", params=params)
        resp.raise_for_status()
        return resp.json().get("results", [])


async def get_movie_details(tmdb_id: int) -> dict:
    """Get full movie details from TMDB."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{TMDB_BASE}/movie/{tmdb_id}",
            params={
                "api_key": settings.tmdb_api_key,
                "language": "ru-RU",
                "append_to_response": "credits,videos",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_trending(media_type: str = "movie", time_window: str = "week") -> list[dict]:
    """Get trending movies/tv from TMDB."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{TMDB_BASE}/trending/{media_type}/{time_window}",
            params={"api_key": settings.tmdb_api_key, "language": "ru-RU"},
        )
        resp.raise_for_status()
        return resp.json().get("results", [])


async def _get_genre_map() -> dict[str, int]:
    """Get genre name -> TMDB genre ID mapping (cached)."""
    global _genre_cache
    if _genre_cache:
        return _genre_cache

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{TMDB_BASE}/genre/movie/list",
            params={"api_key": settings.tmdb_api_key, "language": "ru-RU"},
        )
        resp.raise_for_status()
        _genre_cache = {g["name"]: g["id"] for g in resp.json().get("genres", [])}
    return _genre_cache


async def discover_movies(genre_names: list[str], min_year: int = 2024) -> list[dict]:
    """Discover movies by genres using TMDB discover API."""
    genre_map = await _get_genre_map()
    genre_ids = [str(genre_map[g]) for g in genre_names if g in genre_map]
    if not genre_ids:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{TMDB_BASE}/discover/movie",
            params={
                "api_key": settings.tmdb_api_key,
                "language": "ru-RU",
                "sort_by": "vote_average.desc",
                "vote_count.gte": "100",
                "with_genres": ",".join(genre_ids),
                "primary_release_date.gte": f"{min_year}-01-01",
            },
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

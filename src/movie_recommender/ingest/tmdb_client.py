"""TMDB API client for movie metadata."""
import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()

TMDB_BASE = "https://api.themoviedb.org/3"


async def search_movie(title: str, year: int | None = None) -> list[dict]:
    """Search for a movie on TMDB."""
    params: dict[str, str] = {"api_key": settings.tmdb_api_key, "query": title, "language": "ru-RU"}
    if year:
        params["year"] = str(year)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{TMDB_BASE}/search/movie", params=params)
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

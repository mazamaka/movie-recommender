"""YouTube trailer finder."""
import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()


async def find_trailer(title: str, year: int | None = None) -> str | None:
    """Find Russian trailer on YouTube."""
    query = f"{title} {year or ''} \u0442\u0440\u0435\u0439\u043b\u0435\u0440 \u0440\u0443\u0441\u0441\u043a\u0438\u0439 \u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439".strip()

    if not settings.youtube_api_key:
        # Fallback: return YouTube search URL
        return f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": settings.youtube_api_key,
                "q": query,
                "part": "snippet",
                "type": "video",
                "maxResults": 1,
            },
        )
        if resp.status_code != 200:
            logger.warning("YouTube search failed", status=resp.status_code)
            return None

        items = resp.json().get("items", [])
        if items:
            video_id = items[0]["id"]["videoId"]
            return f"https://www.youtube.com/watch?v={video_id}"

    return None

"""Lampa CUB community reactions client."""
import asyncio

import httpx
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()


async def fetch_cub_reactions(tmdb_ids: list[int]) -> dict[int, dict]:
    """Fetch Lampa CUB community reactions for multiple movies concurrently.

    Tries the primary CUB API URL first, then falls back to mirrors.
    Returns {tmdb_id: {"fire": N, "shit": N, "nice": N, "think": N, "bore": N}}
    for each movie. Returns empty dict for movies where fetch failed.
    """
    results: dict[int, dict] = {}

    async def _fetch_one(client: httpx.AsyncClient, tmdb_id: int) -> None:
        urls = [settings.cub_api_url] + settings.cub_mirrors
        for base_url in urls:
            try:
                resp = await client.get(f"{base_url}/movie_{tmdb_id}", timeout=5)
                data = resp.json()
                if data.get("secuses") or data.get("result"):
                    results[tmdb_id] = {
                        r["type"]: r["counter"] for r in data.get("result", [])
                    }
                    return
            except httpx.TimeoutException:
                logger.debug("CUB timeout", tmdb_id=tmdb_id, url=base_url)
                continue
            except httpx.HTTPError:
                logger.debug("CUB http error", tmdb_id=tmdb_id, url=base_url)
                continue
            except (KeyError, ValueError) as exc:
                logger.debug("CUB parse error", tmdb_id=tmdb_id, error=str(exc))
                continue
        results[tmdb_id] = {}

    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one(client, tid) for tid in tmdb_ids]
        await asyncio.gather(*tasks)

    return results

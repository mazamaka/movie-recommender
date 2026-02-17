"""Jackett torrent search API client."""
import re

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.search.base import BaseTorrentSearcher, SearchResult

logger = structlog.get_logger()


class JackettSearcher(BaseTorrentSearcher):
    def __init__(self) -> None:
        self.base_url = settings.jackett_url
        self.api_key = settings.jackett_api_key

    async def search(self, query: str, year: int | None = None) -> list[SearchResult]:
        search_query = f"{query} {year}" if year else query
        params: dict[str, str | list[int]] = {
            "apikey": self.api_key,
            "Query": search_query,
            "Category[]": [2000],  # Movies
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v2.0/indexers/all/results",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("Results", []):
            quality = self._parse_quality(item.get("Title", ""))
            results.append(SearchResult(
                title=item.get("Title", ""),
                magnet_link=item.get("MagnetUri", "") or item.get("Link", ""),
                size_gb=round(item.get("Size", 0) / (1024 ** 3), 2),
                seeders=item.get("Seeders", 0),
                leechers=item.get("Peers", 0) - item.get("Seeders", 0),
                quality=quality,
                tracker=item.get("Tracker", "jackett"),
            ))
        return sorted(results, key=lambda r: r.seeders, reverse=True)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v2.0/server/config",
                    params={"apikey": self.api_key},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _parse_quality(title: str) -> str:
        title_lower = title.lower()
        if "2160p" in title_lower or "4k" in title_lower:
            return "2160p"
        if "1080p" in title_lower:
            return "1080p"
        if "720p" in title_lower:
            return "720p"
        return "unknown"

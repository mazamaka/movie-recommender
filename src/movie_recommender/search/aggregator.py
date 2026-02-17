"""Aggregator for multiple torrent search sources."""
import asyncio

import structlog

from movie_recommender.search.base import SearchResult
from movie_recommender.search.jackett import JackettSearcher

logger = structlog.get_logger()


class TorrentAggregator:
    def __init__(self, searchers: list | None = None) -> None:
        self.searchers = searchers or [JackettSearcher()]

    async def search_all(self, query: str, year: int | None = None) -> list[SearchResult]:
        """Search all sources in parallel and aggregate results."""
        tasks = [s.search(query, year) for s in self.searchers]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[SearchResult] = []
        for i, results in enumerate(results_lists):
            if isinstance(results, Exception):
                logger.error("Search failed", searcher=type(self.searchers[i]).__name__, error=str(results))
                continue
            all_results.extend(results)

        # Deduplicate by info_hash
        seen: set[str] = set()
        unique: list[SearchResult] = []
        for r in all_results:
            key = r.info_hash or r.magnet_link
            if key and key not in seen:
                seen.add(key)
                unique.append(r)

        return sorted(unique, key=lambda r: r.seeders, reverse=True)

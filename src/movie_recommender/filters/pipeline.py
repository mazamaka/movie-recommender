"""Filter pipeline for torrent results."""
import re
from abc import ABC, abstractmethod

import structlog

from movie_recommender.core.config import settings
from movie_recommender.search.base import SearchResult

logger = structlog.get_logger()


class BaseFilter(ABC):
    @abstractmethod
    def apply(self, results: list[SearchResult]) -> list[SearchResult]:
        ...


class SeedersFilter(BaseFilter):
    def apply(self, results: list[SearchResult]) -> list[SearchResult]:
        filtered = [r for r in results if r.seeders >= settings.min_seeders]
        logger.debug("SeedersFilter", before=len(results), after=len(filtered))
        return filtered


class QualityFilter(BaseFilter):
    QUALITY_ORDER: dict[str, int] = {"2160p": 4, "1080p": 3, "720p": 2, "unknown": 1}

    def apply(self, results: list[SearchResult]) -> list[SearchResult]:
        min_level = self.QUALITY_ORDER.get(settings.quality_filter, 1)
        filtered = [r for r in results if self.QUALITY_ORDER.get(r.quality, 0) >= min_level]
        logger.debug("QualityFilter", before=len(results), after=len(filtered))
        return filtered


class LanguageFilter(BaseFilter):
    RU_PATTERNS = re.compile(
        r"(\u0434\u0443\u0431\u043b\u044f\u0436|\u0434\u0443\u0431\u043b\u0438\u0440\u043e\u0432\u0430\u043d|\u043b\u0438\u0446\u0435\u043d\u0437\u0438|iTunes|D\b|DD5|Dub|\u0434\u0443\u0431\u043b|\u043e\u0437\u0432\u0443\u0447|\u043c\u043d\u043e\u0433\u043e\u0433\u043e\u043b\u043e\u0441|MVO|\u0414\u0411|\u041f\u0440\u043e\u0444\u0435\u0441\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d)",
        re.IGNORECASE,
    )

    def apply(self, results: list[SearchResult]) -> list[SearchResult]:
        if settings.language_filter == "any":
            return results
        filtered = [r for r in results if self.RU_PATTERNS.search(r.title)]
        logger.debug("LanguageFilter", before=len(results), after=len(filtered))
        return filtered


class FilterPipeline:
    def __init__(self, filters: list[BaseFilter] | None = None) -> None:
        self.filters = filters or [SeedersFilter(), QualityFilter(), LanguageFilter()]

    def execute(self, results: list[SearchResult]) -> list[SearchResult]:
        for f in self.filters:
            results = f.apply(results)
            if not results:
                logger.warning("Pipeline empty after filter", filter=type(f).__name__)
                break
        return results

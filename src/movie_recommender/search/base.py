"""Base class for torrent searchers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    title: str
    magnet_link: str
    info_hash: str = ""
    size_gb: float = 0.0
    seeders: int = 0
    leechers: int = 0
    quality: str = ""
    audio: list[str] = field(default_factory=list)
    tracker: str = ""


class BaseTorrentSearcher(ABC):
    @abstractmethod
    async def search(self, query: str, year: int | None = None) -> list[SearchResult]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

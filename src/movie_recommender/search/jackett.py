"""Jackett torrent search API client."""
import re

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.search.base import SearchResult

logger = structlog.get_logger()


class JackettSearcher:
    def __init__(self) -> None:
        self.base_url = settings.jackett_url
        self.api_key = settings.jackett_api_key

    async def search(self, query: str, year: int | None = None) -> list[SearchResult]:
        search_query = f"{query} {year}" if year else query
        params = {
            "apikey": self.api_key,
            "Query": search_query,
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Get session cookie first (Jackett requires this)
            await client.get(f"{self.base_url}/UI/Dashboard")

            resp = await client.get(
                f"{self.base_url}/api/v2.0/indexers/all/results",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("Results", []):
            quality = self._parse_quality(item.get("Title", ""))
            magnet = item.get("MagnetUri") or item.get("Link") or ""
            seeders = item.get("Seeders", 0) or 0
            peers = item.get("Peers", 0) or 0
            results.append(SearchResult(
                title=item.get("Title", ""),
                magnet_link=magnet,
                info_hash=self._extract_hash(magnet),
                size_gb=round(item.get("Size", 0) / (1024 ** 3), 2),
                seeders=seeders,
                leechers=max(peers - seeders, 0),
                quality=quality,
                audio=self._parse_audio(item.get("Title", "")),
                tracker=item.get("Tracker", "jackett"),
            ))
        return sorted(results, key=lambda r: r.seeders, reverse=True)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                await client.get(f"{self.base_url}/UI/Dashboard")
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
        if "2160p" in title_lower or "4k" in title_lower or "uhd" in title_lower:
            return "2160p"
        if "1080p" in title_lower or "1080i" in title_lower:
            return "1080p"
        if "720p" in title_lower:
            return "720p"
        if "web-dl" in title_lower or "webdl" in title_lower:
            return "1080p"
        if "bdrip" in title_lower or "blu-ray" in title_lower:
            return "1080p"
        return "unknown"

    @staticmethod
    def _parse_audio(title: str) -> list[str]:
        """Extract audio/dubbing tracks from torrent title."""
        audio: list[str] = []
        t = title

        # Studios and specific dubs
        studios = [
            "LostFilm", "NewStudio", "HDrezka", "HDRezka Studio", "Кубик в Кубе",
            "Jaskier", "Pazl Voice", "New-Team", "ColdFilm", "IdeaFilm",
            "Kerob", "Profix Media", "TVShows", "Hamster Studio", "AMS",
            "AlexFilm", "BaibaKo", "FOX", "SDI Media", "Невафильм",
        ]
        for s in studios:
            if s.lower() in t.lower():
                audio.append(s)

        # Dubbing types
        patterns: dict[str, str] = {
            r'(?i)\bдублир\w*': 'Дубляж',
            r'(?i)\bдубляж\b': 'Дубляж',
            r'(?i)\bлицензи\w*': 'Лицензия',
            r'(?i)\biTunes\b': 'iTunes',
            r'(?i)\bNetflix\b': 'Netflix',
            r'(?i)\bАвторск\w*': 'Авторский',
            r'(?i)\bAVO\b': 'AVO',
            r'(?i)\bMVO\b': 'Профессиональный (многоголосый)',
            r'(?i)\b[Пп]роф\w*\s*многогол\w*': 'Профессиональный (многоголосый)',
            r'(?i)\bмногогол\w*': 'Многоголосый',
            r'(?i)\bOriginal\b': 'Оригинал',
            r'(?i)\bENG\b': 'ENG',
            r'(?i)\bUKR\b': 'Украинский',
            r'(?i)\b[Лл]юбител\w*': 'Любительский',
            r'(?i)\bDD5\.?1\b': 'DD5.1',
            r'(?i)\bDTS\b': 'DTS',
            r'(?i)\bAtmos\b': 'Atmos',
        }

        for pattern, label in patterns.items():
            if re.search(pattern, t) and label not in audio:
                audio.append(label)

        return audio if audio else ['Неизвестно']

    @staticmethod
    def _extract_hash(magnet: str) -> str:
        if not magnet:
            return ""
        match = re.search(r"btih:([a-fA-F0-9]{40})", magnet)
        return match.group(1).lower() if match else ""

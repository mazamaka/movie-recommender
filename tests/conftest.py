"""Shared pytest fixtures for the test suite."""
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def sample_feedback() -> dict[str, dict]:
    """Realistic reaction_feedback.json content with mix of reactions."""
    return {
        "693134": {  # Dune Part Two
            "favorites": 2, "likes": 1, "dislikes": 0, "blocks": 0,
            "title": "Дюна: Часть вторая",
            "genres": ["фантастика", "приключения", "драма"],
        },
        "872585": {  # Oppenheimer
            "favorites": 1, "likes": 0, "dislikes": 0, "blocks": 0,
            "title": "Оппенгеймер",
            "genres": ["драма", "история"],
        },
        "346698": {  # Barbie
            "favorites": 0, "likes": 0, "dislikes": 2, "blocks": 0,
            "title": "Барби",
            "genres": ["комедия", "фэнтези"],
        },
        "1226578": {  # placeholder blocked movie
            "favorites": 0, "likes": 0, "dislikes": 0, "blocks": 2,
            "title": "Скучный фильм",
            "genres": ["драма"],
        },
    }


@pytest.fixture
def sample_finished_movies() -> list[dict]:
    """Movies with watch ratio > 0.80, enriched with TMDB metadata."""
    return [
        {
            "tmdb_id": 693134,
            "title_ru": "Дюна: Часть вторая",
            "title_en": "Dune: Part Two",
            "year": 2024,
            "genres": ["фантастика", "приключения", "драма"],
            "directors": ["Дени Вильнёв"],
            "actors": ["Тимоти Шаламе", "Зендея"],
            "rating_imdb": 8.5,
            "vote_count": 500000,
            "description": "Пол Атрейдес объединяется с Чани и фрименами...",
        },
    ]


@pytest.fixture
def sample_dropped_movies() -> list[dict]:
    """Movies with watch ratio in [0.10, 0.50]."""
    return [
        {
            "tmdb_id": 346698,
            "title_ru": "Барби",
            "title_en": "Barbie",
            "year": 2023,
            "genres": ["комедия", "фэнтези"],
            "directors": ["Грета Гервиг"],
            "actors": ["Марго Робби"],
            "rating_imdb": 6.8,
            "vote_count": 600000,
            "description": "Барби и Кен отправляются в реальный мир...",
        },
    ]


@pytest.fixture
def sample_candidates() -> list[dict]:
    """30 candidate movies with score, sorted desc — output of score_movie."""
    candidates = []
    for i in range(30):
        candidates.append({
            "tmdb_id": 1000000 + i,
            "title_ru": f"Кандидат {i+1}",
            "title_en": f"Candidate {i+1}",
            "year": 2024,
            "genres": ["драма"] if i % 2 == 0 else ["боевик", "триллер"],
            "directors": [f"Режиссёр {i+1}"],
            "actors": [f"Актёр {i+1}"],
            "rating_imdb": 7.0 + (i % 3) * 0.3,
            "vote_count": 10000 + i * 1000,
            "description": f"Описание кандидата {i+1}.",
            "score": round(0.9 - i * 0.01, 2),
            "release_date": "2024-06-01",
            "popularity": 50.0,
            "poster_url": f"https://image.tmdb.org/t/p/w500/{i}.jpg",
            "runtime_min": 120,
            "trailer_url": None,
            "countries": ["США"],
        })
    return candidates


@pytest.fixture
def mock_anthropic_response() -> MagicMock:
    """Mock Anthropic API response with valid JSON containing 10 picks."""
    picks = []
    for i in range(10):
        picks.append({
            "rank": i + 1,
            "tmdb_id": 1000000 + i,  # matches sample_candidates first 10
            "reason": f"Обоснование выбора {i+1}: подходит под твой вкус.",
        })
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    response.usage = MagicMock(input_tokens=2150, output_tokens=850)
    return response


@pytest.fixture
def mock_anthropic_client(mock_anthropic_response: MagicMock) -> MagicMock:
    """Mock AsyncAnthropic client whose messages.create returns mock_anthropic_response."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=mock_anthropic_response)
    return client

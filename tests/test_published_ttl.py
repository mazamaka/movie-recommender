"""Tests for published TTL filtering in feedback.get_published_tmdb_ids."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_published_state():
    """Reset _published dict between tests to avoid cross-test contamination."""
    from movie_recommender.publishers import feedback
    feedback._published.clear()
    yield
    feedback._published.clear()


def test_recent_published_in_dedup_set():
    """Published within TTL window appear in dedup set."""
    from movie_recommender.publishers import feedback

    now = datetime.utcnow()
    feedback._published["1"] = {"tmdb_id": 100, "published_at": now.isoformat()}
    feedback._published["2"] = {"tmdb_id": 200, "published_at": (now - timedelta(days=10)).isoformat()}

    with patch.object(feedback.settings, "published_ttl_days", 60):
        ids = feedback.get_published_tmdb_ids()

    assert ids == {100, 200}


def test_expired_published_excluded():
    """Published older than TTL are excluded (may be re-recommended)."""
    from movie_recommender.publishers import feedback

    now = datetime.utcnow()
    feedback._published["1"] = {"tmdb_id": 100, "published_at": (now - timedelta(days=70)).isoformat()}
    feedback._published["2"] = {"tmdb_id": 200, "published_at": (now - timedelta(days=5)).isoformat()}

    with patch.object(feedback.settings, "published_ttl_days", 60):
        ids = feedback.get_published_tmdb_ids()

    assert ids == {200}


def test_legacy_no_timestamp_excluded():
    """Legacy entries without published_at are treated as expired (may be re-recommended)."""
    from movie_recommender.publishers import feedback

    feedback._published["1"] = {"tmdb_id": 100}  # no published_at
    feedback._published["2"] = {"tmdb_id": 200, "published_at": datetime.utcnow().isoformat()}

    with patch.object(feedback.settings, "published_ttl_days", 60):
        ids = feedback.get_published_tmdb_ids()

    assert ids == {200}


def test_save_published_stamps_timestamp():
    """save_published adds published_at field automatically."""
    from movie_recommender.publishers import feedback

    movie = {
        "tmdb_id": 999,
        "title_ru": "Test Movie",
        "title_en": "Test Movie",
        "genres": ["драма"],
        "year": 2024,
    }

    with patch.object(feedback, "save_json"):  # don't write to disk
        feedback.save_published(42, movie)

    saved = feedback._published["42"]
    assert "published_at" in saved
    # Should be a valid ISO timestamp parseable as datetime
    parsed = datetime.fromisoformat(saved["published_at"])
    assert (datetime.utcnow() - parsed).total_seconds() < 5  # within 5 seconds

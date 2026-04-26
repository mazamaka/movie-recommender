"""Tests for new TMDB API functions: get_popular, get_top_rated, get_now_playing."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_popular_calls_correct_endpoint():
    from movie_recommender.ingest import tmdb_client

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value={"results": [{"id": 1}, {"id": 2}]})
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await tmdb_client.get_popular()

    assert results == [{"id": 1}, {"id": 2}]
    args, kwargs = mock_client.get.call_args
    assert args[0].endswith("/movie/popular")
    assert kwargs["params"]["page"] == "1"


@pytest.mark.asyncio
async def test_get_top_rated_calls_correct_endpoint():
    from movie_recommender.ingest import tmdb_client

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value={"results": [{"id": 100}]})
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await tmdb_client.get_top_rated()

    assert results == [{"id": 100}]
    args, _ = mock_client.get.call_args
    assert args[0].endswith("/movie/top_rated")


@pytest.mark.asyncio
async def test_get_now_playing_calls_correct_endpoint():
    from movie_recommender.ingest import tmdb_client

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value={"results": []})
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await tmdb_client.get_now_playing()

    assert results == []
    args, _ = mock_client.get.call_args
    assert args[0].endswith("/movie/now_playing")

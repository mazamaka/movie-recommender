"""Unit tests for LLM-based reranker."""
import json
import httpx
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_happy_path_returns_top_n_with_reasons(
    sample_candidates,
    sample_feedback,
    sample_finished_movies,
    sample_dropped_movies,
    mock_anthropic_client,
):
    """When LLM returns valid JSON with 10 picks, all 10 returned with reason and rank."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker, "_get_anthropic_client", return_value=mock_anthropic_client), \
         patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True):
        result = await llm_reranker.rerank_candidates(
            candidates=sample_candidates,
            feedback=sample_feedback,
            finished_movies=sample_finished_movies,
            dropped_movies=sample_dropped_movies,
            top_n=10,
        )

    assert len(result) == 10
    for i, movie in enumerate(result):
        assert movie["llm_rank"] == i + 1
        assert movie["llm_reason"].startswith("Обоснование выбора")
        assert movie["tmdb_id"] == 1000000 + i  # Order matches LLM picks


@pytest.mark.asyncio
async def test_no_api_key_returns_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """No API key → fallback to shortlist[:10] without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", ""), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_returns_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM_RERANK_ENABLED=False → fallback without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", False), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_empty_feedback_and_no_finished_returns_shortlist(sample_candidates):
    """Empty feedback AND empty finished → fallback without LLM call."""
    from movie_recommender.recommender import llm_reranker

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            sample_candidates, feedback={}, finished_movies=[], dropped_movies=[], top_n=10,
        )

    assert len(result) == 10
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_short_candidates_returns_as_is(
    sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """len(candidates) <= top_n → return as is, no LLM call."""
    from movie_recommender.recommender import llm_reranker

    short = [{"tmdb_id": i, "title_ru": f"M{i}", "year": 2024, "genres": []} for i in range(5)]
    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client") as mock_client:
        result = await llm_reranker.rerank_candidates(
            short, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 5
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """httpx.TimeoutException from LLM → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)


@pytest.mark.asyncio
async def test_api_error_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """Anthropic API 5xx error → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=RuntimeError("APIStatusError 500"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10


@pytest.mark.asyncio
async def test_invalid_json_falls_back(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns non-JSON → fallback to shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="это вообще не json, какой-то текст")]
    bad_response.usage = MagicMock(input_tokens=100, output_tokens=20)
    bad_client = MagicMock()
    bad_client.messages = MagicMock()
    bad_client.messages.create = AsyncMock(return_value=bad_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=bad_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)


@pytest.mark.asyncio
async def test_partial_picks_filled_from_shortlist(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns 6 picks → 6 with reason + 4 filled from shortlist without reason."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    picks = [
        {"rank": i + 1, "tmdb_id": 1000000 + i, "reason": f"Reason {i+1}"}
        for i in range(6)
    ]
    partial_response = MagicMock()
    partial_response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    partial_response.usage = MagicMock(input_tokens=2000, output_tokens=500)
    partial_client = MagicMock()
    partial_client.messages = MagicMock()
    partial_client.messages.create = AsyncMock(return_value=partial_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=partial_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    # First 6 from LLM with reason
    for i in range(6):
        assert result[i]["llm_reason"] == f"Reason {i+1}"
        assert result[i]["llm_rank"] == i + 1
    # Last 4 from shortlist without reason (next candidates after the 6 used)
    for i in range(6, 10):
        assert "llm_reason" not in result[i]
        assert "llm_rank" not in result[i]
    # No duplicate tmdb_ids
    ids = [m["tmdb_id"] for m in result]
    assert len(set(ids)) == 10


@pytest.mark.asyncio
async def test_unknown_tmdb_id_skipped(
    sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies,
):
    """LLM returns pick with tmdb_id not in candidates → that pick skipped, filled from shortlist."""
    from unittest.mock import AsyncMock, MagicMock
    from movie_recommender.recommender import llm_reranker

    picks = [
        {"rank": 1, "tmdb_id": 99999999, "reason": "Wrong id"},  # not in candidates
        {"rank": 2, "tmdb_id": 1000001, "reason": "Real pick"},
    ]
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text=json.dumps({"picks": picks}, ensure_ascii=False))]
    bad_response.usage = MagicMock(input_tokens=2000, output_tokens=500)
    bad_client = MagicMock()
    bad_client.messages = MagicMock()
    bad_client.messages.create = AsyncMock(return_value=bad_response)

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=bad_client):
        result = await llm_reranker.rerank_candidates(
            sample_candidates, sample_feedback, sample_finished_movies, sample_dropped_movies, top_n=10,
        )

    assert len(result) == 10
    # Only the real pick (1000001) gets LLM reason, others filled from shortlist
    real_picks = [m for m in result if m.get("llm_reason") == "Real pick"]
    assert len(real_picks) == 1
    assert real_picks[0]["tmdb_id"] == 1000001
    # No duplicates
    ids = [m["tmdb_id"] for m in result]
    assert len(set(ids)) == 10

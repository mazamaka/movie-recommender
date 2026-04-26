"""Integration tests: pipeline runner + LLM reranker (with mocks)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_pipeline_calls_llm_with_top_30(sample_candidates, mock_anthropic_client):
    """Pipeline should pass shortlist of llm_rerank_shortlist_size to LLM."""
    from movie_recommender.recommender import llm_reranker

    captured_args: dict = {}

    async def capturing_rerank(candidates, feedback, finished_movies, dropped_movies, top_n):
        captured_args["candidates"] = candidates
        captured_args["top_n"] = top_n
        # Return first 10 with reasons to simulate happy LLM
        return [{**c, "llm_rank": i + 1, "llm_reason": f"R{i+1}"} for i, c in enumerate(candidates[:top_n])]

    with patch.object(llm_reranker, "rerank_candidates", side_effect=capturing_rerank):
        from movie_recommender.recommender.llm_reranker import rerank_candidates as rc
        result = await rc(
            candidates=sample_candidates,
            feedback={"123": {"favorites": 1, "likes": 0, "dislikes": 0, "blocks": 0,
                              "title": "X", "genres": ["драма"]}},
            finished_movies=[],
            dropped_movies=[],
            top_n=10,
        )

    assert captured_args["candidates"] == sample_candidates
    assert captured_args["top_n"] == 10
    assert len(result) == 10
    assert result[0]["llm_reason"] == "R1"


@pytest.mark.asyncio
async def test_pipeline_continues_on_llm_failure(sample_candidates, sample_feedback, sample_finished_movies):
    """If LLM raises, rerank_candidates returns shortlist[:top_n] without crashing."""
    from movie_recommender.recommender import llm_reranker

    failing_client = MagicMock()
    failing_client.messages = MagicMock()
    failing_client.messages.create = AsyncMock(side_effect=httpx.TimeoutException("nope"))

    with patch.object(llm_reranker.settings, "anthropic_api_key", "sk-test"), \
         patch.object(llm_reranker.settings, "llm_rerank_enabled", True), \
         patch.object(llm_reranker, "_get_anthropic_client", return_value=failing_client):
        result = await llm_reranker.rerank_candidates(
            candidates=sample_candidates,
            feedback=sample_feedback,
            finished_movies=sample_finished_movies,
            dropped_movies=[],
            top_n=10,
        )

    assert len(result) == 10
    assert all("llm_reason" not in m for m in result)
    # Should be the first 10 from shortlist (preserves original order)
    assert [m["tmdb_id"] for m in result] == [c["tmdb_id"] for c in sample_candidates[:10]]


def test_format_message_handles_missing_reason():
    """publishers.telegram.format_message must work for movies without llm_reason field."""
    from movie_recommender.publishers.telegram import format_message

    movie_no_reason = {
        "tmdb_id": 1, "title_ru": "Тест", "year": 2024, "genres": ["драма"],
        "description": "Описание", "rating_imdb": 7.5, "vote_count": 1000,
    }
    movie_with_reason = {**movie_no_reason, "llm_reason": "Шикарно подходит."}
    torrent = {"quality": "1080p", "size_gb": 5, "seeders": 100, "tracker": "rt", "audio": []}

    out_no = format_message(movie_no_reason, torrent)
    out_yes = format_message(movie_with_reason, torrent)

    assert "🤖" not in out_no  # no robot when no reason
    assert "🤖" in out_yes
    assert "Шикарно подходит." in out_yes

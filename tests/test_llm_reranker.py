"""Unit tests for LLM-based reranker."""
import json
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

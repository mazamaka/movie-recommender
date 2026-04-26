"""LLM-based reranker — uses Claude to refine top-N candidates using reaction history."""
from movie_recommender.core.config import settings


def _get_anthropic_client():
    """Lazily construct AsyncAnthropic client. Patched in tests."""
    raise NotImplementedError


async def rerank_candidates(
    candidates: list[dict],
    feedback: dict[str, dict],
    finished_movies: list[dict],
    dropped_movies: list[dict],
    top_n: int = 10,
) -> list[dict]:
    """Stub — to be implemented in Task 5."""
    raise NotImplementedError

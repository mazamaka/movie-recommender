"""Pipeline API -- запуск и управление рекомендательным пайплайном."""

from fastapi import APIRouter, BackgroundTasks
import structlog

from movie_recommender.core.config import settings

logger = structlog.get_logger()
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_pipeline_status = {"running": False, "last_run": None, "last_result": None}


@router.post("/run")
async def run_pipeline_endpoint(background_tasks: BackgroundTasks, top_n: int = 5):
    """Запустить пайплайн рекомендаций."""
    if _pipeline_status["running"]:
        return {"status": "already_running"}

    background_tasks.add_task(_run_pipeline_task, top_n)
    return {"status": "started", "top_n": top_n}


@router.get("/status")
async def pipeline_status():
    """Статус последнего запуска пайплайна."""
    return _pipeline_status


@router.get("/feedback")
async def get_feedback():
    """Получить обратную связь по реакциям из Telegram."""
    from movie_recommender.publishers.feedback import get_feedback, get_genre_feedback

    return {
        "movies": get_feedback(),
        "genre_scores": get_genre_feedback(),
    }


@router.get("/recommendations")
async def get_recommendations():
    """Get latest published recommendations for Lampa plugin."""
    from movie_recommender.publishers.feedback import _published, get_feedback

    feedback = get_feedback()
    seen_ids: set[int] = set()
    recommendations = []

    for msg_id, movie_info in _published.items():
        tmdb_id = movie_info.get("tmdb_id")
        if not tmdb_id or tmdb_id in seen_ids:
            continue
        seen_ids.add(tmdb_id)

        fb = feedback.get(str(tmdb_id), {})
        fav = fb.get("favorites", 0)
        likes = fb.get("likes", 0)
        dislikes = fb.get("dislikes", 0)
        blocks = fb.get("blocks", 0)

        # Skip if 💩 > 🔥 — community says bad
        if blocks > 0 and blocks > fav:
            continue
        # Skip if any reaction — already watched
        if fav + likes + dislikes + blocks > 0:
            continue
        # Skip old movies (before 2020)
        movie_year = movie_info.get("year") or 0
        if movie_year and movie_year < 2020:
            continue

        score = movie_info.get("score") or 0
        genre_list = movie_info.get("genres", [])
        genres_str = ", ".join(genre_list)

        recommendations.append({
            "id": tmdb_id,
            "title": movie_info.get("title", ""),
            "original_title": movie_info.get("original_title", ""),
            "poster_path": movie_info.get("poster_path", ""),
            "vote_average": movie_info.get("vote_average") or score * 10,
            "vote_count": movie_info.get("vote_count", 0),
            "release_date": f"{movie_year}-01-01" if movie_year else "",
            "overview": genres_str,
            "genre_ids": [],
            "genres": genre_list,
            "media_type": "movie",
            "score": score,
        })

    # Ranking: TMDB rating + popularity + pipeline score + freshness
    import math
    from datetime import datetime
    current_year = datetime.now().year

    for r in recommendations:
        rating = r.get("vote_average") or 5.0
        vote_count = r.get("vote_count", 0)
        popularity = min(math.log1p(vote_count) / math.log1p(10000), 1.0)
        pipeline = r.get("score") or 0.5
        try:
            year = int(r.get("release_date", "")[:4])
            freshness = min(max(year - 2020, 0) / (current_year - 2020), 1.0)
        except (ValueError, TypeError):
            freshness = 0.5

        # Quality: high rating = good. Below 7.5 with many votes = controversial, penalize
        # Bayesian: blend toward prior (6.5) when few votes, trust rating when many
        prior = 6.5
        min_votes = 500
        bayesian_rating = (vote_count * rating + min_votes * prior) / (vote_count + min_votes)
        quality = min(max(bayesian_rating - 5.0, 0) / 5.0, 1.0)  # 5.0->0, 10.0->1.0

        # Skip controversial/mediocre: Bayesian rating < 7.0 with enough votes
        if bayesian_rating < 7.0 and vote_count >= 200:
            continue

        r["rank_score"] = round(quality * 0.40 + popularity * 0.15 + pipeline * 0.20 + freshness * 0.25, 4)
        r["vote_count"] = vote_count

    # Remove movies that got skipped by Bayesian filter (no rank_score)
    recommendations = [r for r in recommendations if r.get("rank_score")]
    recommendations.sort(key=lambda x: x["rank_score"], reverse=True)

    return {
        "results": recommendations,
        "total": len(recommendations),
    }


@router.post("/backfill")
async def backfill_published():
    """Enrich existing published messages with TMDB metadata (poster, year, etc)."""
    from movie_recommender.publishers.feedback import _published
    from movie_recommender.core.storage import save_json
    from movie_recommender.ingest.tmdb_client import get_movie_details
    import asyncio

    updated = 0
    for msg_id, info in _published.items():
        tmdb_id = info.get("tmdb_id")
        if not tmdb_id:
            continue
        # Skip if already has poster_path AND vote_count
        if info.get("poster_path") and info.get("vote_count"):
            continue
        try:
            details = await get_movie_details(tmdb_id)
            release_date = details.get("release_date", "") or ""
            year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None
            info["poster_path"] = details.get("poster_path", "") or ""
            info["original_title"] = details.get("original_title", "")
            info["year"] = year
            info["vote_average"] = details.get("vote_average")
            info["vote_count"] = details.get("vote_count", 0)
            if not info.get("title"):
                info["title"] = details.get("title", "")
            updated += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning("Backfill failed", tmdb_id=tmdb_id, error=str(e))

    save_json("published_messages", _published)
    return {"status": "done", "updated": updated, "total": len(_published)}


async def _run_pipeline_task(top_n: int):
    from movie_recommender.pipeline.runner import run_pipeline
    from datetime import datetime

    _pipeline_status["running"] = True
    try:
        results = await run_pipeline(top_n)
        _pipeline_status["last_result"] = {
            "published": len(results),
            "movies": [r["movie"].get("title_ru") for r in results],
        }
    except Exception as e:
        logger.error("Pipeline failed", error=str(e))
        _pipeline_status["last_result"] = {"error": str(e)}
    finally:
        _pipeline_status["running"] = False
        _pipeline_status["last_run"] = datetime.utcnow().isoformat()

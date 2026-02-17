"""Pipeline API -- запуск и управление рекомендательным пайплайном."""

import asyncio
import math
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks
import structlog

from movie_recommender.core.config import settings
from movie_recommender.core.storage import save_json
from movie_recommender.ingest.cub_client import fetch_cub_reactions
from movie_recommender.ingest.tmdb_client import get_movie_details
from movie_recommender.publishers.feedback import (
    get_published,
    get_feedback as get_tg_feedback,
    get_genre_feedback,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_pipeline_status: dict = {"running": False, "last_run": None, "last_result": None}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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
async def feedback_endpoint():
    """Получить обратную связь по реакциям из Telegram."""
    return {
        "movies": get_tg_feedback(),
        "genre_scores": get_genre_feedback(),
    }


@router.get("/recommendations")
async def get_recommendations():
    """Get latest published recommendations for Lampa plugin."""
    pre_candidates = _filter_by_telegram_signals()
    cub_reactions = await fetch_cub_reactions([tid for tid, _ in pre_candidates])
    recommendations = _apply_cub_and_country_filters(pre_candidates, cub_reactions)
    recommendations = _rank(recommendations)
    return {"results": recommendations, "total": len(recommendations)}


@router.post("/backfill")
async def backfill_published():
    """Enrich existing published messages with TMDB metadata."""
    published = get_published()
    updated = 0
    for msg_id, info in published.items():
        tmdb_id = info.get("tmdb_id")
        if not tmdb_id:
            continue
        if info.get("poster_path") and info.get("vote_count") and info.get("countries") is not None:
            continue
        try:
            details = await get_movie_details(tmdb_id)
            release_date = details.get("release_date", "") or ""
            year = _parse_year(release_date)
            info["poster_path"] = details.get("poster_path", "") or ""
            info["original_title"] = details.get("original_title", "")
            info["year"] = year
            info["vote_average"] = details.get("vote_average")
            info["vote_count"] = details.get("vote_count", 0)
            info["countries"] = [c.get("name", "") for c in details.get("production_countries", [])]
            if not info.get("title"):
                info["title"] = details.get("title", "")
            updated += 1
            await asyncio.sleep(settings.tmdb_request_delay)
        except Exception as e:
            logger.warning("Backfill failed", tmdb_id=tmdb_id, error=str(e))

    save_json("published_messages", published)
    return {"status": "done", "updated": updated, "total": len(published)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_year(release_date: str) -> int | None:
    if len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def _filter_by_telegram_signals() -> list[tuple[int, dict]]:
    """Filter published movies by our Telegram channel reactions."""
    feedback = get_tg_feedback()
    seen_ids: set[int] = set()
    candidates = []

    for _msg_id, movie_info in get_published().items():
        tmdb_id = movie_info.get("tmdb_id")
        if not tmdb_id or tmdb_id in seen_ids:
            continue
        seen_ids.add(tmdb_id)

        fb = feedback.get(str(tmdb_id), {})
        fav = fb.get("favorites", 0)
        likes = fb.get("likes", 0)
        dislikes = fb.get("dislikes", 0)
        blocks = fb.get("blocks", 0)

        if blocks > 0 and blocks > fav:
            continue
        if fav + likes + dislikes + blocks > 0:
            continue

        movie_year = movie_info.get("year") or 0
        if movie_year and movie_year < settings.rec_min_year:
            continue

        candidates.append((tmdb_id, movie_info))

    return candidates


def _apply_cub_and_country_filters(
    pre_candidates: list[tuple[int, dict]],
    cub_reactions: dict[int, dict],
) -> list[dict]:
    """Apply Lampa CUB community reactions + country filters."""
    blocked = set(settings.rec_blocked_countries)
    results = []

    for tmdb_id, movie_info in pre_candidates:
        cub = cub_reactions.get(tmdb_id, {})
        cub_fire = cub.get("fire", 0)
        cub_shit = cub.get("shit", 0)

        if cub_shit > 0 and cub_shit >= cub_fire:
            continue
        if cub_fire < settings.cub_min_fires:
            continue

        countries = movie_info.get("countries") or []
        if len(countries) == 1 and countries[0] in blocked:
            continue

        score = movie_info.get("score") or 0
        movie_year = movie_info.get("year") or 0
        genre_list = movie_info.get("genres", [])

        results.append({
            "id": tmdb_id,
            "title": movie_info.get("title", ""),
            "original_title": movie_info.get("original_title", ""),
            "poster_path": movie_info.get("poster_path", ""),
            "vote_average": movie_info.get("vote_average") or score * 10,
            "vote_count": movie_info.get("vote_count", 0),
            "release_date": f"{movie_year}-01-01" if movie_year else "",
            "overview": ", ".join(genre_list),
            "genre_ids": [],
            "genres": genre_list,
            "media_type": "movie",
            "score": score,
            "cub_fire": cub_fire,
            "cub_shit": cub_shit,
        })

    return results


def _rank(recommendations: list[dict]) -> list[dict]:
    """Compute rank_score and sort. Drops movies failing Bayesian filter."""
    current_year = datetime.now().year

    for r in recommendations:
        rating = r.get("vote_average") or 5.0
        vote_count = r.get("vote_count", 0)
        tmdb_pop = min(math.log1p(vote_count) / math.log1p(10000), 1.0)
        pipeline = r.get("score") or 0.5

        try:
            year = int(r.get("release_date", "")[:4])
            freshness = min(max(year - settings.rec_min_year, 0) / (current_year - settings.rec_min_year), 1.0)
        except (ValueError, TypeError, ZeroDivisionError):
            freshness = 0.5

        bayesian = (vote_count * rating + settings.rec_bayesian_min_votes * settings.rec_bayesian_prior) / (
            vote_count + settings.rec_bayesian_min_votes
        )
        quality = min(max(bayesian - 5.0, 0) / 5.0, 1.0)

        if bayesian < settings.rec_bayesian_min_rating and vote_count >= settings.rec_bayesian_vote_threshold:
            continue

        cub_fire = r.get("cub_fire", 0)
        cub_shit = r.get("cub_shit", 0)
        fire_ratio = cub_fire / (cub_fire + cub_shit) if (cub_fire + cub_shit) > 0 else 0.5
        cub_pop = min(math.log1p(cub_fire) / math.log1p(5000), 1.0)

        r["rank_score"] = round(
            quality * settings.rank_quality
            + fire_ratio * settings.rank_fire_ratio
            + cub_pop * settings.rank_cub_popularity
            + tmdb_pop * settings.rank_tmdb_popularity
            + pipeline * settings.rank_pipeline
            + freshness * settings.rank_freshness,
            4,
        )

    ranked = [r for r in recommendations if r.get("rank_score")]
    ranked.sort(key=lambda x: x["rank_score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _run_pipeline_task(top_n: int):
    from movie_recommender.pipeline.runner import run_pipeline

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

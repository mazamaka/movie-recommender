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

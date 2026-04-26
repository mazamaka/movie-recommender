"""FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from movie_recommender.api.v1.sync import router as sync_router
from movie_recommender.api.v1.pipeline import router as pipeline_router
from movie_recommender.core.config import settings
from movie_recommender.core.database import init_db
from movie_recommender.publishers.feedback import reaction_poll_loop

logger = structlog.get_logger()
STATIC_DIR = Path(__file__).parent / "static"


async def _scheduled_pipeline():
    """Run pipeline daily at 21:00 Budapest time (Europe/Budapest)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from movie_recommender.pipeline.runner import run_pipeline

    tz = ZoneInfo("Europe/Budapest")

    while True:
        now = datetime.now(tz)
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Pipeline scheduled", next_run=target.isoformat(), wait_hours=round(wait_seconds / 3600, 1))
        await asyncio.sleep(wait_seconds)
        try:
            logger.info("Scheduled pipeline run starting")
            results = await run_pipeline()
            logger.info("Scheduled pipeline done", published=len(results))
        except Exception as e:
            logger.error("Scheduled pipeline failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    poll_task = asyncio.create_task(reaction_poll_loop())
    schedule_task = asyncio.create_task(_scheduled_pipeline())
    yield
    poll_task.cancel()
    schedule_task.cancel()


app = FastAPI(
    title="Movie Recommender",
    description="Smart movie recommender with Lampa sync",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sync_router, prefix="/api/v1")
app.include_router(pipeline_router, prefix="/api/v1")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return {
        "app": "movie-recommender",
        "version": "0.3.0",
        "endpoints": {
            "plugin": "/static/lampa_plugin.js",
            "sync": "/api/v1/sync/health",
            "pipeline": "/api/v1/pipeline/run",
            "feedback": "/api/v1/pipeline/feedback",
            "docs": "/docs",
        },
    }

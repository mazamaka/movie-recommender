"""FastAPI application."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from movie_recommender.api.v1.sync import router as sync_router
from movie_recommender.api.v1.pipeline import router as pipeline_router
from movie_recommender.core.database import init_db
from movie_recommender.publishers.feedback import reaction_poll_loop

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Start reaction polling in background
    poll_task = asyncio.create_task(reaction_poll_loop())
    yield
    poll_task.cancel()


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

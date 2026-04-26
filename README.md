# Movie Recommender

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Typing: mypy](https://img.shields.io/badge/typing-mypy%20strict-blue.svg)](https://mypy-lang.org/)

Smart movie recommender that analyzes your [Lampa](https://lampa.app) watch history, builds a taste profile, finds quality torrents, and publishes curated recommendations to a Telegram channel -- fully automated.

<p align="center">
  <img src="logo.png" width="200" alt="Movie Recommender Logo">
</p>

## How It Works

1. **Sync** -- Lampa plugin pushes your watch history, bookmarks, likes, and drops via REST API
2. **Enrich** -- Each movie is enriched with metadata from TMDB (genres, cast, ratings, trailers)
3. **Profile** -- A preference profile is built from your history (genre/actor/director weights)
4. **Discover** -- Candidates are gathered from TMDB trending, discover, recommendations, and similar movies
5. **Score** -- Content-based scoring (genre similarity, actor/director match, rating, freshness) + Telegram reaction feedback
6. **Search** -- Jackett searches multiple torrent trackers; results are filtered by quality, seeders, and Russian audio
7. **Publish** -- Best picks are posted to Telegram with posters, ratings, trailers, and HDRezka user reviews
8. **Feedback** -- Channel reactions (fire/thumbs/poop) feed back into the next pipeline run

## Features

- **Lampa integration** -- real-time sync via CUB cloud or JSON backup import
- **Content-based recommender** -- TF-IDF-style scoring on genres, actors, directors
- **Multi-source torrent search** -- Jackett aggregator with quality/seeders/language filters
- **Telegram publisher** -- rich posts with poster, ratings, cast, trailer link, and HDRezka reviews
- **Reaction feedback loop** -- fire = boost similar, poop = suppress genre, thumbs adjust scores
- **Bot commands** -- `/search`, `/top`, `/help` in the discussion group
- **CUB community signals** -- Lampa CUB fire/shit reactions filter out unpopular content
- **Bayesian ranking** -- weighted composite score (quality, fire ratio, CUB popularity, freshness)
- **Country & genre blocking** -- configurable blocked countries and auto-blocked genres from reactions
- **Scheduled pipeline** -- runs automatically every N hours
- **CLI interface** -- `movie-recommender sync | recommend | search | serve`
- **Lampa plugin** -- JavaScript plugin served as a static file for direct Lampa integration

## Architecture

```
src/movie_recommender/
├── api/v1/
│   ├── sync.py            # Lampa sync endpoints (push/pull/history/backup)
│   └── pipeline.py        # Pipeline control, feedback, recommendations API
├── cli/
│   └── main.py            # Typer CLI (sync, recommend, search, serve)
├── core/
│   ├── config.py          # Pydantic Settings (all env vars)
│   ├── database.py        # SQLite via SQLModel + aiosqlite
│   └── storage.py         # Persistent JSON storage on Docker volume
├── filters/
│   └── pipeline.py        # Filter chain: seeders -> quality -> language
├── ingest/
│   ├── lampa_parser.py    # CUB cloud sync, backup parser, TorrServer history
│   ├── tmdb_client.py     # TMDB API (details, search, trending, discover)
│   └── cub_client.py      # Lampa CUB community reactions API
├── models/                # Pydantic/SQLModel data models
├── pipeline/
│   └── runner.py          # 8-step pipeline orchestrator
├── publishers/
│   ├── telegram.py        # Telegram channel publisher (rich HTML formatting)
│   ├── feedback.py        # Reaction polling + feedback tracker
│   ├── bot_commands.py    # /search, /top, /help command handler
│   ├── rezka_reviews.py   # HDRezka review scraper + comment poster
│   └── trailer_finder.py  # YouTube trailer search
├── recommender/
│   ├── content_based.py   # Scoring engine (genre/actor/director/rating/freshness)
│   └── profile_builder.py # Build preference weights from watch history
├── search/
│   ├── base.py            # SearchResult dataclass + BaseTorrentSearcher ABC
│   ├── jackett.py         # Jackett API integration
│   └── aggregator.py      # Multi-source parallel search + dedup
├── static/                # Lampa JS plugins
├── app.py                 # FastAPI application + lifespan (scheduler, poll loop)
└── __main__.py            # python -m entry point
```

## Quick Start

### Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/mazamaka/movie-recommender.git
cd movie-recommender

# Configure environment
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# Start services (app + Jackett)
docker compose up -d

# The API is available at http://localhost:9200
# Jackett UI at http://localhost:9117
```

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in API keys

movie-recommender serve          # start API server
movie-recommender sync           # check sync status
movie-recommender recommend 5    # run pipeline, publish top 5
movie-recommender search "Inception"  # search torrents
```

## Configuration

All settings are managed via environment variables (`.env` file). See [`.env.example`](.env.example) for the full list.

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | Yes |
| `TELEGRAM_CHANNEL_ID` | Target Telegram channel ID | Yes |
| `TELEGRAM_DISCUSSION_GROUP_ID` | Discussion group for bot commands | No |
| `TMDB_API_KEY` | TMDB API key for movie metadata | Yes |
| `JACKETT_URL` | Jackett instance URL | Yes |
| `JACKETT_API_KEY` | Jackett API key | Yes |
| `LAMPA_CUB_TOKEN` | Lampa CUB cloud sync token | No |
| `KP_API_TOKEN` | Kinopoisk API token | No |
| `YOUTUBE_API_KEY` | YouTube Data API key for trailers | No |
| `TORRSERVER_URL` | TorrServer instance URL | No |
| `MIN_RATING_KP` | Minimum Kinopoisk rating (default: 6.5) | No |
| `MIN_RATING_IMDB` | Minimum IMDB rating (default: 6.0) | No |
| `MIN_SEEDERS` | Minimum seeders for torrents (default: 5) | No |
| `QUALITY_FILTER` | Minimum video quality (default: 1080p) | No |
| `PIPELINE_INTERVAL_HOURS` | Auto-run interval in hours (default: 12) | No |
| `RECOMMEND_TOP_N` | Number of recommendations per run (default: 10) | No |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | App info and endpoint index |
| `GET` | `/docs` | Interactive Swagger UI |
| `POST` | `/api/v1/sync/push` | Receive Lampa sync data |
| `GET` | `/api/v1/sync/pull` | Return sync data to Lampa |
| `GET` | `/api/v1/sync/history` | Full watch history + signals |
| `POST` | `/api/v1/sync/backup/import` | Import Lampa JSON backup |
| `GET` | `/api/v1/sync/health` | Sync status and counts |
| `POST` | `/api/v1/pipeline/run` | Trigger recommendation pipeline |
| `GET` | `/api/v1/pipeline/status` | Pipeline run status |
| `GET` | `/api/v1/pipeline/feedback` | Telegram reaction feedback |
| `GET` | `/api/v1/pipeline/recommendations` | Ranked recommendations for Lampa |
| `POST` | `/api/v1/pipeline/backfill` | Enrich published posts with TMDB data |

## Tech Stack

- **Runtime**: Python 3.12+, async/await throughout
- **Web**: FastAPI + Uvicorn
- **Database**: SQLite via SQLModel + aiosqlite
- **ML**: scikit-learn, NumPy (content-based scoring)
- **HTTP**: httpx (async client for TMDB, Telegram, Jackett, CUB, YouTube)
- **Telegram**: python-telegram-bot for publishing, raw Bot API for polling
- **Scraping**: BeautifulSoup4 + lxml (HDRezka reviews)
- **Torrent search**: Jackett (multi-tracker aggregator)
- **CLI**: Typer + Rich
- **Config**: pydantic-settings (env vars)
- **Logging**: structlog
- **Scheduling**: APScheduler + asyncio background tasks
- **Containerization**: Docker + Docker Compose
- **Code quality**: ruff (linting + formatting), mypy (strict typing), pytest

"""Full recommendation pipeline: sync -> enrich -> profile -> candidates -> score -> search -> filter -> publish."""
import asyncio
import json
import random
from datetime import datetime

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.ingest.tmdb_client import (
    get_movie_details, search_movie, get_trending, discover_movies,
    get_recommendations, get_similar,
)
from movie_recommender.recommender.content_based import score_movie
from movie_recommender.recommender.profile_builder import build_profile
from movie_recommender.publishers.feedback import get_genre_feedback, get_blocked_genres, get_published_tmdb_ids, pause_poll, resume_poll
from movie_recommender.search.aggregator import TorrentAggregator
from movie_recommender.filters.pipeline import FilterPipeline
from movie_recommender.publishers.telegram import publish_recommendation
from movie_recommender.publishers.rezka_reviews import fetch_rezka_reviews, post_reviews_as_comments
from movie_recommender.publishers.trailer_finder import find_trailer

logger = structlog.get_logger()


async def run_pipeline(top_n: int | None = None) -> list[dict]:
    """Run the full recommendation pipeline."""
    top_n = top_n or settings.recommend_top_n

    # Step 1: Get watch history
    logger.info("Pipeline step 1: getting watch history")
    history, signals = await _get_sync_history()
    if not history:
        logger.warning("No watch history, using trending only")
        signals = {}

    # Step 2: Enrich with TMDB
    logger.info("Pipeline step 2: enriching with TMDB", count=len(history))
    enriched = await _enrich_movies(history)
    logger.info("Enriched movies", count=len(enriched))

    # Step 3: Build user profile
    logger.info("Pipeline step 3: building profile")
    profile = build_profile(enriched) if enriched else {}
    if profile.get("genre_weights"):
        logger.info("Profile genres", top=list(profile["genre_weights"].keys())[:5])

    # Step 4: Get candidates (expanded sources)
    logger.info("Pipeline step 4: getting candidates")
    candidates = await _get_candidates(enriched, profile, signals)
    logger.info("Candidates found", count=len(candidates))

    # Step 5: Score, rank, deduplicate
    watched_ids = {m.get("tmdb_id") for m in enriched if m.get("tmdb_id")}
    # Also exclude raw history IDs (including TV shows that failed to enrich)
    for item in history:
        tid = item.get("tmdb_id")
        if tid:
            watched_ids.add(tid)
    thrown_ids = signals.get("thrown", set()) if signals else set()
    liked_ids = signals.get("liked", set()) if signals else set()
    published_ids = get_published_tmdb_ids()  # DEDUP: skip already published
    genre_feedback = get_genre_feedback()
    blocked_genres = get_blocked_genres()

    scored = []
    for c in candidates:
        cid = c.get("tmdb_id")
        if cid in watched_ids:
            continue
        if cid in thrown_ids:
            continue
        if cid in published_ids:
            continue  # DEDUP
        # Skip movies with blocked genres (💩 reaction)
        movie_genres = c.get("genres", [])
        if isinstance(movie_genres, str):
            movie_genres = json.loads(movie_genres)
        if blocked_genres and movie_genres:
            blocked_overlap = len(set(movie_genres) & blocked_genres)
            if blocked_overlap >= len(movie_genres) * 0.5:
                continue  # Skip if 50%+ genres are blocked

        s = score_movie(c, profile) if profile else 0.5
        # Boost if similar genres to liked movies
        if liked_ids and enriched:
            liked_genres = set()
            for m in enriched:
                if m.get("tmdb_id") in liked_ids:
                    g = m.get("genres", [])
                    if isinstance(g, list):
                        liked_genres.update(g)
            if isinstance(movie_genres, list) and liked_genres:
                overlap = len(set(movie_genres) & liked_genres) / max(len(movie_genres), 1)
                s = min(s + overlap * 0.15, 1.0)
        # Apply Telegram reaction feedback (favorites=2x, blocks=-3x)
        if genre_feedback:
            feedback_bonus = sum(genre_feedback.get(g, 0.0) for g in movie_genres) * 0.1
            s = min(max(s + feedback_bonus, 0.0), 1.0)
        scored.append({**c, "score": s})
    # Filter out unreleased movies
    today = datetime.now().strftime("%Y-%m-%d")
    scored = [c for c in scored if not c.get("release_date") or c["release_date"] <= today]

    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        "Pipeline step 5: scored candidates",
        count=len(scored), thrown=len(thrown_ids),
        deduped=len(published_ids), feedback_genres=len(genre_feedback),
    )

    if not scored:
        logger.warning("No new candidates after dedup, nothing to publish")
        return []

    # Step 6-7: Search torrents + filter
    logger.info("Pipeline step 6-7: searching torrents")
    recommendations = []
    agg = TorrentAggregator()
    pipe = FilterPipeline()

    for movie in scored[:top_n * 10]:
        title_ru = movie.get("title_ru", "")
        title_en = movie.get("title_en", "")
        year = movie.get("year")
        if not title_ru and not title_en:
            continue
        try:
            results = await _search_torrent(agg, title_ru, title_en, year)
            logger.debug("Torrent search", title=title_ru or title_en, year=year, results=len(results))
            filtered = pipe.execute(results)
            if not filtered:
                filtered = [r for r in results if r.seeders >= settings.min_seeders and r.quality in ("2160p", "1080p")]
            if filtered:
                best = filtered[0]
                recommendations.append({
                    "movie": movie,
                    "torrent": {
                        "title": best.title,
                        "magnet_link": best.magnet_link,
                        "size_gb": best.size_gb,
                        "seeders": best.seeders,
                        "quality": best.quality,
                        "audio": best.audio,
                        "tracker": best.tracker,
                    },
                    "score": movie["score"],
                })
        except Exception as e:
            logger.warning("Search failed for movie", title=title_ru or title_en, error=str(e))

        if len(recommendations) >= top_n:
            break

    # Step 8: Publish (pause poll loop to avoid getUpdates conflict)
    logger.info("Pipeline step 8: publishing", count=len(recommendations))
    pause_poll()
    published = 0
    try:
        for rec in recommendations:
            trailer_url = rec["movie"].get("trailer_url")
            if not trailer_url:
                trailer_url = await find_trailer(
                    rec["movie"].get("title_ru", ""), rec["movie"].get("year")
                )

            # Fetch Rezka reviews + get Rezka URL for the post
            rezka_url = None
            reviews = []
            try:
                reviews, rezka_url = await fetch_rezka_reviews(
                    rec["movie"].get("title_ru", ""), rec["movie"].get("year")
                )
            except Exception as e:
                logger.warning("Rezka reviews failed", error=str(e))

            msg_id = await publish_recommendation(
                rec["movie"], rec["torrent"], trailer_url, rezka_url,
            )
            if msg_id:
                published += 1
                if reviews:
                    try:
                        await post_reviews_as_comments(msg_id, reviews[:5], rec["movie"].get("title_ru", ""))
                    except Exception as e:
                        logger.warning("Rezka comments failed", error=str(e))
            await asyncio.sleep(3)
    finally:
        resume_poll()

    logger.info("Pipeline complete", total_scored=len(scored), published=published)
    return recommendations


async def _get_sync_history() -> tuple[list[dict], dict]:
    """Get watch history and signals from local sync API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("http://localhost:9000/api/v1/sync/history")
            data = resp.json()
            items = data.get("items", [])

            seen = {i.get("tmdb_id") for i in items if i.get("tmdb_id")}
            for tmdb_id in data.get("bookmarks", []):
                if isinstance(tmdb_id, int) and tmdb_id not in seen:
                    items.append({"tmdb_id": tmdb_id, "type": "movie"})
                    seen.add(tmdb_id)
            for tmdb_id in data.get("liked", []):
                if isinstance(tmdb_id, int) and tmdb_id not in seen:
                    items.append({"tmdb_id": tmdb_id, "type": "movie"})
                    seen.add(tmdb_id)
            for tmdb_id in data.get("viewed", []):
                if isinstance(tmdb_id, int) and tmdb_id not in seen:
                    items.append({"tmdb_id": tmdb_id, "type": "movie"})
                    seen.add(tmdb_id)

            signals = {
                "liked": set(data.get("liked", [])),
                "thrown": set(data.get("thrown", [])),
                "viewed": set(data.get("viewed", [])),
                "wath": set(data.get("wath", [])),
                "booked": set(data.get("booked", [])),
            }

            return items, signals
    except Exception as e:
        logger.error("Failed to get sync history", error=str(e))
        return [], {}


async def _enrich_movies(items: list[dict]) -> list[dict]:
    """Enrich history items with TMDB metadata."""
    enriched = []
    seen_ids: set[int] = set()

    for item in items:
        tmdb_id = item.get("tmdb_id")
        if tmdb_id and tmdb_id in seen_ids:
            continue
        if tmdb_id:
            seen_ids.add(tmdb_id)

        try:
            if tmdb_id:
                details = await get_movie_details(tmdb_id)
            elif item.get("title"):
                results = await search_movie(item["title"], item.get("year"))
                if not results:
                    continue
                details = await get_movie_details(results[0]["id"])
                seen_ids.add(results[0]["id"])
            else:
                continue
            enriched.append(tmdb_to_movie(details))
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning("Enrich failed", title=item.get("title"), error=str(e))

    return enriched


def tmdb_to_movie(d: dict) -> dict:
    """Convert TMDB API response to internal movie dict."""
    genres = [g["name"] for g in d.get("genres", [])]
    credits = d.get("credits", {})
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    actors = [c["name"] for c in credits.get("cast", [])[:10]]

    trailer_url = None
    for v in d.get("videos", {}).get("results", []):
        if v.get("type") == "Trailer" and v.get("site") == "YouTube":
            trailer_url = f"https://www.youtube.com/watch?v={v['key']}"
            break

    release_date = d.get("release_date", "") or ""
    year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None

    return {
        "tmdb_id": d.get("id"),
        "title_ru": d.get("title", ""),
        "title_en": d.get("original_title", ""),
        "release_date": release_date,
        "year": year,
        "rating_imdb": d.get("vote_average"),
        "vote_count": d.get("vote_count", 0),
        "popularity": d.get("popularity", 0),
        "rating_kp": None,
        "genres": genres,
        "directors": directors,
        "actors": actors,
        "description": d.get("overview", ""),
        "poster_url": f"https://image.tmdb.org/t/p/w500{d['poster_path']}" if d.get("poster_path") else None,
        "runtime_min": d.get("runtime"),
        "trailer_url": trailer_url,
        "countries": [c.get("name", "") for c in d.get("production_countries", [])],
    }


async def _get_candidates(watched: list[dict], profile: dict, signals: dict | None = None) -> list[dict]:
    """Get candidate movies from multiple TMDB sources."""
    candidates = []
    seen: set[int] = set()

    async def _add_from_list(items: list[dict], limit: int = 10):
        for t in items[:limit]:
            tid = t.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            try:
                details = await get_movie_details(tid)
                candidates.append(tmdb_to_movie(details))
                await asyncio.sleep(0.3)
            except Exception:
                pass

    # 1) Trending (week + day)
    try:
        trending = await get_trending("movie", "week")
        await _add_from_list(trending, 15)
    except Exception as e:
        logger.warning("Trending week failed", error=str(e))

    try:
        trending_day = await get_trending("movie", "day")
        await _add_from_list(trending_day, 10)
    except Exception as e:
        logger.warning("Trending day failed", error=str(e))

    # 2) Discover by top genres (more genres, multiple years)
    top_genres = list(profile.get("genre_weights", {}).keys())[:5]
    for i in range(0, len(top_genres), 2):
        genre_chunk = top_genres[i:i+2]
        if genre_chunk:
            for min_year in [2024, 2022]:
                try:
                    discovered = await discover_movies(genre_chunk, min_year=min_year)
                    await _add_from_list(discovered, 10)
                except Exception:
                    pass

    # 3) Recommendations based on top-rated watched movies
    top_watched = sorted(watched, key=lambda m: m.get("rating_imdb", 0) or 0, reverse=True)
    # Pick up to 5 best-rated watched movies for recommendations
    liked_ids = signals.get("liked", set()) if signals else set()
    seed_movies = []
    for m in top_watched:
        tmdb_id = m.get("tmdb_id")
        if tmdb_id and (tmdb_id in liked_ids or (m.get("rating_imdb") or 0) >= 7.0):
            seed_movies.append(tmdb_id)
        if len(seed_movies) >= 5:
            break
    # Shuffle to get variety across runs
    random.shuffle(seed_movies)

    for seed_id in seed_movies[:3]:
        try:
            recs = await get_recommendations(seed_id)
            await _add_from_list(recs, 8)
        except Exception:
            pass
        try:
            sims = await get_similar(seed_id)
            await _add_from_list(sims, 5)
        except Exception:
            pass

    # 4) Discover by favorite directors
    top_directors = list(profile.get("director_weights", {}).keys())[:3]
    if top_directors:
        # Use general discover with high rating as proxy (TMDB doesn't support director filter in discover)
        try:
            discovered = await discover_movies(top_genres[:2], min_year=2020)
            await _add_from_list(discovered, 10)
        except Exception:
            pass

    logger.info("Candidates from all sources", total=len(candidates))
    return candidates


async def _search_torrent(agg: TorrentAggregator, title_ru: str, title_en: str, year: int | None) -> list:
    """Try multiple search strategies to find torrents."""
    # Strategy 1: Russian title + year
    if title_ru:
        results = await agg.search_all(title_ru, year)
        if results:
            return results

    # Strategy 2: English title + year
    if title_en and title_en != title_ru:
        results = await agg.search_all(title_en, year)
        if results:
            return results

    # Strategy 3: Russian title without year
    if title_ru and year:
        results = await agg.search_all(title_ru, None)
        if results:
            return results

    # Strategy 4: English title without year
    if title_en and title_en != title_ru and year:
        results = await agg.search_all(title_en, None)
        if results:
            return results

    return []

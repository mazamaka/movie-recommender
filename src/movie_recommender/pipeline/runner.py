"""Full recommendation pipeline: sync -> enrich -> profile -> candidates -> score -> search -> filter -> publish."""
import asyncio
import json

import httpx
import structlog

from movie_recommender.core.config import settings
from movie_recommender.ingest.tmdb_client import get_movie_details, search_movie, get_trending, discover_movies
from movie_recommender.recommender.content_based import score_movie
from movie_recommender.recommender.profile_builder import build_profile
from movie_recommender.publishers.feedback import get_genre_feedback
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

    # Step 4: Get candidates
    logger.info("Pipeline step 4: getting candidates")
    candidates = await _get_candidates(enriched, profile)
    logger.info("Candidates found", count=len(candidates))

    # Step 5: Score and rank (with feedback + Lampa signals)
    watched_ids = {m.get("tmdb_id") for m in enriched if m.get("tmdb_id")}
    thrown_ids = signals.get("thrown", set()) if signals else set()
    liked_ids = signals.get("liked", set()) if signals else set()
    genre_feedback = get_genre_feedback()
    scored = []
    for c in candidates:
        cid = c.get("tmdb_id")
        if cid in watched_ids:
            continue
        # Skip thrown/dropped movies
        if cid in thrown_ids:
            continue
        s = score_movie(c, profile) if profile else 0.5
        # Boost if similar genres to liked movies
        if liked_ids and enriched:
            liked_genres = set()
            for m in enriched:
                if m.get("tmdb_id") in liked_ids:
                    g = m.get("genres", [])
                    if isinstance(g, list):
                        liked_genres.update(g)
            movie_genres = c.get("genres", [])
            if isinstance(movie_genres, list) and liked_genres:
                overlap = len(set(movie_genres) & liked_genres) / max(len(movie_genres), 1)
                s = min(s + overlap * 0.15, 1.0)
        # Apply Telegram reaction feedback
        if genre_feedback:
            movie_genres = c.get("genres", [])
            if isinstance(movie_genres, str):
                import json as _json
                movie_genres = _json.loads(movie_genres)
            feedback_bonus = sum(genre_feedback.get(g, 0.0) for g in movie_genres) * 0.1
            s = min(max(s + feedback_bonus, 0.0), 1.0)
        scored.append({**c, "score": s})
    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Pipeline step 5: scored candidates", count=len(scored), thrown=len(thrown_ids), feedback_genres=len(genre_feedback))

    # Step 6-7: Search torrents + filter
    logger.info("Pipeline step 6-7: searching torrents")
    recommendations = []
    agg = TorrentAggregator()
    pipe = FilterPipeline()

    for movie in scored[:top_n * 3]:
        title = movie.get("title_ru") or movie.get("title_en", "")
        if not title:
            continue
        try:
            results = await agg.search_all(title, movie.get("year"))
            filtered = pipe.execute(results)
            if not filtered:
                # Try relaxed: just seeders filter
                filtered = [r for r in results if r.seeders >= settings.min_seeders]
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
            logger.warning("Search failed for movie", title=title, error=str(e))

        if len(recommendations) >= top_n:
            break

    # Step 8: Publish
    logger.info("Pipeline step 8: publishing", count=len(recommendations))
    published = 0
    for rec in recommendations:
        trailer_url = rec["movie"].get("trailer_url")
        if not trailer_url:
            trailer_url = await find_trailer(
                rec["movie"].get("title_ru", ""), rec["movie"].get("year")
            )
        msg_id = await publish_recommendation(rec["movie"], rec["torrent"], trailer_url)
        if msg_id:
            published += 1
            # Post Rezka reviews as comments
            try:
                reviews = await fetch_rezka_reviews(
                    rec["movie"].get("title_ru", ""), rec["movie"].get("year")
                )
                if reviews:
                    await post_reviews_as_comments(msg_id, reviews[:3], rec["movie"].get("title_ru", ""))
            except Exception as e:
                logger.warning("Rezka reviews failed", error=str(e))
        await asyncio.sleep(3)

    logger.info("Pipeline complete", total_scored=len(scored), published=published)
    return recommendations


async def _get_sync_history() -> tuple[list[dict], dict]:
    """Get watch history and signals from local sync API.

    Returns: (items_to_enrich, signals) where signals contain liked/thrown/etc IDs.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("http://localhost:9000/api/v1/sync/history")
            data = resp.json()
            items = data.get("items", [])

            # Add bookmarks, liked, booked, wath as items to enrich
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
            await asyncio.sleep(0.3)  # TMDB rate limit
        except Exception as e:
            logger.warning("Enrich failed", title=item.get("title"), error=str(e))

    return enriched


def tmdb_to_movie(d: dict) -> dict:
    """Convert TMDB API response to internal movie dict."""
    genres = [g["name"] for g in d.get("genres", [])]
    credits = d.get("credits", {})
    directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
    actors = [c["name"] for c in credits.get("cast", [])[:10]]

    # Find trailer
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
        "year": year,
        "rating_imdb": d.get("vote_average"),
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


async def _get_candidates(watched: list[dict], profile: dict) -> list[dict]:
    """Get candidate movies from TMDB trending + discover."""
    candidates = []
    seen: set[int] = set()

    # 1) Trending
    try:
        trending = await get_trending("movie", "week")
        for t in trending[:15]:
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            try:
                details = await get_movie_details(t["id"])
                candidates.append(tmdb_to_movie(details))
                await asyncio.sleep(0.3)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Trending fetch failed", error=str(e))

    # 2) Discover by top genres
    top_genres = list(profile.get("genre_weights", {}).keys())[:3]
    if top_genres:
        try:
            discovered = await discover_movies(top_genres)
            for t in discovered[:15]:
                if t["id"] in seen:
                    continue
                seen.add(t["id"])
                try:
                    details = await get_movie_details(t["id"])
                    candidates.append(tmdb_to_movie(details))
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Discover failed", error=str(e))

    return candidates

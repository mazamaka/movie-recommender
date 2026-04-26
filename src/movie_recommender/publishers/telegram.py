"""Telegram channel publisher with rich formatting."""
import structlog
from telegram import Bot

from movie_recommender.core.config import settings
from movie_recommender.publishers.feedback import save_published

logger = structlog.get_logger()


async def publish_recommendation(
    movie: dict,
    torrent: dict,
    trailer_url: str | None = None,
    rezka_url: str | None = None,
) -> int | None:
    """Publish movie recommendation to Telegram channel. Returns message_id or None."""
    bot = Bot(token=settings.telegram_bot_token)
    text = format_message(movie, torrent, trailer_url, rezka_url)

    try:
        if movie.get("poster_url"):
            msg = await bot.send_photo(
                chat_id=settings.telegram_channel_id,
                photo=movie["poster_url"],
                caption=text,
                parse_mode="HTML",
            )
        else:
            msg = await bot.send_message(
                chat_id=settings.telegram_channel_id,
                text=text,
                parse_mode="HTML",
            )

        save_published(msg.message_id, movie)
        logger.info("Published to Telegram", title=movie.get("title_ru"), message_id=msg.message_id)
        return msg.message_id
    except Exception as e:
        logger.error("Telegram publish failed", error=str(e))
        return None


def format_message(movie: dict, torrent: dict, trailer_url: str | None = None, rezka_url: str | None = None) -> str:
    """Format movie info as rich Telegram message with emojis."""
    import json

    title_ru = movie.get("title_ru", "N/A")
    title_en = movie.get("title_en", "")
    year = movie.get("year", "?")

    lines = [f"<b>{title_ru}</b> ({year})"]
    if title_en and title_en != title_ru:
        lines.append(f"<i>{title_en}</i>")
    lines.append("")

    # Ratings + vote count
    ratings = []
    if movie.get("rating_kp"):
        kp = movie["rating_kp"]
        star = _rating_emoji(kp)
        ratings.append(f"{star} KP: <b>{kp}</b>")
    if movie.get("rating_imdb"):
        imdb = movie["rating_imdb"]
        star = _rating_emoji(imdb)
        vote_count = movie.get("vote_count", 0)
        vote_str = f" ({_format_count(vote_count)})" if vote_count else ""
        ratings.append(f"{star} IMDB: <b>{imdb}</b>{vote_str}")
    if ratings:
        lines.append(" | ".join(ratings))

    # Popularity / user engagement
    vote_count = movie.get("vote_count", 0)
    popularity = movie.get("popularity", 0)
    if vote_count > 0:
        # Show how many people rated the movie
        engagement = []
        engagement.append(f"\U0001f465 {_format_count(vote_count)} \u043e\u0446\u0435\u043d\u043e\u043a")
        if popularity > 50:
            engagement.append(f"\U0001f4c8 \u043f\u043e\u043f\u0443\u043b\u044f\u0440\u043d\u043e\u0441\u0442\u044c: {popularity:.0f}")
        lines.append(" | ".join(engagement))

    # Genres
    genres = movie.get("genres", [])
    if isinstance(genres, str):
        genres = json.loads(genres)
    if genres:
        genre_emojis = {
            "\u0431\u043e\u0435\u0432\u0438\u043a": "\U0001f4a5", "\u043a\u043e\u043c\u0435\u0434\u0438\u044f": "\U0001f923",
            "\u0434\u0440\u0430\u043c\u0430": "\U0001f3ad", "\u0443\u0436\u0430\u0441\u044b": "\U0001f47b",
            "\u0444\u0430\u043d\u0442\u0430\u0441\u0442\u0438\u043a\u0430": "\U0001f680", "\u0444\u044d\u043d\u0442\u0435\u0437\u0438": "\U0001f9d9",
            "\u0442\u0440\u0438\u043b\u043b\u0435\u0440": "\U0001f631", "\u043c\u0435\u043b\u043e\u0434\u0440\u0430\u043c\u0430": "\U0001f495",
            "\u043f\u0440\u0438\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f": "\U0001f5fa", "\u0430\u043d\u0438\u043c\u0430\u0446\u0438\u044f": "\U0001f3a8",
            "\u043c\u0443\u043b\u044c\u0442\u0444\u0438\u043b\u044c\u043c": "\U0001f3a8", "\u0434\u0435\u0442\u0435\u043a\u0442\u0438\u0432": "\U0001f50d",
            "\u043a\u0440\u0438\u043c\u0438\u043d\u0430\u043b": "\U0001f52b", "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u043b\u044c\u043d\u044b\u0439": "\U0001f4f9",
            "\u0441\u0435\u043c\u0435\u0439\u043d\u044b\u0439": "\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466",
            "\u0432\u043e\u0435\u043d\u043d\u044b\u0439": "\u2694\ufe0f", "\u0438\u0441\u0442\u043e\u0440\u0438\u044f": "\U0001f4dc",
            "\u043c\u0443\u0437\u044b\u043a\u0430": "\U0001f3b5", "\u0431\u0438\u043e\u0433\u0440\u0430\u0444\u0438\u044f": "\U0001f4d6",
        }
        genre_str = ""
        for g in genres[:4]:
            emoji = genre_emojis.get(g.lower(), "\U0001f3ac")
            genre_str += f"{emoji} {g}  "
        lines.append(genre_str.strip())

    # Directors
    directors = movie.get("directors", [])
    if isinstance(directors, str):
        directors = json.loads(directors)
    if directors:
        lines.append(f"\U0001f3ac \u0420\u0435\u0436\u0438\u0441\u0441\u0451\u0440: <code>{', '.join(directors[:2])}</code>")

    # Actors
    actors = movie.get("actors", [])
    if isinstance(actors, str):
        actors = json.loads(actors)
    if actors:
        lines.append(f"\U0001f31f \u0412 \u0440\u043e\u043b\u044f\u0445: <code>{', '.join(actors[:4])}</code>")

    # Runtime
    if movie.get("runtime_min"):
        h, m = divmod(movie["runtime_min"], 60)
        lines.append(f"\u23f1 <code>{h}\u0447 {m}\u043c\u0438\u043d</code>")

    lines.append("")

    # Description
    if movie.get("description"):
        desc = movie["description"][:350]
        if len(movie["description"]) > 350:
            desc += "..."
        lines.append(f"<code>{desc}</code>")

    # LLM reasoning (only if reranker provided one)
    if movie.get("llm_reason"):
        lines.append("")
        lines.append(f"\U0001f916 <i>{movie['llm_reason']}</i>")

    lines.append("")

    # Torrent info
    quality = torrent.get("quality", "?")
    size = torrent.get("size_gb", "?")
    seeders = torrent.get("seeders", "?")
    tracker = torrent.get("tracker", "?")

    quality_emoji = "\U0001f7e2" if quality in ("2160p", "1080p") else "\U0001f7e1" if quality == "720p" else "\U0001f534"
    seed_emoji = "\U0001f525" if isinstance(seeders, int) and seeders > 100 else "\U0001f331"

    lines.append(f"{quality_emoji} <b>{quality}</b> | \U0001f4be {size} GB | {seed_emoji} {seeders} seeds | \U0001f4e1 {tracker}")

    # Audio/dubbing
    audio = torrent.get("audio", [])
    if audio:
        lines.append(f"\U0001f399 \u041e\u0437\u0432\u0443\u0447\u043a\u0430: <code>{', '.join(audio)}</code>")

    if torrent.get("speed_mbps"):
        lines.append(f"\u26a1 \u0421\u043a\u043e\u0440\u043e\u0441\u0442\u044c: <code>{torrent['speed_mbps']:.1f} MB/s</code>")

    # Score
    score = movie.get("score")
    if score:
        pct = int(score * 100)
        lines.append(f"\n\U0001f3af \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f: <b>{pct}%</b>")

    # Links inline
    links = []
    tmdb_id = movie.get("tmdb_id")
    if tmdb_id:
        links.append(f'<a href="https://www.themoviedb.org/movie/{tmdb_id}?language=ru">\U0001f4d6 TMDB</a>')
    if trailer_url:
        links.append(f'<a href="{trailer_url}">\u25b6\ufe0f \u0422\u0440\u0435\u0439\u043b\u0435\u0440</a>')
    if rezka_url:
        links.append(f'<a href="{rezka_url}">\U0001f3ac HDRezka</a>')
    if links:
        lines.append("\n" + "  |  ".join(links))

    # Reactions hint
    lines.append("\n\U0001f525 \u0444\u0430\u0432\u043e\u0440\u0438\u0442  |  \U0001f44d \u043d\u0440\u0430\u0432\u0438\u0442\u0441\u044f  |  \U0001f44e \u043d\u0435\u0442  |  \U0001f4a9 \u043d\u0435 \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u0442\u044c \u043f\u043e\u0434\u043e\u0431\u043d\u044b\u0435")

    return "\n".join(lines)


def _format_count(n: int) -> str:
    """Format large numbers: 1500 -> '1.5K', 15000 -> '15K'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _rating_emoji(rating: float) -> str:
    if rating >= 8:
        return "\U0001f31f"
    if rating >= 7:
        return "\u2b50"
    if rating >= 6:
        return "\u2728"
    return "\U0001f4ab"

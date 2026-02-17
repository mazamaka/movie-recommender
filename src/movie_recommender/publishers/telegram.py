"""Telegram channel publisher."""
import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from movie_recommender.core.config import settings

logger = structlog.get_logger()


async def publish_movie(
    movie: dict,
    torrent: dict,
    trailer_url: str | None = None,
) -> bool:
    """Publish movie recommendation to Telegram channel."""
    bot = Bot(token=settings.telegram_bot_token)

    text = format_message(movie, torrent, trailer_url)
    buttons = build_buttons(torrent, trailer_url)

    try:
        if movie.get("poster_url"):
            await bot.send_photo(
                chat_id=settings.telegram_channel_id,
                photo=movie["poster_url"],
                caption=text,
                parse_mode="HTML",
                reply_markup=buttons,
            )
        else:
            await bot.send_message(
                chat_id=settings.telegram_channel_id,
                text=text,
                parse_mode="HTML",
                reply_markup=buttons,
            )
        logger.info("Published to Telegram", title=movie.get("title_ru"))
        return True
    except Exception as e:
        logger.error("Telegram publish failed", error=str(e))
        return False


def format_message(movie: dict, torrent: dict, trailer_url: str | None = None) -> str:
    """Format movie info as Telegram message."""
    lines = [
        f"<b>{movie.get('title_ru', 'N/A')}</b> ({movie.get('year', '?')})",
    ]
    if movie.get("title_en"):
        lines.append(f"<i>{movie['title_en']}</i>")
    lines.append("")

    if movie.get("rating_kp") or movie.get("rating_imdb"):
        ratings = []
        if movie.get("rating_kp"):
            ratings.append(f"KP: {movie['rating_kp']}")
        if movie.get("rating_imdb"):
            ratings.append(f"IMDB: {movie['rating_imdb']}")
        lines.append(f"Rating: {' | '.join(ratings)}")

    if movie.get("genres"):
        lines.append(f"Genre: {movie['genres']}")
    if movie.get("directors"):
        lines.append(f"Director: {movie['directors']}")

    lines.append("")
    if movie.get("description"):
        desc = movie["description"][:300]
        if len(movie["description"]) > 300:
            desc += "..."
        lines.append(desc)

    lines.append("")
    lines.append(f"Quality: {torrent.get('quality', '?')} | {torrent.get('size_gb', '?')} GB")
    if torrent.get("audio_tracks"):
        lines.append(f"Audio: {torrent['audio_tracks']}")
    lines.append(f"Seeds: {torrent.get('seeders', '?')}")
    if torrent.get("speed_mbps"):
        lines.append(f"Speed: {torrent['speed_mbps']:.1f} MB/s")

    return "\n".join(lines)


def build_buttons(torrent: dict, trailer_url: str | None = None) -> InlineKeyboardMarkup | None:
    """Build inline keyboard with action buttons."""
    buttons = []
    if torrent.get("magnet_link"):
        buttons.append([InlineKeyboardButton("Magnet", url=torrent["magnet_link"][:64])])  # URL limit
    if trailer_url:
        buttons.append([InlineKeyboardButton("Trailer", url=trailer_url)])

    return InlineKeyboardMarkup(buttons) if buttons else None

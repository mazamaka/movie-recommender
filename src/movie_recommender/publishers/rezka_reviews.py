"""HDRezka user reviews scraper + Telegram comments poster."""
import json
import re

import httpx
import structlog
from bs4 import BeautifulSoup

from movie_recommender.core.config import settings

logger = structlog.get_logger()

REZKA_SEARCH = "https://rezka.ag/search/?do=search&subaction=search&q={query}"
REZKA_COMMENTS = "https://rezka.ag/ajax/get_comments/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


async def fetch_rezka_reviews(title: str, year: int | None = None, max_reviews: int = 5) -> list[dict]:
    """Search HDRezka for a movie and scrape user reviews via AJAX."""
    query = f"{title} {year}" if year else title

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        # Search for the movie
        resp = await client.get(REZKA_SEARCH.format(query=query))
        if resp.status_code != 200:
            logger.warning("Rezka search failed", status=resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".b-content__inline_item")
        if not items:
            return []

        # Get movie page URL
        link = items[0].select_one("a")
        if not link or not link.get("href"):
            return []

        movie_url = link["href"]

        # Extract news_id from URL (e.g. /82389-grenlandiya...)
        match = re.search(r"/(\d+)-", movie_url)
        if not match:
            return []
        news_id = match.group(1)

        # Visit movie page first (for cookies/session)
        await client.get(movie_url)

        # Load comments via AJAX
        resp = await client.post(
            REZKA_COMMENTS,
            data={"news_id": news_id, "cstart": "1", "type": "0", "comment_id": "0", "skin": "hdrezka"},
            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": movie_url},
        )
        if resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        comments_html = data.get("comments", "")
        if not comments_html:
            return []

        soup = BeautifulSoup(comments_html, "lxml")
        reviews: list[dict] = []

        for block in soup.select("li.comments-tree-item"):
            # Author
            author_el = block.select_one(".comm_author, .nickname a, .name a")
            author = author_el.get_text(strip=True) if author_el else "Аноним"

            # Comment text
            text_el = block.select_one(".comments-tree-text, .text")
            if not text_el:
                continue
            text = text_el.get_text(strip=True)
            if len(text) < 15:
                continue

            # Rating (likes)
            likes_el = block.select_one(".comm_likes_count, .likes-count")
            likes = 0
            if likes_el:
                try:
                    likes = int(likes_el.get_text(strip=True))
                except ValueError:
                    pass

            reviews.append({
                "author": author,
                "text": text[:500],
                "likes": likes,
            })

        # Sort by likes (most popular reviews first)
        reviews.sort(key=lambda x: x.get("likes", 0), reverse=True)
        reviews = reviews[:max_reviews]

        logger.info("Rezka reviews fetched", title=title, count=len(reviews))
        return reviews


async def post_reviews_as_comments(
    message_id: int,
    reviews: list[dict],
    movie_title: str,
) -> int:
    """Post reviews as comments in the Telegram discussion group.

    When a channel post is auto-forwarded to the linked discussion group,
    we reply to that forwarded message so reviews appear as threaded comments.
    """
    if not reviews or not settings.telegram_bot_token:
        return 0

    bot_token = settings.telegram_bot_token
    group_id = settings.telegram_discussion_group_id
    if not group_id:
        logger.warning("No discussion group ID configured, skipping reviews")
        return 0

    posted = 0

    async with httpx.AsyncClient(timeout=15) as client:
        # Find the auto-forwarded message in the discussion group
        # Telegram auto-forwards channel posts to linked groups;
        # the forwarded message has forward_from_message_id == channel message_id
        group_msg_id = await _find_forwarded_message(client, bot_token, group_id, message_id)

        for review in reviews:
            author = review["author"]
            text = review["text"]
            likes = review.get("likes", 0)

            comment_text = f"\U0001f4ac <b>{author}</b>"
            if likes > 0:
                comment_text += f" (\U0001f44d {likes})"
            comment_text += f"\n\n{text}"
            comment_text += "\n\n<i>\u2014 \u043e\u0442\u0437\u044b\u0432 \u0441 HDRezka</i>"

            payload: dict = {
                "chat_id": group_id,
                "text": comment_text,
                "parse_mode": "HTML",
            }
            if group_msg_id:
                payload["reply_to_message_id"] = group_msg_id

            try:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload,
                )
                result = resp.json()
                if result.get("ok"):
                    posted += 1
                else:
                    logger.warning("TG comment failed", error=result.get("description"))
            except Exception as e:
                logger.warning("Failed to post review comment", error=str(e))

    logger.info("Posted Rezka reviews", title=movie_title, posted=posted, group=group_id)
    return posted


async def _find_forwarded_message(
    client: httpx.AsyncClient,
    bot_token: str,
    group_id: str,
    channel_msg_id: int,
) -> int | None:
    """Find the auto-forwarded channel message in the discussion group.

    Uses getUpdates to look for the forwarded message, or falls back
    to the Telegram trick: discussion group message_id = channel_msg_id + 1
    (works for linked groups where auto-forward is immediate).
    """
    import asyncio

    # Wait a moment for Telegram to auto-forward the channel post
    await asyncio.sleep(2)

    # Try using the Telegram API to get recent messages via getUpdates
    try:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            json={"allowed_updates": ["channel_post", "message"], "limit": 20},
        )
        data = resp.json()
        if data.get("ok"):
            for update in reversed(data.get("result", [])):
                msg = update.get("message", {})
                fwd = msg.get("forward_from_message_id")
                if fwd == channel_msg_id and str(msg.get("chat", {}).get("id")) == str(group_id):
                    logger.info("Found forwarded message", group_msg_id=msg["message_id"])
                    return msg["message_id"]
    except Exception as e:
        logger.debug("getUpdates lookup failed", error=str(e))

    logger.info("Forwarded message not found via getUpdates, posting without reply")
    return None

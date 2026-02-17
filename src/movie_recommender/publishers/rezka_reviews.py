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


async def fetch_rezka_reviews(title: str, year: int | None = None, max_reviews: int = 5) -> tuple[list[dict], str | None]:
    """Search HDRezka for a movie and scrape user reviews via AJAX.

    Returns: (reviews, rezka_url) tuple.
    """
    query = f"{title} {year}" if year else title

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        # Search for the movie
        resp = await client.get(REZKA_SEARCH.format(query=query))
        if resp.status_code != 200:
            logger.warning("Rezka search failed", status=resp.status_code)
            return [], None

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".b-content__inline_item")
        if not items:
            return [], None

        # Get movie page URL
        link = items[0].select_one("a")
        if not link or not link.get("href"):
            return [], None

        movie_url = link["href"]

        # Extract news_id from URL (e.g. /82389-grenlandiya...)
        match = re.search(r"/(\d+)-", movie_url)
        if not match:
            return [], movie_url
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
            return [], movie_url

        try:
            data = resp.json()
        except Exception:
            return [], movie_url

        comments_html = data.get("comments", "")
        if not comments_html:
            return [], movie_url

        soup = BeautifulSoup(comments_html, "lxml")
        reviews: list[dict] = []

        for block in soup.select("li.comments-tree-item"):
            # Author
            author_el = block.select_one(".comm_author, .nickname a, .name a")
            author = author_el.get_text(strip=True) if author_el else "\u0410\u043d\u043e\u043d\u0438\u043c"

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

        logger.info("Rezka reviews fetched", title=title, count=len(reviews), url=movie_url)
        return reviews, movie_url


async def post_reviews_as_comments(
    message_id: int,
    reviews: list[dict],
    movie_title: str,
) -> int:
    """Post reviews as comments in the Telegram discussion group.

    Finds the auto-forwarded message in the group via getUpdates
    (poll loop is paused during pipeline publish), then replies to it.
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
        group_msg_id = await _find_forwarded_message(client, bot_token, group_id, message_id)
        if not group_msg_id:
            logger.warning("Could not find forwarded message, skipping reviews", channel_msg_id=message_id)
            return 0

        for review in reviews:
            author = review["author"]
            text = review["text"]
            likes = review.get("likes", 0)

            comment_text = f"\U0001f4ac <b>{author}</b>"
            if likes > 0:
                comment_text += f" (\U0001f44d {likes})"
            comment_text += f"\n\n<code>{text}</code>"
            comment_text += "\n\n<i>\u2014 \u043e\u0442\u0437\u044b\u0432 \u0441 HDRezka</i>"

            try:
                resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": group_id,
                        "text": comment_text,
                        "parse_mode": "HTML",
                        "reply_to_message_id": group_msg_id,
                    },
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

    Calls getUpdates directly (poll loop is paused) and advances shared offset.
    Also processes any reaction updates encountered along the way.
    """
    import asyncio
    from movie_recommender.publishers.feedback import get_poll_offset, advance_offset, _process_reaction_count

    # Wait for Telegram to auto-forward the channel post to the group
    await asyncio.sleep(3)

    offset = get_poll_offset()

    # Try up to 3 times with short waits
    for attempt in range(3):
        try:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                json={
                    "offset": offset,
                    "limit": 100,
                    "timeout": 3,
                    "allowed_updates": ["message", "message_reaction_count", "channel_post"],
                },
            )
            data = resp.json()
            if not data.get("ok"):
                continue

            found_msg_id = None
            max_offset = offset

            for update in data.get("result", []):
                max_offset = max(max_offset, update["update_id"] + 1)

                # Process reaction updates while we're here
                reaction_count = update.get("message_reaction_count")
                if reaction_count:
                    _process_reaction_count(reaction_count)

                # Look for forwarded message in the group
                msg = update.get("message", {})
                fwd = msg.get("forward_from_message_id")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if fwd == channel_msg_id and chat_id == str(group_id):
                    found_msg_id = msg["message_id"]
                    logger.info("Found forwarded message", group_msg_id=found_msg_id, attempt=attempt)

            if max_offset > offset:
                advance_offset(max_offset)
                offset = max_offset

            if found_msg_id:
                return found_msg_id

        except Exception as e:
            logger.debug("getUpdates failed", error=str(e), attempt=attempt)

        await asyncio.sleep(2)

    logger.warning("Forwarded message not found after 3 attempts", channel_msg_id=channel_msg_id)
    return None

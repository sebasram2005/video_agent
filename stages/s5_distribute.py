"""
Stage 5 — Distribution

Sends the finished video to Telegram with platform-optimized captions
for YouTube Shorts and Facebook Reels, plus a blog post title for
Phase 2 Mediavine arbitrage integration.
"""

import asyncio
import logging
import os
from pathlib import Path

from telegram import Bot

logger = logging.getLogger(__name__)

_YT_BASE_TAGS = [
    "#RedditStories", "#AITA", "#StoryTime", "#RelationshipAdvice",
    "#ForumDrama", "#BestOfReddit", "#RedditDrama", "#Shorts",
]

_FB_BASE_TAGS = [
    "#RedditStories", "#AITA", "#StoryTime", "#RelationshipAdvice",
    "#ForumDrama", "#Reels",
]


def _build_youtube_caption(script_data: dict) -> str:
    hook     = script_data.get("hook_text", "")
    sub      = script_data.get("source_subreddit", "reddit")
    score    = script_data.get("source_score", 0)
    custom   = script_data.get("hashtags", [])
    all_tags = list(dict.fromkeys(_YT_BASE_TAGS + custom))[:15]

    return (
        f"{hook}\n\n"
        f"r/{sub} • ⬆️ {score:,} upvotes\n\n"
        f"🔥 Full story + update at the link in bio!\n"
        f"💬 Drop your verdict below 👇\n\n"
        + " ".join(all_tags)
    )


def _build_facebook_caption(script_data: dict) -> str:
    hook     = script_data.get("hook_text", "")
    cta      = script_data.get("cta", "Read the full story at the link in my bio.")
    sub      = script_data.get("source_subreddit", "reddit")
    custom   = script_data.get("hashtags", [])
    all_tags = list(dict.fromkeys(_FB_BASE_TAGS + custom))[:10]

    return (
        f"{hook}\n\n"
        f"r/{sub} story 👇\n\n"
        f"{cta}\n\n"
        + " ".join(all_tags)
    )


async def _send(video_path: Path, script_data: dict) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        return False

    bot        = Bot(token=bot_token)
    sub        = script_data.get("source_subreddit", "reddit")
    score      = script_data.get("source_score", 0)
    blog_title = script_data.get("blog_title", "")
    source_url = script_data.get("source_url", "")
    yt_caption = _build_youtube_caption(script_data)
    fb_caption = _build_facebook_caption(script_data)

    try:
        # 1. Send the video
        with open(video_path, "rb") as vf:
            await bot.send_video(
                chat_id=chat_id,
                video=vf,
                caption=f"r/{sub}  ⬆️ {score:,}  |  {script_data.get('hook_text', '')[:80]}",
                supports_streaming=True,
                width=1080,
                height=1920,
            )

        # 2. Send captions + metadata as a plain text block for easy copy-paste
        SEP = "─" * 42
        message = (
            f"📱 YOUTUBE SHORTS:\n{yt_caption}\n\n"
            f"{SEP}\n\n"
            f"📘 FACEBOOK REELS:\n{fb_caption}\n\n"
            f"{SEP}\n\n"
            f"📝 BLOG TITLE (Phase 2 — Mediavine):\n{blog_title}\n\n"
            f"🔗 SOURCE: {source_url}"
        )
        await bot.send_message(chat_id=chat_id, text=message)

        logger.info(f"Telegram: delivered {video_path.name}")
        return True

    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def distribute_video(video_path: Path, script_data: dict) -> bool:
    return asyncio.run(_send(video_path, script_data))

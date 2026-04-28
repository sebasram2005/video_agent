"""
Stage 0 — Reddit Story Fetcher

Scrapes top/hot posts from high-engagement subreddits using Reddit's
public JSON API (no API key required). Filters by score, word count,
and deduplication against the stories log.
"""

import json
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config import (
    OUTPUT_DIR, SOURCE_SUBREDDITS,
    MIN_STORY_SCORE, MIN_STORY_WORDS, MAX_STORY_WORDS,
)

logger = logging.getLogger(__name__)

STORIES_LOG      = OUTPUT_DIR / "stories_log.json"
DEDUP_WINDOW_DAYS = 60

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StoryNarratorBot/1.0; +https://reddit.com)"
}


# ── Deduplication log ─────────────────────────────────────────────────────────

def _load_used_ids() -> set:
    if not STORIES_LOG.exists():
        return set()
    try:
        data  = json.loads(STORIES_LOG.read_text(encoding="utf-8"))
        cutoff = datetime.now() - timedelta(days=DEDUP_WINDOW_DAYS)
        return {
            e["post_id"] for e in data
            if datetime.fromisoformat(e["date"]) > cutoff
        }
    except Exception:
        return set()


def record_story(post_id: str, subreddit: str, title: str) -> None:
    data: list = []
    if STORIES_LOG.exists():
        try:
            data = json.loads(STORIES_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.append({
        "date":      datetime.now().isoformat(),
        "post_id":   post_id,
        "subreddit": subreddit,
        "title":     title[:120],
    })
    STORIES_LOG.parent.mkdir(parents=True, exist_ok=True)
    STORIES_LOG.write_text(json.dumps(data[-300:], indent=2), encoding="utf-8")


# ── Reddit API ────────────────────────────────────────────────────────────────

def _fetch_subreddit(
    subreddit: str,
    sort: str = "hot",
    time_filter: str = "week",
    limit: int = 25,
) -> list[dict]:
    url    = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": limit, "t": time_filter, "raw_json": 1}
    try:
        r = requests.get(url, headers=_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        posts = r.json()["data"]["children"]
        return [p["data"] for p in posts]
    except Exception as e:
        logger.warning(f"Reddit fetch failed for r/{subreddit} ({sort}): {e}")
        return []


def _word_count(text: str) -> int:
    return len(text.split())


def _clean_text(text: str) -> str:
    """Remove Reddit formatting artifacts."""
    import re
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)   # bold
    text = re.sub(r"\*(.*?)\*",     r"\1", text)    # italic
    text = re.sub(r"~~(.*?)~~",     r"\1", text)    # strikethrough
    text = re.sub(r"&gt;.*?\n",     "",    text)     # block quotes
    text = re.sub(r"\n{3,}",        "\n\n", text)   # excess newlines
    text = text.replace("&#x200B;", "").strip()
    return text


def _is_suitable(post: dict, used_ids: set) -> bool:
    if post.get("id") in used_ids:
        return False
    if not post.get("is_self", False):
        return False
    if post.get("score", 0) < MIN_STORY_SCORE:
        return False
    if post.get("over_18", False):
        return False

    text = post.get("selftext", "").strip()
    if not text or text in ("[deleted]", "[removed]", ""):
        return False

    wc = _word_count(text)
    if not (MIN_STORY_WORDS <= wc <= MAX_STORY_WORDS):
        return False

    return True


# ── Retention scoring ─────────────────────────────────────────────────────────

def _retention_score(post: dict) -> float:
    """Multi-factor score: CPC alignment + emotional arc + controversy + word count."""
    import math

    score     = post.get("score", 0)
    comments  = max(post.get("num_comments", 1), 2)
    text      = post.get("selftext", "").lower()
    wc        = len(text.split())
    subreddit = post.get("subreddit", "")

    base             = score * math.log(comments)
    controversy_mult = 1.0 + min((comments / max(score, 1)) * 2.0, 1.0)

    if 400 <= wc <= 800:
        wc_mult = 1.40
    elif 300 <= wc < 400 or 800 < wc <= 1000:
        wc_mult = 1.15
    else:
        wc_mult = 0.80

    EMOTIONAL = [
        "betrayed", "cheated", "affair", "divorce", "fired", "wrongful",
        "lawsuit", "revenge", "karma", "exposed", "inheritance", "lied",
        "secret", "discovered", "found out", "confronted", "blocked",
        "cut off", "no contact", "destroyed", "ruined", "quit", "resigned",
        "backstabbed", "humiliated", "apology", "justice",
    ]
    emotional_mult = 1.0 + min(sum(1 for kw in EMOTIONAL if kw in text) * 0.04, 0.45)

    LEGAL_KW   = ["lawsuit", "sued", "attorney", "wrongful termination", "fired",
                  "discrimination", "harassment", "settlement", "legal", "lawyer"]
    FINANCE_KW = ["divorce", "inheritance", "will", "assets", "mortgage",
                  "bankruptcy", "alimony", "child support", "estate", "money"]
    TECH_KW    = ["server", "data breach", "ransomware", "sysadmin",
                  "tech company", "startup", "remote work", "developer"]
    cpc_mult = 1.0 + min(
        sum(1 for kw in LEGAL_KW   if kw in text) * 0.07 +
        sum(1 for kw in FINANCE_KW if kw in text) * 0.05 +
        sum(1 for kw in TECH_KW    if kw in text) * 0.04,
        0.55,
    )

    SUB_WEIGHTS = {
        "ProRevenge": 1.50, "NuclearRevenge": 1.45, "MaliciousCompliance": 1.40,
        "legaladvice": 1.35, "TalesFromTechSupport": 1.30,
        "survivinginfidelity": 1.25, "AmItheAsshole": 1.15, "AITAH": 1.15,
        "relationship_advice": 1.05, "BestofRedditorUpdates": 1.00,
        "TrueOffMyChest": 0.90, "tifu": 0.85, "entitledparents": 0.80,
        "offmychest": 0.80, "confessions": 0.70,
    }
    sub_mult = SUB_WEIGHTS.get(subreddit, 1.0)

    return base * controversy_mult * wc_mult * emotional_mult * cpc_mult * sub_mult


# ── Public interface ──────────────────────────────────────────────────────────

def fetch_story(subreddit_hint: str = None) -> dict | None:
    """
    Fetch one suitable story, preferring subreddit_hint if provided.
    Automatically falls back to other SOURCE_SUBREDDITS if needed.

    Returns dict: {id, subreddit, title, text, score, url, word_count}
    or None if no suitable story found.
    """
    used = _load_used_ids()

    if subreddit_hint and subreddit_hint in SOURCE_SUBREDDITS:
        subs_to_try = [subreddit_hint] + [
            s for s in random.sample(SOURCE_SUBREDDITS, len(SOURCE_SUBREDDITS))
            if s != subreddit_hint
        ]
    else:
        subs_to_try = random.sample(SOURCE_SUBREDDITS, len(SOURCE_SUBREDDITS))

    for sub in subs_to_try:
        logger.info(f"Fetching from r/{sub}...")

        # Try hot first, fall back to top/week
        posts = _fetch_subreddit(sub, sort="hot", limit=25)
        if not posts:
            time.sleep(1)
            posts = _fetch_subreddit(sub, sort="top", time_filter="week", limit=25)

        for p in posts:
            p["subreddit"] = sub
        suitable = [p for p in posts if _is_suitable(p, used)]
        if not suitable:
            logger.debug(f"r/{sub}: no suitable posts (filtered {len(posts)} total)")
            continue

        # Pick best post by multi-factor retention score
        post = max(suitable, key=_retention_score)
        text = _clean_text(post.get("selftext", ""))

        result = {
            "id":         post["id"],
            "subreddit":  sub,
            "title":      post.get("title", ""),
            "text":       text,
            "score":      post.get("score", 0),
            "url":        f"https://www.reddit.com{post.get('permalink', '')}",
            "word_count": _word_count(text),
        }

        logger.info(
            f"Story selected: r/{sub} | score: {result['score']:,} | "
            f"{result['word_count']} words | {result['title'][:70]}"
        )
        return result

    logger.error("No suitable stories found across all subreddits")
    return None

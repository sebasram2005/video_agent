#!/usr/bin/env python3
"""
curator.py — La Trampa Narrativa: Interactive Story Curator

Workflow:
  1. Fetches top posts from high-engagement subreddits
  2. Filters: 10K+ upvotes, 500+ comments, text-only, 300-3000 words
  3. Displays top 5 ranked by engagement score
  4. You pick one and read it
  5. You set the cliffhanger split point (paragraph number)
  6. Saves output/curated/selected_story.json for mvp_run.py

Usage:
  python curator.py
  python curator.py --subreddit AITA
  python curator.py --sort top --time month
"""

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import requests

from config import ACCOUNT_A_SUBREDDITS, ACCOUNT_B_SUBREDDITS, SOURCE_SUBREDDITS

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR   = Path(__file__).parent / "output"
CURATED_DIR  = OUTPUT_DIR / "curated"
STORIES_LOG  = Path(__file__).parent / "data" / "stories_log.json"

TARGET_SUBREDDITS = SOURCE_SUBREDDITS

MIN_UPVOTES  = 10_000
MIN_COMMENTS = 500
MIN_WORDS    = 300
MAX_WORDS    = 3_000

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CuratorBot/1.0)"
}


# ── Reddit fetcher ────────────────────────────────────────────────────────────

def _fetch(subreddit: str, sort: str, time_filter: str, limit: int = 50) -> list[dict]:
    url    = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": limit, "t": time_filter, "raw_json": 1}
    try:
        r = requests.get(url, headers=_HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return [p["data"] for p in r.json()["data"]["children"]]
    except Exception as e:
        print(f"  [warn] r/{subreddit}: {e}")
        return []


def _clean(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*",     r"\1", text)
    text = re.sub(r"&gt;[^\n]*\n",  "",    text)
    text = re.sub(r"\n{3,}",        "\n\n", text)
    return text.replace("&#x200B;", "").strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


# Words that trigger YouTube age-restriction on titles — keep content platform-safe
_EXPLICIT_TITLE_WORDS = {
    "fuck", "fucked", "fucking", "fucker", "shit", "shitted", "bullshit",
    "ass", "asshole", "bitch", "bastard", "cunt", "dick", "pussy", "cock",
    "whore", "slut", "rape", "raped", "porn", "sex", "nude", "naked",
    "masturbat", "orgasm", "erect", "penis", "vagina",
}


def _has_explicit_title(post: dict) -> bool:
    title = post.get("title", "").lower()
    return any(word in title.split() or f"{word}," in title or f"{word}." in title
               for word in _EXPLICIT_TITLE_WORDS)


def _is_suitable(post: dict) -> bool:
    if not post.get("is_self"):
        return False
    if post.get("over_18"):
        return False
    if _has_explicit_title(post):
        return False
    text = post.get("selftext", "").strip()
    if not text or text in ("[deleted]", "[removed]"):
        return False
    wc = _word_count(text)
    return (
        post.get("score", 0)          >= MIN_UPVOTES
        and post.get("num_comments", 0) >= MIN_COMMENTS
        and MIN_WORDS <= wc <= MAX_WORDS
    )


def _retention_score(post: dict) -> float:
    """
    Multi-factor retention score.
    Weights: CPC vertical alignment, emotional arc density, controversy ratio,
    word count sweet spot (400-800 words = ideal 60-90s video), subreddit tier.
    """
    import math

    score     = post.get("score", 0)
    comments  = max(post.get("num_comments", 1), 2)
    text      = post.get("selftext", "").lower()
    wc        = len(text.split())
    subreddit = post.get("subreddit", "")

    # 1. Base: upvotes × log(comments)
    base = score * math.log(comments)

    # 2. Controversy: high comment/upvote ratio = debate = engagement
    controversy_mult = 1.0 + min((comments / max(score, 1)) * 2.0, 1.0)

    # 3. Word count sweet spot: 400-800 words → 60-90s video
    if 400 <= wc <= 800:
        wc_mult = 1.40
    elif 300 <= wc < 400 or 800 < wc <= 1000:
        wc_mult = 1.15
    else:
        wc_mult = 0.80

    # 4. Emotional arc keywords (betrayal/revenge → high completion rate)
    EMOTIONAL = [
        "betrayed", "cheated", "affair", "divorce", "fired", "wrongful",
        "lawsuit", "revenge", "karma", "exposed", "inheritance", "lied",
        "secret", "discovered", "found out", "confronted", "blocked",
        "cut off", "no contact", "destroyed", "ruined", "quit", "resigned",
        "backstabbed", "humiliated", "apology", "justice",
    ]
    emotional_hits = sum(1 for kw in EMOTIONAL if kw in text)
    emotional_mult = 1.0 + min(emotional_hits * 0.04, 0.45)

    # 5. High-CPC semantic alignment (ad vertical keywords)
    LEGAL_KW   = ["lawsuit", "sued", "attorney", "wrongful termination", "fired",
                  "discrimination", "harassment", "settlement", "legal", "lawyer"]
    FINANCE_KW = ["divorce", "inheritance", "will", "assets", "mortgage", "debt",
                  "bankruptcy", "alimony", "child support", "estate", "money"]
    TECH_KW    = ["server", "data breach", "ransomware", "it department", "sysadmin",
                  "tech company", "startup", "remote work", "developer", "software"]
    legal_h  = sum(1 for kw in LEGAL_KW   if kw in text)
    fin_h    = sum(1 for kw in FINANCE_KW if kw in text)
    tech_h   = sum(1 for kw in TECH_KW    if kw in text)
    cpc_mult = 1.0 + min(legal_h * 0.07 + fin_h * 0.05 + tech_h * 0.04, 0.55)

    # 6. Subreddit CPC tier
    SUB_WEIGHTS = {
        "ProRevenge":            1.50,
        "NuclearRevenge":        1.45,
        "MaliciousCompliance":   1.40,
        "legaladvice":           1.35,
        "TalesFromTechSupport":  1.30,
        "survivinginfidelity":   1.25,
        "AmItheAsshole":         1.15,
        "AITAH":                 1.15,
        "relationship_advice":   1.05,
        "BestofRedditorUpdates": 1.00,
        "TrueOffMyChest":        0.90,
        "tifu":                  0.85,
        "entitledparents":       0.80,
        "offmychest":            0.80,
        "confessions":           0.70,
    }
    sub_mult = SUB_WEIGHTS.get(subreddit, 1.0)

    return base * controversy_mult * wc_mult * emotional_mult * cpc_mult * sub_mult


# Keep alias for any external callers
_engagement_score = _retention_score


# ── Display helpers ───────────────────────────────────────────────────────────

def _cpc_tier(subreddit: str) -> str:
    TIERS = {
        "ProRevenge": "A+", "NuclearRevenge": "A+", "MaliciousCompliance": "A",
        "legaladvice": "A", "TalesFromTechSupport": "A-",
        "survivinginfidelity": "B+", "AmItheAsshole": "B", "AITAH": "B",
        "relationship_advice": "B", "BestofRedditorUpdates": "B-",
        "TrueOffMyChest": "C+", "tifu": "C", "entitledparents": "C",
        "offmychest": "C", "confessions": "C-",
    }
    return TIERS.get(subreddit, "B")


def _print_story_list(stories: list[dict]) -> None:
    print()
    print("─" * 70)
    print("  TOP STORIES — ranked by retention score (CPC + emotional arc + virality)")
    print("─" * 70)
    for i, s in enumerate(stories, 1):
        text  = _clean(s.get("selftext", ""))
        wc    = _word_count(text)
        title = s.get("title", "")[:60]
        rscore = _retention_score(s)
        tier   = _cpc_tier(s["subreddit"])
        wc_tag = "IDEAL" if 400 <= wc <= 800 else ("SHORT" if wc < 300 else "LONG")
        print(f"\n  [{i}] r/{s['subreddit']}  [CPC:{tier}]")
        print(f"      ⬆ {s['score']:,}  💬 {s['num_comments']:,}  📝 {wc}w [{wc_tag}]  🎯 {rscore:,.0f}")
        print(f"      {title}")
    print()


def _print_paragraphs(paras: list[str]) -> None:
    print()
    print("─" * 66)
    print("  STORY — PARAGRAPH VIEW  (choose your cliffhanger split)")
    print("─" * 66)
    for i, p in enumerate(paras, 1):
        preview = textwrap.shorten(p, width=90, placeholder="...")
        print(f"\n  [P{i:02d}]  {preview}")
    print()


# ── Already-used IDs ──────────────────────────────────────────────────────────

def _used_ids() -> set:
    if not STORIES_LOG.exists():
        return set()
    try:
        data = json.loads(STORIES_LOG.read_text(encoding="utf-8"))
        return {e["post_id"] for e in data}
    except Exception:
        return set()


def _record(post_id: str, subreddit: str, title: str) -> None:
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


# ── Main curation flow ────────────────────────────────────────────────────────

def curate(
    subreddit: str   = None,
    sort: str        = "top",
    time_filter: str = "month",
    account: str     = None,
    auto: bool       = False,
) -> dict | None:
    print("\n" + "=" * 66)
    print("  LA TRAMPA NARRATIVA — Story Curator")
    print("=" * 66)

    # Account-based subreddit filtering
    if subreddit:
        subs = [subreddit]
    elif account == "A":
        subs = ACCOUNT_A_SUBREDDITS
        print("  Account A — Legal/Corporate (CPC Tier A+)")
    elif account == "B":
        subs = ACCOUNT_B_SUBREDDITS
        print("  Account B — Relationship/Family (CPC Tier B)")
    else:
        subs = TARGET_SUBREDDITS

    used   = _used_ids()
    found  : list[dict] = []

    print(f"\nFetching ({sort}/{time_filter}) from {len(subs)} subreddit(s)...\n")

    for sub in subs:
        posts = _fetch(sub, sort, time_filter, limit=50)
        for p in posts:
            p["subreddit"] = sub
            if _is_suitable(p) and p["id"] not in used:
                found.append(p)
        if len(found) >= 20:
            break

    if not found:
        print(
            "  No stories found matching filters.\n"
            "  Try: --sort top --time all  or lower --min-upvotes"
        )
        return None

    # Rank by multi-factor retention score
    found.sort(key=_retention_score, reverse=True)
    top5 = found[:5]

    _print_story_list(top5)

    # ── Story selection ────────────────────────────────────────────────────────
    if auto:
        post  = top5[0]
        text  = _clean(post.get("selftext", ""))
        paras = _paragraphs(text)
        total = len(paras)
        split = max(1, int(total * 0.70))
        print(f"  [AUTO] Selected #1: r/{post['subreddit']}  ⬆️  {post['score']:,}")
        print(f"  {total} paragraphs | split at P{split} (70%)\n")
    else:
        while True:
            try:
                choice = int(input("  Select story [1-5]: ").strip())
                if 1 <= choice <= len(top5):
                    break
            except (ValueError, EOFError):
                pass
            print("  Enter a number between 1 and 5.")

        post  = top5[choice - 1]
        text  = _clean(post.get("selftext", ""))
        paras = _paragraphs(text)
        total = len(paras)

        print(f"\n  Selected: r/{post['subreddit']}  ⬆️  {post['score']:,}")
        print(f"  {total} paragraphs  |  {_word_count(text)} words total\n")

        show = input("  Show full paragraphs? [y/N]: ").strip().lower()
        if show == "y":
            _print_paragraphs(paras)
        else:
            print()
            for i, p in enumerate(paras, 1):
                preview = textwrap.shorten(p, width=80, placeholder="...")
                print(f"  [P{i:02d}]  {preview}")
            print()

        print(f"  Part 1 = everything UP TO the split paragraph (the cliffhanger).")
        print(f"  Part 2 = everything FROM the split paragraph onwards (the resolution).")
        print(f"  Tip: pick where the tension peaks and the reader doesn't know what happens.\n")

        while True:
            try:
                split = int(input(f"  Split at paragraph [1-{total - 1}]: ").strip())
                if 1 <= split < total:
                    break
            except (ValueError, EOFError):
                pass
            print(f"  Enter a number between 1 and {total - 1}.")

        confirm = input("\n  Confirm selection? [Y/n]: ").strip().lower()
        if confirm == "n":
            print("  Cancelled.")
            return None

    part1_paras = paras[:split]
    part2_paras = paras[split:]
    part1_text  = "\n\n".join(part1_paras)
    part2_text  = "\n\n".join(part2_paras)

    print(f"\n  Part 1: {_word_count(part1_text)} words (video narration)")
    print(f"  Part 2: {_word_count(part2_text)} words (landing page)")

    result = {
        "id":          post["id"],
        "subreddit":   post["subreddit"],
        "title":       post["title"],
        "score":       post["score"],
        "num_comments": post["num_comments"],
        "url":         f"https://www.reddit.com{post.get('permalink', '')}",
        "word_count":  _word_count(text),
        "split_at_paragraph": split,
        "total_paragraphs":   total,
        "part1_text":  part1_text,
        "part2_text":  part2_text,
        "full_text":   text,
        "curated_at":  datetime.now().isoformat(),
    }

    # Save
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CURATED_DIR / f"story_{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also save as "latest" for mvp_run.py default
    latest = CURATED_DIR / "latest.json"
    latest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    _record(post["id"], post["subreddit"], post["title"])

    print(f"\n  Saved: {out_path.name}")
    print(f"  Run next:  python mvp_run.py")
    print()
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="La Trampa Narrativa — Interactive Story Curator"
    )
    parser.add_argument("--subreddit", metavar="SUB", help="Target a specific subreddit")
    parser.add_argument("--sort",      default="top", choices=["top", "hot", "new"])
    parser.add_argument("--time",      default="month",
                        choices=["day", "week", "month", "year", "all"],
                        dest="time_filter")
    parser.add_argument("--min-upvotes",  type=int, default=MIN_UPVOTES)
    parser.add_argument("--min-comments", type=int, default=MIN_COMMENTS)
    parser.add_argument("--account", choices=["A", "B"],
                        help=(
                            "Filter subreddits by account niche:\n"
                            "  A → Legal/Corporate (ProRevenge, MaliciousCompliance, legaladvice...)\n"
                            "  B → Relationship/Family (AITA, survivinginfidelity, relationship_advice...)"
                        ))
    parser.add_argument("--auto", action="store_true",
                        help="Non-interactive: auto-pick #1 story, split at 70%%")
    args = parser.parse_args()

    MIN_UPVOTES  = args.min_upvotes
    MIN_COMMENTS = args.min_comments

    curate(
        subreddit=args.subreddit,
        sort=args.sort,
        time_filter=args.time_filter,
        account=args.account,
        auto=args.auto,
    )

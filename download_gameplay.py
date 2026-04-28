#!/usr/bin/env python3
"""
download_gameplay.py — Copyright-free gaming footage downloader

Uses yt-dlp search queries to find and download gameplay footage.
Search-based approach is more reliable than hardcoded video IDs (which go stale).

Usage:
  python download_gameplay.py              # download one clip (random style)
  python download_gameplay.py --style minecraft
  python download_gameplay.py --list       # show local clips
"""

import argparse
import random
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAMEPLAY_DIR = Path(__file__).parent / "assets" / "gameplay"

# Search queries that consistently return free-to-use gameplay footage.
# These are the exact terms content creators use to label copyright-free clips.
SEARCH_QUERIES = {
    "minecraft": [
        "ytsearch1:minecraft parkour gameplay free to use no copyright 2024",
        "ytsearch1:minecraft satisfying gameplay no copyright free",
        "ytsearch1:minecraft gameplay background free to use shorts",
    ],
    "subway_surfers": [
        "ytsearch1:subway surfers gameplay no copyright free to use vertical",
        "ytsearch1:subway surfers gameplay free use content creators",
    ],
    "satisfying": [
        "ytsearch1:satisfying gameplay loop no copyright free to use",
        "ytsearch1:minecraft building satisfying no copyright background",
    ],
}

ALL_QUERIES = [q for queries in SEARCH_QUERIES.values() for q in queries]


def _has_ytdlp() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _existing_clips() -> list[Path]:
    if not GAMEPLAY_DIR.exists():
        return []
    return list(GAMEPLAY_DIR.glob("*.mp4")) + list(GAMEPLAY_DIR.glob("*.webm"))


def _download(query: str) -> Path | None:
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        query,
        # Best quality up to 720p, prefer mp4
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--max-filesize", "300M",
        "--no-check-certificates",
        # Name by video ID so re-runs don't re-download
        "-o", str(GAMEPLAY_DIR / "%(id)s.%(ext)s"),
        "--quiet",
        "--no-warnings",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        return None

    clips = _existing_clips()
    return clips[-1] if clips else None


def get_gameplay_clip(style: str = None) -> Path | None:
    """
    Return a path to a gameplay clip, downloading one if needed.
    Returns None if yt-dlp is unavailable or all downloads fail.
    """
    existing = _existing_clips()
    if existing:
        clip = random.choice(existing)
        print(f"  Using cached gameplay: {clip.name}")
        return clip

    if not _has_ytdlp():
        print("  [warn] yt-dlp not found. Install: pip install yt-dlp")
        return None

    queries = list(SEARCH_QUERIES.get(style, []) if style else []) + random.sample(ALL_QUERIES, len(ALL_QUERIES))
    # Deduplicate while preserving order
    seen = set()
    queries = [q for q in queries if not (q in seen or seen.add(q))]

    for query in queries:
        print(f"  Searching: {query.replace('ytsearch1:', '')}")
        clip = _download(query)
        if clip:
            print(f"  Downloaded: {clip.name}  ({clip.stat().st_size // 1_048_576} MB)")
            return clip

    print("  [warn] All downloads failed — falling back to color background.")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download copyright-free gameplay footage")
    parser.add_argument("--style", choices=list(SEARCH_QUERIES.keys()), default=None)
    parser.add_argument("--list",  action="store_true", help="List local clips and exit")
    parser.add_argument("--force", action="store_true", help="Re-download even if clips exist")
    args = parser.parse_args()

    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        clips = _existing_clips()
        if clips:
            print(f"\nLocal gameplay clips ({len(clips)}):")
            for c in clips:
                print(f"  {c.name}  ({c.stat().st_size // 1_048_576} MB)")
        else:
            print("\nNo clips yet. Run: python download_gameplay.py")
        sys.exit(0)

    if args.force:
        for c in _existing_clips():
            c.unlink()
        print("Cleared existing clips.\n")

    clip = get_gameplay_clip(style=args.style)
    sys.exit(0 if clip else 1)

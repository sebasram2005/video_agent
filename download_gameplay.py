#!/usr/bin/env python3
"""
download_gameplay.py — Copyright-free gaming footage downloader

Priority:
  1. Local cached clips in assets/gameplay/
  2. Cloudflare R2 pool (if R2_PUBLIC_URL is set) — used in GitHub Actions
  3. yt-dlp live search — fallback for local dev without R2

Usage:
  python download_gameplay.py              # download one clip (random style)
  python download_gameplay.py --style minecraft
  python download_gameplay.py --list       # show local clips
"""

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAMEPLAY_DIR = Path(__file__).parent / "assets" / "gameplay"

# Fallback yt-dlp queries (local dev only)
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


# ── R2 pool ───────────────────────────────────────────────────────────────────

def _fetch_r2_manifest(public_url: str) -> list[dict] | None:
    """Fetch manifest.json from R2 and return list of clip dicts."""
    import requests as _requests
    url = f"{public_url.rstrip('/')}/manifest.json"
    try:
        r = _requests.get(url, timeout=15)
        r.raise_for_status()
        clips = r.json().get("clips", [])
        if clips:
            return clips
    except Exception as e:
        print(f"  [R2] Could not fetch manifest: {e}")
    return None


def _download_from_r2(clip: dict) -> Path | None:
    """Download a single clip from R2 to GAMEPLAY_DIR."""
    import requests as _requests
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)
    dest = GAMEPLAY_DIR / clip["name"]

    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest  # already cached locally

    url = clip["url"]
    print(f"  [R2] Downloading {clip['name']} ...", end=" ", flush=True)
    try:
        with _requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
        size_mb = dest.stat().st_size / 1_048_576
        print(f"{size_mb:.1f} MB  OK")
        return dest
    except Exception as e:
        print(f"FAILED: {e}")
        if dest.exists():
            dest.unlink()
        return None


def _get_clip_from_r2(style: str | None = None) -> Path | None:
    """Pick a random clip from R2 pool, optionally filtered by style."""
    public_url = os.getenv("R2_PUBLIC_URL", "").strip()
    if not public_url:
        return None

    clips = _fetch_r2_manifest(public_url)
    if not clips:
        return None

    if style:
        filtered = [c for c in clips if c.get("style") == style]
        if filtered:
            clips = filtered

    # Avoid repeating locally-cached clip from last run by preferring
    # clips not already in GAMEPLAY_DIR (keeps variety in Actions runs).
    local_names = {p.name for p in _existing_clips()}
    fresh = [c for c in clips if c["name"] not in local_names]
    pool  = fresh if fresh else clips

    chosen = random.choice(pool)
    print(f"  [R2] Selected: {chosen['name']}  (style: {chosen['style']})")
    return _download_from_r2(chosen)


# ── yt-dlp fallback ───────────────────────────────────────────────────────────

def _download_ytdlp(query: str) -> Path | None:
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        query,
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--max-filesize", "300M",
        "--no-check-certificates",
        "-o", str(GAMEPLAY_DIR / "%(id)s.%(ext)s"),
        "--quiet",
        "--no-warnings",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return None

    clips = _existing_clips()
    return clips[-1] if clips else None


# ── Public API ────────────────────────────────────────────────────────────────

def get_gameplay_clip(style: str = None) -> Path | None:
    """
    Return a path to a gameplay clip.

    Priority:
      1. Local cached clips (assets/gameplay/) — instant
      2. Cloudflare R2 pool via R2_PUBLIC_URL — ~5s download, infinite variety
      3. yt-dlp live search — 60-90s, last resort
    """
    # 1. Local cache
    existing = _existing_clips()
    if existing:
        # In CI each run is a fresh VM, so "existing" means we just downloaded
        # this run — keep it to avoid re-downloading. Locally, rotate randomly.
        clip = random.choice(existing)
        print(f"  Using cached gameplay: {clip.name}")
        return clip

    # 2. R2 pool
    clip = _get_clip_from_r2(style)
    if clip:
        return clip

    # 3. yt-dlp fallback
    if not _has_ytdlp():
        print("  [warn] yt-dlp not found and no R2_PUBLIC_URL set.")
        return None

    queries = list(SEARCH_QUERIES.get(style, []) if style else []) + random.sample(ALL_QUERIES, len(ALL_QUERIES))
    seen: set[str] = set()
    queries = [q for q in queries if not (q in seen or seen.add(q))]

    for query in queries:
        print(f"  Searching: {query.replace('ytsearch1:', '')}")
        clip = _download_ytdlp(query)
        if clip:
            print(f"  Downloaded: {clip.name}  ({clip.stat().st_size // 1_048_576} MB)")
            return clip

    print("  [warn] All sources failed — falling back to color background.")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download copyright-free gameplay footage")
    parser.add_argument("--style", choices=list(SEARCH_QUERIES.keys()), default=None)
    parser.add_argument("--list",  action="store_true", help="List local clips and exit")
    parser.add_argument("--force", action="store_true", help="Clear cache and re-download")
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

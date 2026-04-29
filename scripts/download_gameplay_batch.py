#!/usr/bin/env python3
"""
download_gameplay_batch.py — Build a large local pool of copyright-free gameplay clips.

Run this ONCE locally, then upload to R2 with upload_to_r2.py.

Usage:
  python scripts/download_gameplay_batch.py                     # all styles, 5 each
  python scripts/download_gameplay_batch.py --style minecraft   # only minecraft
  python scripts/download_gameplay_batch.py --per-style 10      # 10 per style
  python scripts/download_gameplay_batch.py --list              # show downloaded clips
"""

import argparse
import random
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAMEPLAY_DIR = Path(__file__).parent.parent / "assets" / "gameplay"

# Queries that consistently find clips explicitly labeled "free to use / no copyright".
# ytsearch{N}: pulls N results per query — we stop at first successful download per query.
BATCH_QUERIES: dict[str, list[str]] = {
    "minecraft": [
        "ytsearch5:minecraft parkour gameplay no copyright free to use 2024",
        "ytsearch5:minecraft parkour background footage free use content creators",
        "ytsearch5:minecraft gameplay loop no copyright shorts background",
        "ytsearch5:minecraft satisfying builds no copyright free background",
        "ytsearch5:minecraft night parkour free use vertical shorts",
        "ytsearch5:minecraft speedrun gameplay no copyright background",
        "ytsearch5:minecraft cave parkour no copyright free footage",
        "ytsearch5:minecraft smooth parkour free to use gameplay",
        "ytsearch5:minecraft sky parkour no copyright 1080p background",
        "ytsearch5:minecraft dropper gameplay no copyright free use",
    ],
    "subway_surfers": [
        "ytsearch5:subway surfers gameplay no copyright free to use vertical",
        "ytsearch5:subway surfers free gameplay background content creators",
        "ytsearch5:subway surfers no copyright 2024 gameplay footage shorts",
        "ytsearch5:subway surfers gameplay background no copyright 1080p",
        "ytsearch5:subway surfers free use gameplay loop background",
        "ytsearch5:subway surfers gameplay vertical free to use creators",
    ],
    "geometry_dash": [
        "ytsearch5:geometry dash gameplay no copyright free to use background",
        "ytsearch5:geometry dash free background footage no copyright shorts",
        "ytsearch5:geometry dash gameplay loop no copyright creators",
        "ytsearch5:geometry dash noclip gameplay free background",
    ],
    "temple_run": [
        "ytsearch5:temple run gameplay no copyright free to use background",
        "ytsearch5:temple run 2 gameplay no copyright free background shorts",
        "ytsearch5:temple run free use gameplay footage vertical",
    ],
    "among_us": [
        "ytsearch5:among us gameplay no copyright free to use background",
        "ytsearch5:among us free gameplay background content creators shorts",
        "ytsearch5:among us gameplay loop no copyright footage",
    ],
    "satisfying": [
        "ytsearch5:satisfying minecraft building no copyright free background",
        "ytsearch5:satisfying gameplay loop no copyright free to use",
        "ytsearch5:kinetic sand asmr no copyright free background footage",
        "ytsearch5:satisfying cutting compilation no copyright free use",
        "ytsearch5:marble run no copyright free background footage",
        "ytsearch5:sand art satisfying no copyright free to use",
    ],
    "fall_guys": [
        "ytsearch5:fall guys gameplay no copyright free to use background",
        "ytsearch5:fall guys free gameplay footage no copyright shorts",
    ],
    "angry_birds": [
        "ytsearch5:angry birds gameplay no copyright free to use background",
        "ytsearch5:angry birds 2 gameplay no copyright free footage",
    ],
}

ALL_STYLES = list(BATCH_QUERIES.keys())


def _has_ytdlp() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _existing_clips(style: str | None = None) -> list[Path]:
    if not GAMEPLAY_DIR.exists():
        return []
    all_clips = list(GAMEPLAY_DIR.glob("*.mp4")) + list(GAMEPLAY_DIR.glob("*.webm"))
    if style:
        all_clips = [c for c in all_clips if c.stem.startswith(style)]
    return sorted(all_clips)


def _download_one(query: str, style: str, index: int) -> Path | None:
    """Download one clip matching the query, save as {style}_{index:03d}.mp4."""
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)
    out_template = str(GAMEPLAY_DIR / f"{style}_{index:03d}.%(ext)s")

    cmd = [
        "yt-dlp",
        query,
        "-f", (
            "bestvideo[height<=720][height>=480][ext=mp4]+"
            "bestaudio[ext=m4a]/"
            "best[height<=720][height>=480][ext=mp4]/"
            "best[height<=720][ext=mp4]"
        ),
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--max-filesize", "200M",
        "--min-filesize", "5M",      # skip tiny/corrupt clips
        "--no-check-certificates",
        "-o", out_template,
        "--quiet",
        "--no-warnings",
        "--socket-timeout", "30",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    out_path = GAMEPLAY_DIR / f"{style}_{index:03d}.mp4"
    if result.returncode == 0 and out_path.exists():
        return out_path
    return None


def download_style(style: str, target: int, start_index: int = 1) -> list[Path]:
    queries = BATCH_QUERIES.get(style, [])
    if not queries:
        print(f"  Unknown style: {style}")
        return []

    random.shuffle(queries)
    downloaded: list[Path] = []
    idx = start_index

    for query in queries:
        if len(downloaded) >= target:
            break
        label = query.replace("ytsearch5:", "").strip()
        print(f"  [{style}] Searching: {label[:70]}")
        clip = _download_one(query, style, idx)
        if clip:
            size_mb = clip.stat().st_size / 1_048_576
            print(f"  [{style}] Got: {clip.name}  ({size_mb:.1f} MB)")
            downloaded.append(clip)
            idx += 1
        else:
            print(f"  [{style}] No result — trying next query")

    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Download gameplay clip pool")
    parser.add_argument("--style",     choices=ALL_STYLES + ["all"], default="all",
                        help="Style to download (default: all)")
    parser.add_argument("--per-style", type=int, default=5,
                        help="Target clips per style (default: 5)")
    parser.add_argument("--list",      action="store_true",
                        help="List downloaded clips and exit")
    args = parser.parse_args()

    if args.list:
        clips = _existing_clips()
        if not clips:
            print("\nNo clips yet. Run without --list to download.")
            return
        by_style: dict[str, list[Path]] = {}
        for c in clips:
            s = c.stem.split("_")[0]
            by_style.setdefault(s, []).append(c)
        total_mb = sum(c.stat().st_size for c in clips) / 1_048_576
        print(f"\nLocal gameplay pool: {len(clips)} clips  ({total_mb:.0f} MB total)\n")
        for s, cs in sorted(by_style.items()):
            print(f"  {s}: {len(cs)} clips")
        return

    if not _has_ytdlp():
        print("ERROR: yt-dlp not found. Install: pip install yt-dlp")
        sys.exit(1)

    styles = ALL_STYLES if args.style == "all" else [args.style]
    total_downloaded = 0

    for style in styles:
        existing = _existing_clips(style)
        already = len(existing)
        need = max(0, args.per_style - already)
        if need == 0:
            print(f"\n[{style}] Already have {already} clips — skipping")
            continue
        start_idx = already + 1
        print(f"\n{'─'*50}")
        print(f"[{style}] Have {already}, downloading {need} more (starting at #{start_idx})")
        print(f"{'─'*50}")
        got = download_style(style, need, start_idx)
        total_downloaded += len(got)
        print(f"[{style}] Done: {len(got)}/{need} downloaded")

    clips = _existing_clips()
    total_mb = sum(c.stat().st_size for c in clips) / 1_048_576
    print(f"\n{'='*50}")
    print(f"Pool: {len(clips)} clips total  ({total_mb:.0f} MB)")
    print(f"Next step: python scripts/upload_to_r2.py")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()

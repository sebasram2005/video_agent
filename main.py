#!/usr/bin/env python3
"""
Reddit Stories Bot — Automated Short Video Generator

Pipeline: Reddit story → English script → TTS → Pexels visuals → FFmpeg → Telegram

Target: YouTube Shorts + Facebook Reels (Tier-1 English markets)
Model:  Sniper accounts (1-2 brands), cliffhanger → blog (Mediavine Phase 2)
Limit:  <1 hour/day human intervention
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import ASSETS_DIR, MUSIC_DIR, OUTPUT_DIR, TEMP_DIR
from content_calendar import (
    load_calendar, save_calendar, generate_calendar,
    get_next_pending, mark_generated, print_calendar_summary,
)
from stages.s0_reddit import fetch_story, record_story
from stages.s1_script import generate_script, build_full_narration
from stages.s2_tts    import generate_tts
from stages.s3_visuals import collect_visual_assets
from stages.s4_compose import compose_video
from stages.s5_distribute import distribute_video
from stages.s6_blog_draft import generate_blog_draft

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── System checks ─────────────────────────────────────────────────────────────

def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _system_check() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n=== Reddit Stories Bot — System Check ===\n")

    ok   = "  [OK]"
    warn = "  [!!]"
    opt  = "  [ ]"

    ffmpeg = _has_ffmpeg()
    print(f"{'  [OK]' if ffmpeg else warn}  FFmpeg"
          + ("" if ffmpeg else "  <- Install: winget install ffmpeg"))

    for key, label, required in [
        ("OPENAI_API_KEY",      "OpenAI API key",       True),
        ("TELEGRAM_BOT_TOKEN",  "Telegram bot token",   True),
        ("TELEGRAM_CHAT_ID",    "Telegram chat ID",     True),
        ("PEXELS_API_KEY",      "Pexels API key",       False),
        ("ELEVENLABS_API_KEY",  "ElevenLabs API key",   False),
        ("ELEVENLABS_VOICE_ID", "ElevenLabs Voice ID",  False),
        ("RUNWARE_API_KEY",     "Runware API key",       False),
        ("BLOG_URL",            "Blog URL (Phase 2)",   False),
    ]:
        val    = os.getenv(key, "")
        status = ok if val else (warn if required else opt)
        suffix = "" if val else ("  <- REQUIRED" if required else "  (optional)")
        print(f"{status}  {label}{suffix}")

    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    logo        = os.getenv("BRAND_LOGO_PATH", "")
    brand       = os.getenv("BRAND_NAME", "ForumDrama")

    print(f"\n  Brand name:    {brand}")
    print(f"{'  [OK]' if music_files else opt}  Background music: {len(music_files)} file(s)"
          + ("" if music_files else "  (add MP3s to assets/music/)"))
    print(f"{'  [OK]' if logo else opt}  Brand logo"
          + ("" if logo else "  (add PNG to assets/logo.png)"))
    print()


# ── Directory setup ───────────────────────────────────────────────────────────

def _setup() -> None:
    for d in [OUTPUT_DIR, TEMP_DIR, ASSETS_DIR / "music", ASSETS_DIR / "fonts"]:
        d.mkdir(parents=True, exist_ok=True)


def _clean_temp() -> None:
    for f in TEMP_DIR.glob("*"):
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(
    subreddit_hint: str = None,
    send_telegram: bool = True,
    save_blog_draft: bool = True,
) -> bool:
    t0 = time.time()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("━" * 54)
    logger.info("  REDDIT STORIES BOT")
    logger.info("━" * 54)

    # Stage 0a — Calendar slot
    logger.info("[0/6] Loading calendar...")
    calendar = load_calendar()
    if not calendar:
        logger.info("  No calendar found — generating 30-day plan...")
        calendar = generate_calendar(30, videos_per_day=2)
        save_calendar(calendar)

    slot = get_next_pending(calendar)
    if slot:
        logger.info(
            f"  Slot #{slot['id']} | {slot['date']} {slot['post_time']} | "
            f"{slot['category']} | r/{slot['subreddit_hint']}"
        )
        if subreddit_hint is None:
            subreddit_hint = slot.get("subreddit_hint")

    # Stage 0b — Fetch Reddit story
    logger.info("[0/6] Fetching Reddit story...")
    story = fetch_story(subreddit_hint)
    if not story:
        logger.error("Could not find a suitable story — aborting.")
        return False

    # Stage 1 — Script
    logger.info("[1/6] Generating English script with cliffhanger...")
    try:
        script = generate_script(story)
        record_story(story["id"], story["subreddit"], story["title"])
    except Exception as e:
        logger.error(f"Stage 1 failed: {e}")
        return False

    # Stage 2 — TTS
    logger.info("[2/6] Generating English voiceover...")
    full_text  = build_full_narration(script)
    audio_path = TEMP_DIR / f"voice_{ts}.mp3"
    try:
        audio_path, word_ts = generate_tts(full_text, audio_path)
    except Exception as e:
        logger.error(f"Stage 2 failed: {e}")
        return False

    # Stage 3 — Visuals
    logger.info("[3/6] Collecting Pexels visuals...")
    try:
        assets = collect_visual_assets(script.get("pexels_queries", []))
    except Exception as e:
        logger.warning(f"Stage 3 partial failure: {e}")
        assets = {"hook": None, "broll": []}

    # Stage 4 — Compose
    logger.info("[4/6] Composing video...")
    output = OUTPUT_DIR / f"reddit_story_{ts}.mp4"
    try:
        ok = compose_video(audio_path, word_ts, assets, script, output)
    except Exception as e:
        logger.error(f"Stage 4 failed: {e}")
        return False
    if not ok:
        return False

    # Update calendar
    if slot:
        mark_generated(calendar, slot["id"], str(output))
        save_calendar(calendar)
        remaining = sum(1 for s in calendar if s["status"] == "pending")
        logger.info(f"  Calendar: slot #{slot['id']} done | {remaining} pending")

    # Stage 5 — Distribute
    if send_telegram:
        logger.info("[5/6] Sending to Telegram...")
        try:
            distribute_video(output, script)
        except Exception as e:
            logger.error(f"Stage 5 failed: {e}")
            logger.info(f"  Video saved locally: {output}")
    else:
        logger.info(f"[5/6] Telegram skipped. Output: {output}")

    # Stage 6 — Blog draft (Phase 2 placeholder)
    if save_blog_draft:
        logger.info("[6/6] Saving blog draft (Phase 2 placeholder)...")
        try:
            generate_blog_draft(story, script)
        except Exception as e:
            logger.warning(f"Stage 6 skipped: {e}")
    else:
        logger.info("[6/6] Blog draft skipped.")

    elapsed = time.time() - t0
    logger.info("━" * 54)
    logger.info(f"  Done in {elapsed:.1f}s  →  {output.name}")
    logger.info(f"  r/{story['subreddit']} | {story['score']:,} upvotes")
    logger.info("━" * 54)

    _clean_temp()
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reddit Stories Bot — Automated Short Video Generator",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--subreddit",
        metavar="SUB",
        help=(
            "Override subreddit hint (default: from calendar rotation):\n"
            "  AITA, relationship_advice, ProRevenge, tifu,\n"
            "  entitledparents, MaliciousCompliance, confessions..."
        ),
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Compose video but skip Telegram delivery",
    )
    parser.add_argument(
        "--no-blog-draft",
        action="store_true",
        help="Skip saving blog draft (Phase 2 placeholder)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify all requirements and exit",
    )
    parser.add_argument(
        "--calendar",
        action="store_true",
        help="Show 30-day content calendar and exit",
    )
    parser.add_argument(
        "--new-calendar",
        action="store_true",
        help="Generate a fresh 30-day content calendar",
    )
    parser.add_argument(
        "--videos-per-day",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        metavar="N",
        help=(
            "Videos per day for new calendar (default 2):\n"
            "  1 →  30 videos/month  (new account, soft start)\n"
            "  2 →  60 videos/month  (stable growth)\n"
            "  3 →  90 videos/month  (aggressive — recommended optimum)\n"
            "  4 → 120 videos/month  (maximum)"
        ),
    )
    parser.add_argument(
        "--batch",
        type=int,
        metavar="N",
        help="Generate N videos in sequence (e.g. --batch 7 for a full week)",
    )
    args = parser.parse_args()

    _setup()

    if args.check:
        _system_check()
        return

    if args.calendar:
        cal = load_calendar()
        if not cal:
            cal = generate_calendar(30)
            save_calendar(cal)
        print_calendar_summary(cal, show_days=30)
        return

    if args.new_calendar:
        vpd   = args.videos_per_day
        total = 30 * vpd
        cal   = generate_calendar(30, videos_per_day=vpd)
        save_calendar(cal)
        print_calendar_summary(cal, show_days=14)
        logger.info(f"New 30-day calendar saved: {vpd} videos/day → {total} videos/month.")
        return

    if not _has_ffmpeg():
        logger.error(
            "FFmpeg not found.\n"
            "Install: winget install ffmpeg  (then restart terminal)"
        )
        sys.exit(1)

    if args.batch:
        logger.info(f"Batch mode: generating {args.batch} videos...")
        results = []
        for i in range(args.batch):
            logger.info(f"\n--- Batch {i+1}/{args.batch} ---")
            ok = run_pipeline(
                subreddit_hint=args.subreddit,
                send_telegram=not args.no_telegram,
                save_blog_draft=not args.no_blog_draft,
            )
            results.append(ok)
            if not ok:
                logger.error(f"Batch item {i+1} failed — continuing...")
        done = sum(results)
        logger.info(f"\nBatch complete: {done}/{args.batch} videos generated.")
        sys.exit(0 if done == args.batch else 1)

    success = run_pipeline(
        subreddit_hint=args.subreddit,
        send_telegram=not args.no_telegram,
        save_blog_draft=not args.no_blog_draft,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

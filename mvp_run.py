#!/usr/bin/env python3
"""
mvp_run.py — La Trampa Narrativa: MVP Pipeline Orchestrator

Reads the curated story from curator.py and produces:
  1. video.mp4   — Part 1 narration over gameplay footage + kinetic subtitles
  2. landing/    — index.html with Part 2 (the resolution)

All output goes to:  output/mvp_YYYYMMDD_HHMMSS/

Usage:
  python mvp_run.py                        # uses latest curated story
  python mvp_run.py --story output/curated/story_20260427_120000.json
  python mvp_run.py --no-telegram          # skip Telegram delivery
  python mvp_run.py --style subway_surfers # prefer this gameplay style
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from config               import TEMP_DIR, OUTPUT_DIR, MUSIC_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from stages.s1_script     import generate_script, build_full_narration
from stages.s2_tts        import generate_tts
from stages.s3_visuals    import search_pexels_images, create_ken_burns_background
from stages.s4_compose    import build_ass_subtitles
from stages.s5_distribute import distribute_video
from download_gameplay    import get_gameplay_clip
from generate_landing     import generate


# ── Reddit card overlay ───────────────────────────────────────────────────────

def _generate_reddit_card(story: dict, duration: float = 4.5) -> str | None:
    """
    Generate a semi-transparent Reddit-style title card as PNG.
    Overlaid on the video for the first `duration` seconds.
    Returns path to PNG or None if Pillow unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap
    except ImportError:
        logger.warning("Pillow not installed — skipping Reddit card overlay")
        return None

    # Card dimensions: full width, auto height
    card_w = VIDEO_WIDTH
    pad    = 48
    font_path_candidates = [
        "C:/Windows/Fonts/arialbd.ttf",   # Windows bold Arial
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    font_path = next((p for p in font_path_candidates if Path(p).exists()), None)

    try:
        font_sub   = ImageFont.truetype(font_path, 38) if font_path else ImageFont.load_default()
        font_title = ImageFont.truetype(font_path, 48) if font_path else ImageFont.load_default()
        font_score = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()
    except Exception:
        font_sub = font_title = font_score = ImageFont.load_default()

    # Wrap title at ~34 chars per line to fit 1080px
    title_lines = textwrap.wrap(story.get("title", ""), width=34)

    line_h   = 58
    card_h   = pad + 46 + pad // 2 + len(title_lines) * line_h + pad // 2 + 44 + pad
    img      = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    draw     = ImageDraw.Draw(img)

    # Card background: Reddit dark surface with 88% opacity
    draw.rounded_rectangle([0, 0, card_w, card_h], radius=0,
                            fill=(18, 18, 19, 224))

    # Left accent bar
    draw.rectangle([0, 0, 6, card_h], fill=(255, 69, 0, 255))

    y = pad
    # Subreddit + category label
    sub_text = f"r/{story.get('subreddit', 'AskReddit')}"
    draw.text((pad, y), sub_text, font=font_sub, fill=(255, 69, 0, 255))
    y += 46 + pad // 2

    # Title lines
    for line in title_lines:
        draw.text((pad, y), line, font=font_title, fill=(255, 255, 255, 255))
        y += line_h

    y += pad // 2
    # Upvote count
    score_text = f"▲  {story.get('score', 0):,} upvotes"
    draw.text((pad, y), score_text, font=font_score, fill=(180, 180, 180, 230))

    card_path = str(TEMP_DIR / "reddit_card.png")
    img.save(card_path, "PNG")

    # Position: vertically centered, slightly above center (40% from top)
    card_y = int(VIDEO_HEIGHT * 0.38)
    return f"{card_path}|{card_y}|{duration}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _run_ffmpeg(cmd: list[str], label: str = "") -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg [{label}]: {result.stderr[-500:]}")
        return False
    return True


def _setup() -> None:
    for d in [OUTPUT_DIR, TEMP_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _clean_temp() -> None:
    for f in TEMP_DIR.glob("*"):
        if f.is_file():
            try:
                f.unlink()
            except OSError:
                pass


# ── Gameplay preparation ──────────────────────────────────────────────────────

def _prepare_gameplay_bg(clip_path: Path, target_duration: float, ts: str) -> str | None:
    """
    Extract a random segment from a gameplay clip, scale to 9:16, color grade.
    Uses input-seek (-ss before -i) for fast random access — requires a proper
    MP4 with keyframe index. Falls back to output-seek if that fails.
    """
    src_dur   = _probe_duration(str(clip_path)) or 60.0
    max_start = max(0.0, src_dur - target_duration - 5)
    start_sec = random.uniform(0, max_start) if max_start > 0 else 0.0
    dst       = str(TEMP_DIR / f"gameplay_{ts}.mp4")

    # Scale landscape to portrait: scale height to 1920, crop center 1080 wide.
    # -2 ensures width is divisible by 2 (libx264 requirement).
    vf = (
        f"scale=-2:{VIDEO_HEIGHT},"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        "eq=saturation=1.10:brightness=0.01:contrast=1.08"
    )

    # Try fast input-seek first (instantaneous for indexed MP4s)
    ok = _run_ffmpeg([
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}", "-i", str(clip_path),
        "-t", f"{target_duration + 1:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS), "-an",
        dst,
    ], "gameplay_fast_seek")

    if not ok:
        # Fallback: output-seek (slower, decodes from start, but works on any file)
        logger.warning("Fast seek failed — using output seek (slower)...")
        ok = _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-ss", f"{start_sec:.3f}",
            "-t", f"{target_duration + 1:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS), "-an",
            dst,
        ], "gameplay_output_seek")

    if not ok:
        return None

    actual_dur = _probe_duration(dst)
    logger.info(f"Gameplay ready: {actual_dur:.1f}s from {clip_path.name} (start {start_sec:.0f}s)")
    return dst


# ── Ken Burns background from Pexels images ──────────────────────────────────

# Cinematic Pexels search queries per subreddit — portrait orientation,
# emotionally resonant, safe for commercial use.
_KB_QUERIES = {
    "ProRevenge":            ["person victorious dramatic office", "justice served serious"],
    "NuclearRevenge":        ["confrontation dramatic lighting", "person determined powerful"],
    "MaliciousCompliance":   ["office worker smiling secretly", "corporate meeting tense"],
    "legaladvice":           ["courthouse dramatic", "serious person reading document"],
    "TalesFromTechSupport":  ["computer dark room moody", "server room blue lighting"],
    "survivinginfidelity":   ["couple argument emotional", "person alone betrayed sad"],
    "AmItheAsshole":         ["person thinking dramatic", "family conflict serious"],
    "AITAH":                 ["shocked person close up", "emotional confrontation"],
    "relationship_advice":   ["couple conflict emotional", "person reading message shocked"],
    "BestofRedditorUpdates": ["dramatic reveal moment", "person surprised reading"],
    "TrueOffMyChest":        ["person alone contemplating window", "emotional portrait"],
    "tifu":                  ["person embarrassed hiding face", "cringe moment funny"],
    "entitledparents":       ["frustrated adult confrontation", "argument public place"],
    "offmychest":            ["person crying emotional close up", "confession night"],
    "confessions":           ["person shadow dramatic portrait", "secret confession dark"],
}
_KB_FALLBACK = ["dramatic portrait moody lighting", "emotional storytelling cinematic"]


def _prepare_ken_burns_bg(story: dict, target_duration: float) -> str | None:
    """
    Build a Ken Burns background from Pexels portrait images.
    Requires PEXELS_API_KEY. Returns path to composed video or None.
    """
    subreddit = story.get("subreddit", "")
    queries   = _KB_QUERIES.get(subreddit, _KB_FALLBACK)

    all_images: list[str] = []
    for q in queries:
        imgs = search_pexels_images(q, count=2)
        all_images.extend(imgs)
        if len(all_images) >= 4:
            break

    if not all_images:
        return None

    return create_ken_burns_background(all_images, target_duration)


# ── Lean render (bypasses s4_compose clip-trimmer) ────────────────────────────

def _render_with_gameplay(
    bg_clip: str,
    audio_path: Path,
    word_ts: list[dict],
    output_path: Path,
    audio_dur: float,
    reddit_card: str | None = None,
) -> bool:
    """
    Final render: gameplay background + voice + ASS subtitles.
    Bypasses s4_compose._process_clip() which would trim the bg to 5s clips.
    """
    # 1. Write subtitles — skip words spoken during the Reddit card overlay
    # (title is already visible on the card, no need to subtitle it)
    card_end = float(reddit_card.split("|")[2]) if reddit_card else 0.0
    sub_words = [w for w in word_ts if w["start"] >= card_end]
    style_idx   = random.randint(0, 4)
    ass_content = build_ass_subtitles(sub_words, style_idx)
    ass_path    = TEMP_DIR / "subs.ass"
    ass_path.write_text(ass_content, encoding="utf-8")
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")

    # 2. Optional background music
    music_files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    music       = str(random.choice(music_files)) if music_files else None

    # 3. Optional logo watermark
    logo_path = os.getenv("BRAND_LOGO_PATH", "").strip()
    logo = logo_path if logo_path and Path(logo_path).is_file() else None
    default_logo = Path(__file__).parent / "assets" / "logo.png"
    if not logo and default_logo.is_file():
        logo = str(default_logo)

    # 4. Build FFmpeg command
    card_png = card_y = card_dur = None
    if reddit_card:
        parts_card   = reddit_card.split("|")
        card_png     = parts_card[0]
        card_y       = int(parts_card[1])
        card_dur     = float(parts_card[2])

    inputs = ["-i", bg_clip, "-i", str(audio_path)]
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
    if logo:
        inputs += ["-i", logo]
    if card_png:
        inputs += ["-i", card_png]

    music_idx = 2 if music else None
    logo_idx  = (3 if music else 2) if logo else None
    card_idx  = (logo_idx + 1 if logo_idx is not None else (music_idx + 1 if music_idx is not None else 2)) if card_png else None

    # Filter graph
    parts = []
    if music:
        parts.append(
            f"[1:a]volume=1.0[voice];"
            f"[{music_idx}:a]volume=0.06,atrim=duration={audio_dur:.3f}[music];"
            "[voice][music]amix=inputs=2:duration=first[audio]"
        )
        audio_out = "[audio]"
    else:
        audio_out = "1:a"

    parts.append(f"[0:v]ass='{ass_escaped}'[vsub]")

    current_v = "[vsub]"

    # Reddit card overlay — timed to first card_dur seconds
    if card_png and card_idx is not None:
        parts.append(
            f"{current_v}[{card_idx}:v]overlay=0:{card_y}:"
            f"enable='between(t,0,{card_dur})'[vcrd]"
        )
        current_v = "[vcrd]"

    if logo and logo_idx is not None:
        parts.append(
            f"[{logo_idx}:v]scale={VIDEO_WIDTH//7}:-1[logo];"
            f"{current_v}[logo]overlay=W-w-30:H-h-30:format=auto[vout]"
        )
        current_v = "[vout]"

    video_out = current_v

    graph     = ";".join(parts)
    map_args  = ["-map", video_out, "-map", audio_out]

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", graph]
        + map_args
        + [
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-t", f"{audio_dur:.3f}",
            "-r", str(VIDEO_FPS),
            "-movflags", "+faststart",
            str(output_path),
        ]
    )

    ok = _run_ffmpeg(cmd, "final_render")
    if ok:
        size_mb = output_path.stat().st_size / 1_048_576
        logger.info(f"Video ready: {output_path.name} ({size_mb:.1f} MB)")
    return ok


def _render_color_fallback(
    audio_path: Path,
    word_ts: list[dict],
    output_path: Path,
    audio_dur: float,
) -> bool:
    """Solid color background when no gameplay clip is available."""
    from stages.s4_compose import create_fallback_clip, compose_video
    assets = {"hook": None, "broll": []}
    return compose_video(audio_path, word_ts, assets, {}, output_path)


# ── Script metadata ───────────────────────────────────────────────────────────

def _build_script_data(story: dict) -> dict:
    return {
        "hook_text":        story["title"][:80],
        "source_subreddit": story["subreddit"],
        "source_id":        story["id"],
        "source_url":       story.get("url", ""),
        "source_score":     story["score"],
        "source_title":     story["title"],
        "story_category":   "drama",
        "topic_tag":        f"r/{story['subreddit']} story",
        "blog_title":       story["title"],
        "hashtags":         ["#AITA", "#RedditStories", "#StoryTime",
                             "#ForumDrama", "#Shorts", "#Reels"],
        "cta": "Read the FULL story at the link in my bio — link is live NOW.",
    }


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_mvp(
    story_path: Path    = None,
    gameplay_style: str = None,
    send_telegram: bool = True,
) -> bool:
    t0 = time.time()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("━" * 54)
    logger.info("  LA TRAMPA NARRATIVA — MVP Pipeline")
    logger.info("━" * 54)

    _setup()

    # ── Load story ────────────────────────────────────────────────────────
    if story_path is None:
        story_path = OUTPUT_DIR / "curated" / "latest.json"
    if not story_path.exists():
        logger.error(f"Story not found: {story_path}\nRun: python curator.py")
        return False

    story = json.loads(story_path.read_text(encoding="utf-8"))
    logger.info(
        f"Story: r/{story['subreddit']} | ⬆️ {story['score']:,} | "
        f"Part1: {len(story['part1_text'].split())} words"
    )

    run_dir = OUTPUT_DIR / f"mvp_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── Stage 1: Script (GPT-4o) → TTS ───────────────────────────────────────
    logger.info("[1/4] Generating hook + script (GPT-4o)...")
    story_for_script = {**story, "text": story.get("full_text", story.get("part1_text", ""))}
    try:
        script   = generate_script(story_for_script)
        tts_text = build_full_narration(script)
        logger.info(f"  Hook: {script['hook_text']}")
    except Exception as e:
        logger.warning(f"Script generation failed ({e}) — falling back to raw title")
        tts_text = f"{story['title']}. {story['part1_text']} Read the FULL story — link in my bio."
        script   = {}

    logger.info("[1/4] Generating English voiceover...")
    audio_path = TEMP_DIR / f"voice_{ts}.mp3"
    try:
        audio_path, word_ts = generate_tts(tts_text, audio_path)
    except Exception as e:
        logger.error(f"TTS failed: {e}")
        return False

    audio_dur = _probe_duration(str(audio_path))
    logger.info(f"Audio: {audio_dur:.1f}s")

    # ── Stage 2: Visual background (Ken Burns > gameplay > color) ────────────
    logger.info("[2/4] Preparing visual background...")
    processed_bg = None

    # Priority 1: Ken Burns on Pexels images (targets 25-45 demo, higher CPC)
    if os.getenv("PEXELS_API_KEY", "").strip():
        logger.info("  Trying Ken Burns (Pexels images)...")
        processed_bg = _prepare_ken_burns_bg(story, audio_dur)
        if processed_bg:
            logger.info("  Ken Burns background ready")

    # Priority 2: Gameplay footage (fallback when no Pexels key)
    if not processed_bg:
        logger.info("  Trying gameplay footage...")
        gameplay_clip = get_gameplay_clip(style=gameplay_style)
        if gameplay_clip:
            processed_bg = _prepare_gameplay_bg(gameplay_clip, audio_dur, ts)

    # ── Stage 3: Compose video ────────────────────────────────────────────
    logger.info("[3/4] Composing video...")
    video_output = run_dir / "video.mp4"
    script_data  = script if script else _build_script_data(story)
    reddit_card  = _generate_reddit_card(story)

    try:
        if processed_bg:
            ok = _render_with_gameplay(
                processed_bg, audio_path, word_ts, video_output, audio_dur,
                reddit_card=reddit_card,
            )
        else:
            logger.warning("No visual background — using color fallback")
            ok = _render_color_fallback(audio_path, word_ts, video_output, audio_dur)
    except Exception as e:
        logger.error(f"Compose failed: {e}")
        return False

    if not ok:
        return False

    # ── Stage 4: Landing page ─────────────────────────────────────────────
    logger.info("[4/4] Generating landing page...")
    try:
        landing_path = generate(story_path, output_dir=run_dir / "landing")
    except Exception as e:
        logger.error(f"Landing page failed: {e}")
        landing_path = None

    # ── Telegram ──────────────────────────────────────────────────────────
    if send_telegram:
        logger.info("Sending to Telegram...")
        try:
            distribute_video(video_output, script_data)
        except Exception as e:
            logger.error(f"Telegram failed: {e}")

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    _clean_temp()

    logger.info("━" * 54)
    logger.info(f"  Done in {elapsed:.1f}s")
    logger.info(f"  Video:   {video_output}")
    if landing_path:
        logger.info(f"  Landing: {landing_path}")
    logger.info("━" * 54)

    print("\n" + "=" * 54)
    print("  NEXT STEPS")
    print("=" * 54)
    print(f"\n  1. Review video:   {video_output}")
    print(f"  2. Host landing:   {run_dir / 'landing' / 'index.html'}")
    print("     Drag to: netlify.com/drop  (free, 30 sec)")
    print("  3. Put Netlify URL in bio via Bitly (track clicks)")
    print("  4. Upload video to YouTube Shorts + TikTok")
    print("  5. After 14 days: clicks/views > 1.5% = validated\n")

    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="La Trampa Narrativa — MVP Pipeline",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--story",      metavar="PATH",
                        help="Path to story JSON (default: output/curated/latest.json)")
    parser.add_argument("--style",      metavar="STYLE",
                        choices=["minecraft", "subway_surfers", "satisfying"],
                        help="Gameplay style preference")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Skip Telegram delivery")
    args = parser.parse_args()

    if not _has_ffmpeg():
        logger.error("FFmpeg not found. Install: winget install ffmpeg")
        sys.exit(1)

    success = run_mvp(
        story_path     = Path(args.story) if args.story else None,
        gameplay_style = args.style,
        send_telegram  = not args.no_telegram,
    )
    sys.exit(0 if success else 1)

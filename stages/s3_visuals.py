import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests

from config import TEMP_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS

logger = logging.getLogger(__name__)

# ── Pexels ────────────────────────────────────────────────────────────────────

def _download_file(url: str, dest: Path, timeout: int = 60) -> bool:
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Download failed {url}: {e}")
        return False


def search_pexels_videos(query: str, count: int = 2) -> list[str]:
    """Download vertical B-roll clips from Pexels."""
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        logger.warning("PEXELS_API_KEY not set — skipping Pexels")
        return []

    import random
    headers = {"Authorization": api_key}
    params  = {
        "query":       query,
        "orientation": "portrait",
        "size":        "medium",
        "per_page":    count + 3,
        "page":        random.randint(1, 4),
    }

    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers, params=params, timeout=15,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
    except Exception as e:
        logger.error(f"Pexels search failed: {e}")
        return []

    downloaded = []
    for video in videos:
        files = [
            f for f in video.get("video_files", [])
            if f.get("quality") in ("hd", "sd") and f.get("file_type") == "video/mp4"
        ]
        if not files:
            continue
        # Prefer highest resolution available
        files.sort(key=lambda x: x.get("width", 0), reverse=True)
        url = files[0]["link"]

        safe = "".join(c for c in query if c.isalnum() or c == "_")[:25]
        dest = TEMP_DIR / f"pexels_{safe}_{video['id']}.mp4"

        if not dest.exists():
            if not _download_file(url, dest, timeout=45):
                continue

        downloaded.append(str(dest))
        if len(downloaded) >= count:
            break

    logger.info(f"Pexels '{query}': {len(downloaded)} clips downloaded")
    return downloaded


# ── Runware (AI hook image → Ken Burns video) ─────────────────────────────────

def _generate_runware_image(visual_prompt: str) -> Path | None:
    """Generate a 1080x1920 cinematic drama image using Runware API."""
    api_key = os.getenv("RUNWARE_API_KEY", "")
    if not api_key:
        return None

    enhanced = (
        f"Cinematic drama photography, vertical portrait 9:16, {visual_prompt}, "
        "dramatic moody lighting, photorealistic, 8k resolution, highly detailed, "
        "emotional depth, dark atmospheric background, storytelling composition"
    )

    payload = [{
        "taskType":        "imageInference",
        "taskUUID":        str(uuid.uuid4()),
        "model":           "runware:100@1",
        "positivePrompt":  enhanced,
        "negativePrompt":  "cartoon, illustration, text, watermark, blurry, distorted",
        "width":           VIDEO_WIDTH,
        "height":          VIDEO_HEIGHT,
        "numberResults":   1,
        "outputFormat":    "JPEG",
    }]

    try:
        r = requests.post(
            "https://api.runware.ai/v1",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()

        image_url = None
        for item in data.get("data", []):
            if item.get("taskType") == "imageInference":
                image_url = item.get("imageURL") or item.get("url")
                break

        if not image_url:
            logger.warning("Runware returned no image URL")
            return None

        dest = TEMP_DIR / f"hook_img_{int(time.time())}.jpg"
        if _download_file(image_url, dest):
            logger.info(f"Runware image ready: {dest.name}")
            return dest

    except Exception as e:
        logger.error(f"Runware failed: {e}")

    return None


def _image_to_ken_burns_video(image_path: Path, duration: int = 3) -> str | None:
    """Animate a still image with a slow zoom-in (Ken Burns effect) via FFmpeg."""
    output = TEMP_DIR / f"hook_video_{int(time.time())}.mp4"

    # zoompan: slowly zoom from 1.0x to 1.10x over `duration` seconds
    total_frames = duration * VIDEO_FPS
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", (
            f"scale={VIDEO_WIDTH * 2}:{VIDEO_HEIGHT * 2},"
            f"zoompan=z='min(zoom+0.0008,1.1)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Ken Burns encode failed: {result.stderr[-300:]}")
        return None

    logger.info(f"Hook video (Ken Burns): {output.name}")
    return str(output)


def generate_ai_hook(visual_prompt: str) -> str | None:
    """Full AI hook pipeline: generate image → animate."""
    img = _generate_runware_image(visual_prompt)
    if img:
        return _image_to_ken_burns_video(img, duration=3)
    return None


# ── Pexels still images + Ken Burns background ───────────────────────────────

def search_pexels_images(query: str, count: int = 3) -> list[str]:
    """Download portrait photos from Pexels for Ken Burns animation."""
    api_key = os.getenv("PEXELS_API_KEY", "")
    if not api_key:
        return []

    import random
    headers = {"Authorization": api_key}
    params  = {
        "query":       query,
        "orientation": "portrait",
        "size":        "large",
        "per_page":    count + 4,
        "page":        random.randint(1, 3),
    }
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers, params=params, timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
    except Exception as e:
        logger.error(f"Pexels image search failed: {e}")
        return []

    downloaded = []
    for photo in photos:
        src = photo.get("src", {})
        url = src.get("large2x") or src.get("large")
        if not url:
            continue
        dest = TEMP_DIR / f"pexels_img_{photo['id']}.jpg"
        if not dest.exists():
            if not _download_file(url, dest, timeout=30):
                continue
        downloaded.append(str(dest))
        if len(downloaded) >= count:
            break

    logger.info(f"Pexels images '{query}': {len(downloaded)} downloaded")
    return downloaded


def create_ken_burns_background(image_paths: list[str], target_duration: float) -> str | None:
    """
    Animate multiple images with Ken Burns effect (slow zoom + pan),
    then concatenate to fill target_duration. Each image gets ~5 seconds.
    Returns path to the final background video or None on failure.
    """
    if not image_paths:
        return None

    clip_dur = 5.0
    total_frames = int(clip_dur * VIDEO_FPS)

    # (zoom_expr, x_expr, y_expr) — varied motion to avoid monotony
    PATTERNS = [
        ("min(zoom+0.0006,1.25)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        ("min(zoom+0.0006,1.20)", "0",                 "ih/2-(ih/zoom/2)"),
        ("min(zoom+0.0006,1.20)", "iw-(iw/zoom)",      "ih/2-(ih/zoom/2)"),
        ("if(lte(zoom,1.0),1.2,max(1.001,zoom-0.0004))", "iw/2-(iw/zoom/2)", "0"),
    ]

    clips = []
    for i, img_path in enumerate(image_paths):
        z, x, y = PATTERNS[i % len(PATTERNS)]
        output = TEMP_DIR / f"kb_{i}_{int(time.time())}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-vf", (
                f"scale={VIDEO_WIDTH * 2}:{VIDEO_HEIGHT * 2}"
                f":force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH * 2}:{VIDEO_HEIGHT * 2},"
                f"zoompan=z='{z}':x='{x}':y='{y}'"
                f":d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
                "eq=saturation=1.08:contrast=1.06:brightness=0.01"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-t", str(clip_dur), "-an",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            clips.append(str(output))
        else:
            logger.warning(f"Ken Burns clip {i} failed: {result.stderr[-200:]}")

    if not clips:
        return None

    # Concatenate clips to fill target_duration
    list_path = TEMP_DIR / "kb_concat.txt"
    selected, total = [], 0.0
    while total < target_duration:
        for c in clips:
            selected.append(c)
            total += clip_dur
            if total >= target_duration:
                break

    with open(list_path, "w", encoding="utf-8") as f:
        for c in selected:
            f.write(f"file '{c.replace(chr(92), '/')}'\n")

    output = TEMP_DIR / f"kb_bg_{int(time.time())}.mp4"
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-t", str(target_duration + 1),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-r", str(VIDEO_FPS), "-an",
        str(output),
    ], capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"Ken Burns concat failed: {result.stderr[-300:]}")
        return None

    logger.info(f"Ken Burns background: {output.name} ({target_duration:.1f}s)")
    return str(output)


# ── Fallback: solid gradient background clip ─────────────────────────────────

def create_fallback_clip(index: int = 0, duration: int = 12) -> str | None:
    """Solid-color fallback when no visual API is configured."""
    colors = ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#2b2d42"]
    color  = colors[index % len(colors)]
    output = TEMP_DIR / f"fallback_{index}.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color={color}:size={VIDEO_WIDTH}x{VIDEO_HEIGHT}:rate={VIDEO_FPS}",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return str(output) if result.returncode == 0 else None


# Curated fallback queries — emotionally resonant, always available on Pexels
_FALLBACK_QUERIES = [
    "woman shocked reading phone",
    "couple arguing living room",
    "person crying alone bedroom",
    "man looking betrayed frustrated",
    "woman walking away determined",
]

# ── Public interface ──────────────────────────────────────────────────────────

def collect_visual_assets(pexels_queries: list[str]) -> dict:
    """
    Collect hook clip + B-roll using short, targeted Pexels queries.
    Falls back to curated queries if GPT-generated ones return nothing.
    Returns {"hook": path_or_None, "broll": [paths]}
    """
    import random

    assets: dict = {"hook": None, "broll": []}

    # Use provided queries, pad with fallbacks if needed
    queries = list(pexels_queries or [])
    if len(queries) < 3:
        extras = [q for q in _FALLBACK_QUERIES if q not in queries]
        queries += random.sample(extras, min(3 - len(queries), len(extras)))

    # Hook: try AI first, fall back to Pexels
    hook_clip = generate_ai_hook(queries[0])
    if hook_clip:
        assets["hook"] = hook_clip
    else:
        clips = search_pexels_videos(queries[0], count=1)
        if clips:
            assets["hook"] = clips[0]

    # B-roll: 2 clips per remaining query → 8-10 clips total for rapid cuts
    for query in queries[1:]:
        clips = search_pexels_videos(query, count=2)
        assets["broll"].extend(clips)

    # If still nothing, use pure fallbacks
    if not assets["hook"] and not assets["broll"]:
        logger.warning("All queries failed — using fallback queries")
        for q in random.sample(_FALLBACK_QUERIES, 3):
            clips = search_pexels_videos(q, count=1)
            if clips:
                if not assets["hook"]:
                    assets["hook"] = clips[0]
                else:
                    assets["broll"].extend(clips)

    logger.info(
        f"Assets collected — hook: {'yes' if assets['hook'] else 'no'}, "
        f"broll: {len(assets['broll'])} clips"
    )
    return assets

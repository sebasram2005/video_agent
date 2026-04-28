"""
Stage 4 — Video composition

Identical pipeline to the Emermédica bot with two adjustments:
  - Cinematic color grade (cooler, more dramatic — fits drama/betrayal content)
  - Subtitle styles tuned for US/UK audiences (higher contrast, slightly larger)
"""

import logging
import os
import random
import subprocess
from pathlib import Path

from config import MUSIC_DIR, TEMP_DIR, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH
from stages.s3_visuals import create_fallback_clip

logger = logging.getLogger(__name__)

# ── ASS subtitle styles ───────────────────────────────────────────────────────
# (font, base_px, active_px, active_BGR, base_BGR, outline_BGR)
_SUBTITLE_STYLES = [
    ("Arial Rounded MT Bold", 70, 92, "&H0000EEFF", "&H00FFFFFF", "&H00000000"),  # yellow
    ("Arial Rounded MT Bold", 70, 92, "&H0020C0FF", "&H00FFFFFF", "&H00000000"),  # orange
    ("Arial Rounded MT Bold", 70, 92, "&H0040DD70", "&H00FFFFFF", "&H00000000"),  # green
    ("Impact",                68, 88, "&H00FFB830", "&H00F0F0F0", "&H00000000"),  # gold
    ("Arial Rounded MT Bold", 70, 92, "&H00FF6060", "&H00FFFFFF", "&H00000000"),  # coral
]

# Cinematic drama grade — cooler/desaturated reds, enhanced contrast.
# Uses colorbalance instead of curves (curves breaks on Windows via subprocess).
_CINEMATIC_GRADE = (
    "colorbalance=rs=-0.06:gs=0:bs=0.06,"
    "eq=saturation=1.10:brightness=0.01:contrast=1.10"
)


# ── ASS helpers ───────────────────────────────────────────────────────────────

def _fmt_ass_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_subtitles(word_timestamps: list[dict], style_idx: int = 0) -> str:
    font, base_px, active_px, active_bgr, base_bgr, outline_bgr = (
        _SUBTITLE_STYLES[style_idx % len(_SUBTITLE_STYLES)]
    )

    margin_v = int(VIDEO_HEIGHT * 0.33)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {VIDEO_WIDTH}\n"
        f"PlayResY: {VIDEO_HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{base_px},{base_bgr},&H00000000,"
        f"{outline_bgr},&H90000000,-1,0,0,0,100,100,2,0,1,5,2,2,"
        f"60,60,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    # Group words into fixed chunks of 4.
    # Each chunk stays on screen for all its words — only the highlighted word changes.
    # This eliminates: (1) gaps between events, (2) text jumping every single word.
    WORDS_PER_GROUP = 4
    groups = [word_timestamps[i:i + WORDS_PER_GROUP]
              for i in range(0, len(word_timestamps), WORDS_PER_GROUP)]

    events = []
    for g_idx, group in enumerate(groups):
        next_start = groups[g_idx + 1][0]["start"] if g_idx + 1 < len(groups) else None

        for w_idx, current in enumerate(group):
            start = current["start"]

            # End = next word's start (no gap), or natural end for last word of last group
            if w_idx + 1 < len(group):
                end = group[w_idx + 1]["start"]
            elif next_start is not None:
                end = next_start
            else:
                end = current["start"] + current["duration"]

            parts = []
            for j, w in enumerate(group):
                word_text = w["word"].strip(".,!?;:")
                if not word_text:
                    continue
                if j == w_idx:
                    parts.append(
                        f"{{\\c{active_bgr}&\\b1\\fs{active_px}"
                        f"\\t(0,80,\\fscx115\\fscy115)\\t(80,200,\\fscx100\\fscy100)}}"
                        f"{word_text}{{\\r}}"
                    )
                else:
                    parts.append(
                        f"{{\\c{base_bgr}&\\b0\\fs{base_px}\\alpha&H30&}}"
                        f"{word_text}{{\\r}}"
                    )

            if parts:
                events.append(
                    f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},"
                    f"Default,,0,0,0,,{' '.join(parts)}"
                )

    return header + "\n".join(events)


# ── FFmpeg helpers ────────────────────────────────────────────────────────────

def _run(cmd: list[str], label: str = "") -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg [{label}]: {result.stderr[-700:]}")
        return False
    return True


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _ass_esc(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


_CLIP_MAX_DUR = 5.0

_MOTION_PATTERNS = [
    ("dx/2",           "dy*(1-t/D)"),
    ("dx/2",           "dy*t/D"),
    ("dx*t/D",         "dy/2"),
    ("dx*(1-t/D)",     "dy/2"),
    ("dx*t/D",         "dy*t/D"),
    ("dx*(1-t/D)",     "dy*t/D"),
    ("dx*(0.5-0.1*t/D)", "dy*(0.5-0.1*t/D)"),
]


def _process_clip(src: str, dst: str, motion_idx: int = 0) -> bool:
    src_dur  = _probe_duration(src) or _CLIP_MAX_DUR
    clip_dur = min(src_dur, _CLIP_MAX_DUR)
    clip_dur = max(clip_dur, 0.5)

    zoom_w = int(VIDEO_WIDTH  * 1.10)
    zoom_h = int(VIDEO_HEIGHT * 1.10)
    dx = zoom_w - VIDEO_WIDTH
    dy = zoom_h - VIDEO_HEIGHT

    xp, yp  = _MOTION_PATTERNS[motion_idx % len(_MOTION_PATTERNS)]
    x_expr  = xp.replace("dx", str(dx)).replace("dy", str(dy)).replace("D", f"{clip_dur:.3f}")
    y_expr  = yp.replace("dx", str(dx)).replace("dy", str(dy)).replace("D", f"{clip_dur:.3f}")

    vf = (
        f"scale={zoom_w}:{zoom_h}:force_original_aspect_ratio=increase,"
        f"crop={zoom_w}:{zoom_h},"
        f"{_CINEMATIC_GRADE},"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:'{x_expr}':'{y_expr}'"
    )

    return _run([
        "ffmpeg", "-y", "-i", src,
        "-t", str(clip_dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS), "-an",
        dst,
    ], f"clip_{motion_idx}")


def _concat_to_duration(clip_paths: list[str], dst: str, target: float) -> bool:
    list_path = TEMP_DIR / "concat_list.txt"

    total, selected = 0.0, []
    while total < target:
        for cp in clip_paths:
            d = _probe_duration(cp) or 5.0
            selected.append(cp)
            total += d
            if total >= target:
                break

    with open(list_path, "w", encoding="utf-8") as f:
        for cp in selected:
            f.write(f"file '{cp.replace(chr(92), '/')}'\n")

    return _run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-t", str(target),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-r", str(VIDEO_FPS),
        dst,
    ], "concat")


def _get_music() -> str | None:
    if not MUSIC_DIR.exists():
        return None
    files = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    return str(random.choice(files)) if files else None


def _get_logo() -> str | None:
    logo = os.getenv("BRAND_LOGO_PATH", "").strip()
    if logo and Path(logo).is_file():
        return logo
    default = Path(__file__).parent.parent / "assets" / "logo.png"
    return str(default) if default.is_file() else None


# ── Final render ──────────────────────────────────────────────────────────────

def _build_filter_graph(
    ass: str,
    music_src: str | None,
    logo_src: str | None,
    duration: float,
    has_music_input: bool,
) -> str:
    music_idx = 2 if has_music_input else None
    logo_idx  = (3 if has_music_input else 2) if logo_src else None

    parts = []

    if has_music_input:
        parts.append(
            f"[1:a]volume=1.0[voice];"
            f"[{music_idx}:a]volume=0.06,atrim=duration={duration}[music];"
            "[voice][music]amix=inputs=2:duration=first[audio]"
        )
        audio_out = "[audio]"
    else:
        audio_out = "1:a"

    parts.append(f"[0:v]ass='{ass}'[vsub]")

    if logo_src and logo_idx is not None:
        parts.append(
            f"[{logo_idx}:v]scale=iw*{VIDEO_WIDTH//7}/iw:-1[logo];"
            f"[vsub][logo]overlay=W-w-30:H-h-30:format=auto[vout]"
        )
        video_out = "[vout]"
    else:
        video_out = "[vsub]"

    return ";".join(parts), video_out, audio_out


def _render(
    video_src: str,
    voice_src: str,
    ass_path: Path,
    music_src: str | None,
    logo_src: str | None,
    dst: str,
    duration: float,
) -> bool:
    ass = _ass_esc(ass_path)

    inputs = ["-i", video_src, "-i", voice_src]
    if music_src:
        inputs += ["-stream_loop", "-1", "-i", music_src]
    if logo_src:
        inputs += ["-i", logo_src]

    graph, video_out, audio_out = _build_filter_graph(
        ass, music_src, logo_src, duration,
        has_music_input=bool(music_src),
    )

    map_args = ["-map", video_out, "-map", audio_out]

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", graph]
        + map_args
        + [
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-t", str(duration), "-r", str(VIDEO_FPS),
            "-movflags", "+faststart",
            dst,
        ]
    )

    return _run(cmd, "final_render")


# ── Public entry point ────────────────────────────────────────────────────────

def compose_video(
    audio_path: Path,
    word_timestamps: list[dict],
    assets: dict,
    script_data: dict,
    output_path: Path,
) -> bool:
    audio_dur = _probe_duration(str(audio_path)) or 65.0
    logger.info(f"Audio duration: {audio_dur:.1f}s")

    # 1. Process clips
    scaled:  list[str] = []
    all_raw = [assets.get("hook")] + assets.get("broll", [])
    for idx, raw in enumerate([r for r in all_raw if r]):
        dst = str(TEMP_DIR / f"sc_{idx}.mp4")
        if _process_clip(raw, dst, motion_idx=idx):
            scaled.append(dst)

    if not scaled:
        logger.warning("No clips — using colour fallback")
        for i in range(3):
            fb = create_fallback_clip(i, duration=15)
            if fb:
                scaled.append(fb)

    if not scaled:
        logger.error("Cannot produce any visual clip")
        return False

    # 2. Concatenate
    concat_path = str(TEMP_DIR / "concat.mp4")
    if not _concat_to_duration(scaled, concat_path, audio_dur):
        return False

    # 3. Subtitles
    style_idx   = random.randint(0, len(_SUBTITLE_STYLES) - 1)
    ass_content = build_ass_subtitles(word_timestamps, style_idx)
    ass_path    = TEMP_DIR / "subs.ass"
    ass_path.write_text(ass_content, encoding="utf-8")

    # 4. Render
    music = _get_music()
    logo  = _get_logo()

    if not music:
        logger.info("No music in assets/music/ — rendering without background audio")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    success = _render(
        concat_path, str(audio_path), ass_path,
        music, logo, str(output_path), audio_dur,
    )

    if success:
        logger.info(
            f"Video ready: {output_path.name} "
            f"({output_path.stat().st_size / 1_048_576:.1f} MB)"
        )

    return success

"""
Stage 2 — Text-to-Speech + word timestamps

Priority:
  1. ElevenLabs (cloned/premium voice, if keys set)
  2. edge-tts   (English neural voices, free fallback)
"""

import asyncio
import base64
import logging
import os
import random
from pathlib import Path

import edge_tts
import requests

from config import TEMP_DIR, TTS_VOICES

logger = logging.getLogger(__name__)


# ── ElevenLabs ────────────────────────────────────────────────────────────────

def _chars_to_word_timestamps(chars: list, starts: list, ends: list) -> list[dict]:
    words        = []
    current_word = ""
    word_start   = None

    for i, (ch, t_start, t_end) in enumerate(zip(chars, starts, ends)):
        is_last = i == len(chars) - 1

        if ch == " " or is_last:
            if is_last and ch != " ":
                current_word += ch
                if word_start is None:
                    word_start = t_start
            if current_word and word_start is not None:
                words.append({
                    "word":     current_word,
                    "start":    word_start,
                    "duration": t_end - word_start,
                })
            current_word = ""
            word_start   = None
        else:
            if not current_word:
                word_start = t_start
            current_word += ch

    return words


def _generate_elevenlabs(text: str, output_path: Path) -> tuple[Path, list[dict]] | None:
    api_key  = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    payload = {
        "text":     text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability":         0.50,
            "similarity_boost":  0.80,
            "style":             0.25,
            "use_speaker_boost": True,
        },
    }

    try:
        r = requests.post(
            url, json=payload,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f"ElevenLabs failed: {e} — falling back to edge-tts")
        return None

    audio_bytes = base64.b64decode(data["audio_base64"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    alignment = data.get("alignment", {})
    word_ts   = _chars_to_word_timestamps(
        alignment.get("characters",                  []),
        alignment.get("character_start_times_seconds", []),
        alignment.get("character_end_times_seconds",  []),
    )

    logger.info(f"ElevenLabs done | words: {len(word_ts)} | {len(audio_bytes)//1024} KB")
    return output_path, word_ts


# ── edge-tts (free fallback) ──────────────────────────────────────────────────

async def _stream_edge_tts(text: str, voice: str) -> tuple[bytes, list[dict]]:
    communicate     = edge_tts.Communicate(text, voice)
    audio_chunks:   list[bytes] = []
    word_timestamps: list[dict] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            word_timestamps.append({
                "word":     chunk["text"],
                "start":    chunk["offset"]   / 10_000_000,
                "duration": chunk["duration"] / 10_000_000,
            })

    return b"".join(audio_chunks), word_timestamps


def _timestamps_from_text(text: str, audio_duration: float) -> list[dict]:
    words = text.split()
    if not words:
        return []

    def weight(w: str) -> float:
        base = max(1.5, len(w.rstrip(".,!?;:")))
        if w[-1] in ".!?":
            base += 3.5
        elif w[-1] in ",;:":
            base += 1.5
        return base

    weights      = [weight(w) for w in words]
    total_weight = sum(weights)
    timestamps   = []
    current_time = 0.08

    for w, wt in zip(words, weights):
        duration = (wt / total_weight) * (audio_duration - 0.08)
        timestamps.append({
            "word":     w,
            "start":    current_time,
            "duration": duration * 0.88,
        })
        current_time += duration

    return timestamps


def _get_audio_duration(path: Path) -> float:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 65.0


def _generate_edge_tts(text: str, output_path: Path, gender: str) -> tuple[Path, list[dict]]:
    voice = TTS_VOICES[gender]
    logger.info(f"edge-tts voice: {voice}")

    audio_bytes, word_ts = asyncio.run(_stream_edge_tts(text, voice))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    if not word_ts:
        logger.warning("No WordBoundary events — using proportional distribution")
        duration = _get_audio_duration(output_path)
        word_ts  = _timestamps_from_text(text, duration)

    logger.info(f"edge-tts done | words: {len(word_ts)} | {len(audio_bytes)//1024} KB")
    return output_path, word_ts


# ── Public entry point ────────────────────────────────────────────────────────

def generate_tts(
    text: str,
    output_path: Path,
    gender: str = None,
) -> tuple[Path, list[dict]]:
    """
    Generate TTS audio with word-level timestamps.
    Tries ElevenLabs first, falls back to edge-tts English neural voice.
    Returns (audio_path, word_timestamps).
    """
    if gender is None:
        gender = random.choice(["male", "female"])

    result = _generate_elevenlabs(text, output_path)
    if result:
        logger.info("Using ElevenLabs")
        return result

    logger.info("Using edge-tts (English neural)")
    return _generate_edge_tts(text, output_path, gender)

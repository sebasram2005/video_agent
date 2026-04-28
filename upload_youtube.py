#!/usr/bin/env python3
"""
upload_youtube.py — Sube videos a YouTube Shorts automáticamente.

Primera vez: abre el navegador para autorizar con tu cuenta de YouTube.
Siguientes veces: usa el token guardado, sin interacción.

Usage:
  python upload_youtube.py --video output/mvp_20260427_225044/video.mp4
  python upload_youtube.py          # usa el último video generado
  python upload_youtube.py --private  # sube como privado para revisar primero
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
OUTPUT_DIR    = BASE_DIR / "output"

# Busca el client_secrets automáticamente (el nombre que descarga Google es largo)
def _find_client_secrets() -> Path:
    explicit = os.getenv("YOUTUBE_CLIENT_SECRETS", "").strip()
    if explicit and Path(explicit).exists():
        return Path(explicit)
    candidates = list(BASE_DIR.glob("client_secret*.json"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        "No se encontró client_secrets.json.\n"
        "Descárgalo desde Google Cloud Console → APIs & Services → Credentials."
    )

TOKEN_FILE    = BASE_DIR / "youtube_token.json"
SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]

BLOG_URL      = os.getenv("BLOG_URL", "https://blogreddit.netlify.app")
BRAND_NAME    = os.getenv("BRAND_NAME", "ForumDrama")

_BASE_TAGS = [
    "RedditStories", "AITA", "StoryTime", "RelationshipAdvice",
    "ForumDrama", "BestOfReddit", "RedditDrama", "Shorts",
]


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            logger.info("Token renovado automáticamente.")
        else:
            client_secrets = _find_client_secrets()
            logger.info(f"Abriendo navegador para autorizar con tu cuenta de YouTube...")
            logger.info("Selecciona la cuenta donde está el canal @reddithistories-h7v")
            flow  = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
            logger.info("Autorización completada.")

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Token guardado en {TOKEN_FILE.name} — próximas subidas serán automáticas.")

    return creds


# ── Metadata ──────────────────────────────────────────────────────────────────

def _build_metadata(story_data: dict, script_data: dict, private: bool) -> dict:
    title      = story_data.get("title", "Reddit Story")
    subreddit  = story_data.get("subreddit", "reddit")
    score      = story_data.get("score", 0)
    hook       = script_data.get("hook_text", title[:80])
    custom_tags = [t.lstrip("#") for t in script_data.get("hashtags", [])]
    all_tags   = list(dict.fromkeys(_BASE_TAGS + custom_tags))[:15]

    # Título de YouTube: máx 100 chars, debe incluir #Shorts para activar el feed
    yt_title = f"{title} #Shorts"
    if len(yt_title) > 100:
        yt_title = title[:96] + " #Sh"

    description = (
        f"{hook}\n\n"
        f"r/{subreddit} • ⬆️ {score:,} upvotes\n\n"
        f"📖 Read the FULL story (with the ending) here:\n{BLOG_URL}\n\n"
        f"💬 Drop your verdict in the comments 👇\n\n"
        f"#{' #'.join(all_tags)}"
    )

    return {
        "snippet": {
            "title":       yt_title,
            "description": description,
            "tags":        all_tags,
            "categoryId":  "24",   # Entertainment
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":          "private" if private else "public",
            "selfDeclaredMadeForKids": False,
        },
    }


# ── Upload ────────────────────────────────────────────────────────────────────

def upload(video_path: Path, story_data: dict, script_data: dict, private: bool = False) -> str | None:
    """
    Sube el video a YouTube. Devuelve el video_id o None si falla.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        logger.error(
            "Faltan dependencias. Instala:\n"
            "  pip install google-api-python-client google-auth-oauthlib"
        )
        return None

    creds    = _get_credentials()
    youtube  = build("youtube", "v3", credentials=creds)
    metadata = _build_metadata(story_data, script_data, private)

    logger.info(f"Subiendo: {video_path.name}  ({video_path.stat().st_size / 1_048_576:.1f} MB)")
    logger.info(f"Título:   {metadata['snippet']['title']}")
    logger.info(f"Estado:   {'PRIVADO' if private else 'PÚBLICO'}")

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,   # 5 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=metadata,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            logger.info(f"  Subiendo... {pct}%")

    video_id  = response.get("id", "")
    video_url = f"https://youtube.com/shorts/{video_id}"
    logger.info(f"Video publicado: {video_url}")
    return video_id


# ── CLI ───────────────────────────────────────────────────────────────────────

def _find_latest_run() -> Path | None:
    runs = sorted(OUTPUT_DIR.glob("mvp_*/video.mp4"))
    return runs[-1] if runs else None


def _load_story_and_script(run_dir: Path) -> tuple[dict, dict]:
    """Carga story JSON del run o del curated/latest.json como fallback."""
    story_json = OUTPUT_DIR / "curated" / "latest.json"
    story_data = json.loads(story_json.read_text(encoding="utf-8")) if story_json.exists() else {}

    # script_data no se guarda actualmente — reconstruimos lo mínimo necesario
    script_data = {
        "hook_text":        story_data.get("title", "")[:80],
        "source_subreddit": story_data.get("subreddit", ""),
        "source_score":     story_data.get("score", 0),
        "hashtags":         ["#AITA", "#RedditStories", "#StoryTime",
                             "#ForumDrama", "#Shorts"],
    }
    return story_data, script_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Subir video a YouTube Shorts")
    parser.add_argument("--video",   metavar="PATH", help="Ruta al video.mp4")
    parser.add_argument("--private", action="store_true", help="Subir como privado")
    args = parser.parse_args()

    if args.video:
        video_path = Path(args.video)
    else:
        video_path = _find_latest_run()
        if not video_path:
            logger.error("No se encontró ningún video. Pasa --video ruta/al/video.mp4")
            sys.exit(1)
        logger.info(f"Usando último video: {video_path}")

    if not video_path.exists():
        logger.error(f"Video no encontrado: {video_path}")
        sys.exit(1)

    story_data, script_data = _load_story_and_script(video_path.parent)

    video_id = upload(video_path, story_data, script_data, private=args.private)
    if video_id:
        print(f"\n  YouTube Shorts: https://youtube.com/shorts/{video_id}\n")
        sys.exit(0)
    else:
        sys.exit(1)

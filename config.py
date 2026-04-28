from pathlib import Path
import os

BASE_DIR   = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR  = ASSETS_DIR / "music"
FONTS_DIR  = ASSETS_DIR / "fonts"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR   = BASE_DIR / "temp"

VIDEO_WIDTH  = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS    = 30

# English neural voices — edge-tts free fallback
TTS_VOICES = {
    "male":   "en-US-ChristopherNeural",
    "female": "en-US-JennyNeural",
}

BRAND_NAME = os.getenv("BRAND_NAME", "ForumDrama")

# 65s for TikTok Creator Rewards threshold (>60s required).
# For new accounts (<10K followers, not yet monetized): consider 55s for
# better completion rate. Switch to 65s once Creator Rewards is active.
TARGET_DURATION_SECONDS = 65

# ── Dual-account subreddit architecture ───────────────────────────────────────
# Account A — Legal/Corporate (CPC $15-75): activates legal services + B2B tech ads
ACCOUNT_A_SUBREDDITS = [
    "ProRevenge",
    "NuclearRevenge",
    "MaliciousCompliance",
    "legaladvice",
    "TalesFromTechSupport",
]

# Account B — Relationship/Family (CPC $8-45): activates insurance, family law, therapy ads
ACCOUNT_B_SUBREDDITS = [
    "AmItheAsshole",
    "AITAH",
    "survivinginfidelity",
    "relationship_advice",
    "BestofRedditorUpdates",
    "TrueOffMyChest",
    "offmychest",
]

# Combined list used by the automated pipeline (main.py).
# tifu/entitledparents/confessions removed: CPC $0.7-1.1, destroys contextual RPM.
SOURCE_SUBREDDITS = ACCOUNT_A_SUBREDDITS + ACCOUNT_B_SUBREDDITS

# Story quality filters
# MIN_STORY_SCORE at 5000 for the first 60 days (new domain):
# only premium stories build domain authority and clean traffic signals.
# Lower to 1000 once you hit 10K sessions/month.
MIN_STORY_SCORE = 5000
MIN_STORY_WORDS = 200
MAX_STORY_WORDS = 3000

# Story covers this fraction of the narrative before cliffhanger
STORY_COVERAGE_FRACTION = 0.72

# Platforms targeted for distribution
PLATFORMS = ["youtube_shorts", "facebook_reels"]

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Traffic arbitrage pipeline: curate viral Reddit stories → generate a 60-65s YouTube Short/TikTok with a cliffhanger → drive viewers to a paginated blog where display ads fire on every page load (Mediavine model). The blog lives in `../reddit-stories-blog/`.

## Commands

```bash
# Step 1 — pick a story interactively
python curator.py
python curator.py --account A          # Legal/Corporate subreddits (higher CPC)
python curator.py --account B          # Relationship/Family subreddits
python curator.py --subreddit AITAH    # specific subreddit

# Step 2 — generate video + landing page
python mvp_run.py
python mvp_run.py --no-telegram        # skip Telegram delivery
python mvp_run.py --story output/curated/story_XYZ.json

# Step 3 — export story to Next.js blog
python export_to_blog.py
python export_to_blog.py --all             # export all curated stories
python export_to_blog.py --trigger-build   # also trigger Netlify rebuild

# Install dependencies
pip install -r requirements.txt
```

## Pipeline architecture

```
curator.py  →  output/curated/latest.json
                     ↓
mvp_run.py  (orchestrator — 4 stages)
  ├─ stages/s1_script.py   GPT-4o → narration script + hook_text + metadata
  ├─ stages/s2_tts.py      ElevenLabs (priority) or edge-tts → audio + word timestamps
  ├─ stages/s3_visuals.py  Pexels images → Ken Burns video (priority) or gameplay clip
  └─ stages/s4_compose.py  build_ass_subtitles() → FFmpeg final render
         ↓
  output/mvp_YYYYMMDD_HHMMSS/
    ├─ video.mp4
    └─ landing/             (legacy HTML — superseded by Next.js blog)
         ↓
export_to_blog.py  →  ../reddit-stories-blog/content/stories/story_{id}.json
```

## Key design decisions

**Narration format** — `"Reddit Stories. {title}. {narration_body} {cta}"`. The Reddit title is the spoken hook (it's already viral-tested). `hook_text` from GPT is a 4-6 word visual overlay only, shown on the Reddit card PNG for the first 4.5s — not spoken.

**Reddit card overlay** — `_generate_reddit_card()` in `mvp_run.py` creates a Pillow PNG with subreddit, title, and upvote count. FFmpeg overlays it using `enable='between(t,0,4.5)'`. Subtitles are suppressed during card duration (`card_end` filter in `_render_with_gameplay`).

**Subtitle grouping** — `build_ass_subtitles()` in `s4_compose.py` groups words into fixed chunks of 4. Each chunk stays on screen while only the active word is highlighted (scale pulse). This eliminates gaps between ASS events and prevents text jumping on every word.

**Visual background priority** — Ken Burns (Pexels portrait images) > gameplay footage > solid colour fallback. Ken Burns targets the 25-45 demographic for higher CPC.

**Dual-account subreddit split** (in `config.py`) — Account A (legal/corporate, CPC $15-75): ProRevenge, NuclearRevenge, MaliciousCompliance, legaladvice, TalesFromTechSupport. Account B (relationship/family, CPC $8-45): AmItheAsshole, AITAH, survivinginfidelity, relationship_advice, etc. `SOURCE_SUBREDDITS` combines both for `main.py`.

**Story scoring** — `_retention_score()` in `curator.py` weights: base upvotes × log(comments), controversy ratio, word count sweet spot (400-800 words = 60-90s video), emotional arc keywords, legal/finance/tech CPC keywords, and subreddit CPC tier.

**Cliffhanger split** — Human-chosen at curation time (`split_at_paragraph`). Part 1 = video narration (70% of story). Part 2 = blog resolution (drives return traffic). The `full_text` field contains the complete story; `part1_text` and `part2_text` are the split halves.

## Environment variables

See `.env.template`. Required: `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Optional but recommended: `PEXELS_API_KEY` (Ken Burns background), `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (better voice). `NETLIFY_BUILD_HOOK_URL` enables auto-rebuild on `export_to_blog.py --trigger-build`.

## Story JSON schema

Fields consumed downstream by the blog (`RawStory` type in `../reddit-stories-blog/src/lib/types.ts`):

```
id, subreddit, title, score, num_comments, url, word_count,
part1_text, part2_text, full_text,
split_at_paragraph,   ← paragraph index where cliffhanger marker is injected in blog
total_paragraphs,
curated_at            ← ISO timestamp used as article datePublished
```

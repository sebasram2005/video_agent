"""
Stage 1 — Script Generation

Takes a Reddit story and generates a ~65-second English narration script.
The script covers 70% of the story then cuts to a cliffhanger, driving
viewers to the blog for the full resolution (Mediavine arbitrage model).
"""

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a viral short-form video scriptwriter. Your hooks have stopped
millions of scrolls on TikTok, YouTube Shorts, and Instagram Reels. You know that the
first 3 seconds are the only seconds that matter — if the hook doesn't land, the video dies.

ABSOLUTE RULES:
1. Never use Reddit usernames. Use "OP" or a generic name (Alex, Sam, Jamie, Jordan).
2. Write for spoken audio only. No lists, no symbols, no markdown. Pure conversational flow.
3. Never start with: "So", "Today", "Hey guys", "Welcome back", "This is a story about".
4. Active voice. Present tense for dramatic scenes. Short sentences under tension.
5. Platform-safe for YouTube and Facebook at all times.
6. The cliffhanger must create genuine psychological discomfort — the viewer CANNOT leave."""


def _build_prompt(story: dict) -> str:
    title = story["title"]
    text  = story.get("text") or story.get("full_text", "")
    sub   = story["subreddit"]
    story_excerpt = text[:2800]

    return f"""Write a 65-second narration script for this Reddit story. Target: YouTube Shorts + TikTok.

SOURCE:
Subreddit: r/{sub}
Title: {title}
Story: {story_excerpt}

FORMAT: "Reddit Stories. [title]. [narration body] [CTA]"

The Reddit title IS the hook — it's already been upvoted by thousands of people who found it
compelling. Do NOT rewrite it. The narration starts immediately after the title is read.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATION BODY [~55 seconds after the title]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[0–15s] CONTEXT: Who is OP? Who are the key people? What is the relationship?
  One concrete specific detail that makes this feel real (a name, a place, a number).
  DO NOT repeat the title. Jump straight into the story.

[16–45s] ESCALATION: Show the conflict deepening. Build to a moment where the viewer
  thinks "okay this is bad" — then immediately reveal something worse.
  Short punchy sentences under tension. Raise emotional stakes to maximum.

[46–57s] CLIFFHANGER: Cut RIGHT before the resolution. End at peak tension.
  The viewer must feel the answer is one second away but unreachable. Examples:
  - "And then I saw the message she'd sent."
  - "That's when he said something I never expected."
  - "I looked at what she'd hidden and realized everything had been a lie."
  DO NOT reveal the outcome. DO NOT say "stay tuned" or "find out next time".

[57–60s] CTA (use exactly): "Drop your verdict in the comments — and read the FULL story with the ending at the link in my bio."

WORD COUNT: 115–125 words for narration_script only (title + CTA are added separately).
At 130 wpm the full video = 62–67 seconds. Count carefully.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
hook_text = VISUAL OVERLAY ONLY (not spoken)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4–6 words shown as a subtitle card while the title is read aloud. NOT spoken.
Must be the CONSEQUENCE of the story stated bluntly. Specific, not abstract.
Use plain language. No metaphors. No adjectives without nouns.

GOOD — specific consequence: "She left her daughter to grieve alone." / "He sided with his mom. Big mistake." / "The daughter never forgave her."
BAD — abstract/vague: "Fear paralyzed her responsibility." / "A dramatic family moment." / "Trust was broken forever."

RESPOND ONLY with valid JSON (no markdown, no extra text):
{{
  "hook_text": "4–6 word visual teaser for on-screen text overlay. Not spoken.",
  "narration_script": "Context + escalation + cliffhanger. NO title repeat, NO CTA. 115–125 words.",
  "cta": "Drop your verdict in the comments — and read the FULL story with the ending at the link in my bio.",
  "pexels_queries": [
    "cinematic portrait shocked person close up dramatic lighting",
    "couple serious conversation living room emotional",
    "person alone reading phone devastated",
    "confrontation argument two people tense",
    "person staring window contemplating regret"
  ],
  "story_category": "one of: betrayal, revenge, family_drama, relationship, workplace, entitled_person, confession",
  "topic_tag": "3-word English topic tag",
  "blog_title": "SEO blog title for full story",
  "yt_title": "YouTube title. Max 90 chars. Emotional hook that creates curiosity — do NOT copy the Reddit title. Do NOT start with AITA/AITAH. Write it like a tabloid headline: state the drama, imply the conflict, make the viewer need to know the verdict. Example good titles: 'She Returned His Gift And Said She Deserved Better' / 'His Own Mom Sided Against Him At The Wedding' / 'She Found The Messages And Confronted Him In Public'.",
  "hashtags": ["#AITA", "#RedditStories", "#StoryTime", "#RelationshipAdvice", "#ForumDrama", "#Shorts", "#Reels"]
}}"""


def generate_script(story: dict, context: dict = None) -> dict:
    """
    Generate a 65-second English cliffhanger narration script from a Reddit story.
    Returns structured script data consumed by TTS + composition stages.
    """
    logger.info(
        f"Generating script | r/{story['subreddit']} | "
        f"score: {story['score']:,} | {story['word_count']} words"
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": _build_prompt(story)},
        ],
        temperature=0.55,
        max_tokens=900,
        response_format={"type": "json_object"},
    )

    script_data = json.loads(response.choices[0].message.content)

    # Inject story provenance for distribution stage
    script_data["source_subreddit"] = story["subreddit"]
    script_data["source_id"]        = story["id"]
    script_data["source_url"]       = story["url"]
    script_data["source_score"]     = story["score"]
    script_data["source_title"]     = story["title"]

    logger.info(
        f"Script ready | hook: {script_data.get('hook_text', '')[:60]} | "
        f"category: {script_data.get('story_category', '?')}"
    )
    return script_data


def build_full_narration(script_data: dict) -> str:
    """
    Build the full TTS narration in the proven Reddit Stories format:
      "Reddit Stories. [title]. [narration body]. [cliffhanger]. [CTA]"

    The Reddit title IS the hook — curator selects 5K+ upvote stories whose
    titles are already viral. hook_text is kept for Ken Burns visual overlay only.
    """
    title = script_data.get("source_title", script_data.get("hook_text", ""))
    return (
        f"Reddit Stories. {title}. "
        f"{script_data['narration_script']} "
        f"{script_data['cta']}"
    )

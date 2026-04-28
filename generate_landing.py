#!/usr/bin/env python3
"""
generate_landing.py — Paginated Landing Page Generator (Part 2)

Generates 3 HTML pages from the story resolution, forcing 3 separate ad auctions
per user session instead of 1. At $15 RPM (Journey by Mediavine) this triples
effective RPM to ~$45 per session.

Output structure:
  landing/index.html    — Page 1 of 3 (hook into resolution)
  landing/page-2.html   — Page 2 of 3 + email capture
  landing/page-3.html   — Page 3 of 3 (verdict) + affiliate block

Affiliate links (fill in your IDs before deploying):
  Legal/Corporate stories  → JustAnswer Law    (CJ Affiliate / ShareASale)
  Relationship stories     → BetterHelp        (Impact network, ~$100-150/lead)
  Tech stories             → JustAnswer Tech   (CJ Affiliate)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMPLATE_PATH = Path(__file__).parent / "landing" / "template.html"
OUTPUT_DIR    = Path(__file__).parent / "output"

# ── Affiliate configuration ───────────────────────────────────────────────────
# Replace the URL values with your actual affiliate links before going live.
# Sign up at: CJ Affiliate (cj.com) for JustAnswer, Impact (impact.com) for BetterHelp.

_AFFILIATE_CONFIG = {
    "legal": {
        "subreddits": {"ProRevenge", "NuclearRevenge", "MaliciousCompliance", "legaladvice"},
        "headline":   "Dealing with a similar workplace or legal situation?",
        "link_text":  "Ask a verified lawyer — answer in minutes",
        "url":        "https://www.justanswer.com/law/",  # ← replace with your affiliate URL
        "note":       "Sponsored · JustAnswer",
    },
    "tech": {
        "subreddits": {"TalesFromTechSupport"},
        "headline":   "Have a tech or IT issue of your own?",
        "link_text":  "Get expert help from a verified tech professional",
        "url":        "https://www.justanswer.com/computer/",  # ← replace with your affiliate URL
        "note":       "Sponsored · JustAnswer",
    },
    "relationship": {
        "subreddits": {
            "survivinginfidelity", "relationship_advice", "AmItheAsshole",
            "AITAH", "BestofRedditorUpdates", "TrueOffMyChest", "offmychest",
        },
        "headline":   "Going through something similar?",
        "link_text":  "Talk to a licensed therapist — first session affordable",
        "url":        "https://www.betterhelp.com/",  # ← replace with your affiliate URL
        "note":       "Sponsored · BetterHelp",
    },
}


def _get_affiliate_block(subreddit: str) -> str:
    """Return affiliate card HTML for the given subreddit, or empty string."""
    for cfg in _AFFILIATE_CONFIG.values():
        if subreddit in cfg["subreddits"]:
            return (
                f'<div class="affiliate-card">'
                f'<p class="affiliate-note">{cfg["note"]}</p>'
                f'<p class="affiliate-headline">{cfg["headline"]}</p>'
                f'<a href="{cfg["url"]}" class="btn btn-affiliate" '
                f'target="_blank" rel="noopener sponsored">{cfg["link_text"]} →</a>'
                f'</div>'
            )
    return ""


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _paras_to_html(paras: list[str]) -> str:
    return "\n".join(f"    <p>{_escape_html(p)}</p>" for p in paras)


# ── Pagination logic ──────────────────────────────────────────────────────────

def _split_into_pages(text: str) -> list[list[str]]:
    """
    Split text into pages dynamically based on paragraph count.
    >= 6 paragraphs → 3 pages; >= 3 paragraphs → 2 pages; else → 1 page.
    Ensures every page has at least 1 paragraph.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    n = len(paras)
    if n >= 6:
        num_pages = 3
    elif n >= 3:
        num_pages = 2
    else:
        return [paras]

    per_page = max(1, n // num_pages)
    pages = []
    for i in range(num_pages):
        start = i * per_page
        end   = start + per_page if i < num_pages - 1 else n
        if start < n:
            pages.append(paras[start:end])
    return pages


def _page_filename(page_num: int) -> str:
    return "index.html" if page_num == 1 else f"page-{page_num}.html"


def _prev_nav(page_num: int) -> str:
    if page_num <= 1:
        return ""
    url = _page_filename(page_num - 1)
    return f'<a href="{url}" class="btn-page btn-prev">← Previous</a>'


def _next_nav(page_num: int, total: int) -> str:
    if page_num >= total:
        return ""
    url   = _page_filename(page_num + 1)
    label = "Read the Final Part →" if page_num == total - 1 else "Continue Reading →"
    return f'<a href="{url}" class="btn-page btn-next">{label}</a>'


_REVEAL_BANNERS = [
    "<strong>Here it is.</strong> The full resolution — the part the video couldn't show you.",
    "<strong>Keep reading.</strong> The verdict is one page away.",
    "<strong>The final verdict.</strong> Here's exactly how it ended.",
]

_EMAIL_CAPTURE = """<div class="email-capture">
  <p class="email-headline">Get the next story in your inbox</p>
  <p class="email-sub">New drops every week — no spam, unsubscribe anytime.</p>
  <form name="story-subscribe" method="POST" data-netlify="true" class="email-form">
    <input type="hidden" name="form-name" value="story-subscribe">
    <input type="email" name="email" placeholder="your@email.com" required class="email-input">
    <button type="submit" class="btn btn-email">Subscribe →</button>
  </form>
  <!-- Formspree alternative: change action to https://formspree.io/f/YOUR_FORM_ID -->
</div>"""


# ── Main generator ────────────────────────────────────────────────────────────

def generate(story_json_path: Path = None, output_dir: Path = None) -> Path:
    """Generate 3 paginated HTML files. Returns path to index.html (page 1)."""
    if story_json_path is None:
        story_json_path = OUTPUT_DIR / "curated" / "latest.json"

    if not story_json_path.exists():
        print(f"Story file not found: {story_json_path}")
        print("Run curator.py first.")
        sys.exit(1)

    story = json.loads(story_json_path.read_text(encoding="utf-8"))

    if output_dir is None:
        ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = OUTPUT_DIR / f"mvp_{ts}" / "landing"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Shared metadata
    title        = _escape_html(story["title"])
    subreddit    = _escape_html(story["subreddit"])
    score        = f"{story['score']:,}"
    num_comments = f"{story.get('num_comments', 0):,}"
    source_url   = story.get("url", "#")
    curated_date = story.get("curated_at", "")[:10]
    year         = str(datetime.now().year)
    brand        = story.get("brand_name", "Forum Drama")

    affiliate_block = _get_affiliate_block(story["subreddit"])
    template        = TEMPLATE_PATH.read_text(encoding="utf-8")
    page_groups = _split_into_pages(story["part2_text"])
    total_pages = len(page_groups)
    first_page_path = output_dir / "index.html"

    for page_num, paras in enumerate(page_groups, start=1):

        filename  = _page_filename(page_num)
        out_path  = output_dir / filename

        page_indicator  = f'<span class="page-indicator">Page {page_num} of {total_pages}</span>'
        reveal_banner   = _REVEAL_BANNERS[min(page_num - 1, len(_REVEAL_BANNERS) - 1)]
        part2_html      = _paras_to_html(paras) if paras else "<p><em>Story continues below.</em></p>"

        prev_nav = _prev_nav(page_num)
        next_nav = _next_nav(page_num, total_pages)
        pagination_nav  = (
            f'<div class="pagination-nav">{prev_nav}{next_nav}</div>'
            if (prev_nav or next_nav) else ""
        )

        email_capture   = _EMAIL_CAPTURE if page_num == 2 else ""
        aff_block       = affiliate_block if page_num == total_pages else ""

        # Verdict section only on last page
        verdict_section = (
            '<div class="verdict-section">'
            '<h2>What\'s your verdict?</h2>'
            '<p>Was OP in the right? Drop your take in the comments on the video.</p>'
            '</div>'
        ) if page_num == total_pages else ""

        # CTA block only on last page
        cta_block = (
            f'<div class="cta-block">'
            f'<p>Watch Part 1 and drop your verdict 👇</p>'
            f'<a href="{source_url}" class="btn" target="_blank" rel="noopener">'
            f'Watch Part 1 on YouTube</a><br>'
            f'<a href="{source_url}" class="btn-secondary" target="_blank" rel="noopener">'
            f'Read the original post on Reddit →</a>'
            f'</div>'
        ) if page_num == total_pages else pagination_nav

        html = (
            template
            .replace("{{TITLE}}",          title)
            .replace("{{SUBREDDIT}}",       subreddit)
            .replace("{{SCORE}}",           score)
            .replace("{{NUM_COMMENTS}}",    num_comments)
            .replace("{{PAGE_INDICATOR}}", page_indicator)
            .replace("{{REVEAL_BANNER}}",  reveal_banner)
            .replace("{{PART2_PARAS}}",    part2_html)
            .replace("{{EMAIL_CAPTURE}}",  email_capture)
            .replace("{{AFFILIATE_BLOCK}}", aff_block)
            .replace("{{VERDICT_SECTION}}", verdict_section)
            .replace("{{PAGINATION_NAV}}", pagination_nav if page_num < total_pages else "")
            .replace("{{CTA_BLOCK}}",      cta_block)
            .replace("{{SOURCE_URL}}",     source_url)
            .replace("{{DATE}}",           curated_date)
            .replace("{{YEAR}}",           year)
            .replace("{{BRAND_NAME}}",     brand)
        )

        out_path.write_text(html, encoding="utf-8")
        print(f"Landing page {page_num}/{total_pages}: {out_path}")

    return first_page_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Part 2 landing pages (paginated)")
    parser.add_argument("--story",  metavar="PATH", help="Path to story JSON (default: latest)")
    parser.add_argument("--output", metavar="DIR",  help="Output directory")
    args = parser.parse_args()

    generate(
        story_json_path=Path(args.story)  if args.story  else None,
        output_dir     =Path(args.output) if args.output else None,
    )

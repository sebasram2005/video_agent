#!/usr/bin/env python3
"""
export_to_blog.py — Exports curated stories to the Next.js blog content directory
and optionally triggers a Netlify rebuild.

Usage:
  python export_to_blog.py                    # export latest curated story
  python export_to_blog.py --all              # export all curated stories
  python export_to_blog.py --trigger-build    # export + trigger Netlify rebuild
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_DIR      = Path(__file__).parent
CURATED_DIR  = BOT_DIR / "output" / "curated"
BLOG_CONTENT = Path(os.getenv("BLOG_CONTENT_DIR", str(BOT_DIR.parent / "reddit-stories-blog" / "content" / "stories")))


def export_story(json_path: Path) -> bool:
    if not json_path.exists():
        print(f"  [skip] not found: {json_path}")
        return False

    story = json.loads(json_path.read_text(encoding="utf-8"))
    dest  = BLOG_CONTENT / f"story_{story['id']}.json"

    BLOG_CONTENT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(json_path, dest)
    print(f"  [ok] exported: {dest.name}  (r/{story['subreddit']} · {story['score']:,} upvotes)")
    return True


def trigger_netlify_build() -> None:
    hook_url = os.getenv("NETLIFY_BUILD_HOOK_URL", "").strip()
    if not hook_url:
        print("  [skip] NETLIFY_BUILD_HOOK_URL not set — rebuild not triggered.")
        print("         Get your hook URL from: Netlify → Site → Deploys → Build hooks")
        return
    try:
        r = requests.post(hook_url, timeout=10)
        if r.status_code == 200:
            print("  [ok] Netlify rebuild triggered (~30s to go live).")
        else:
            print(f"  [warn] Netlify returned {r.status_code}")
    except Exception as e:
        print(f"  [error] Netlify trigger failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export curated stories to Next.js blog")
    parser.add_argument("--all",           action="store_true", help="Export all curated stories")
    parser.add_argument("--trigger-build", action="store_true", help="Trigger Netlify rebuild after export")
    args = parser.parse_args()

    print(f"\nExporting to: {BLOG_CONTENT}\n")

    if args.all:
        files = sorted(CURATED_DIR.glob("story_*.json"))
        if not files:
            print("  No curated stories found. Run curator.py first.")
            sys.exit(1)
        exported = sum(1 for f in files if export_story(f))
        print(f"\n  Exported {exported}/{len(files)} stories.")
    else:
        latest = CURATED_DIR / "latest.json"
        if not export_story(latest):
            print("  Run curator.py first to curate a story.")
            sys.exit(1)

    if args.trigger_build:
        trigger_netlify_build()

    print("\nDone. Run 'npm run build' in reddit-stories-blog/ to rebuild locally.\n")


if __name__ == "__main__":
    main()

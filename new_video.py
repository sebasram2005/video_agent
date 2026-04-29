#!/usr/bin/env python3
"""
new_video.py — Cura N historias y las encola para GitHub Actions.

GitHub Actions sube los videos con 4 horas de separación a lo largo del día.

Usage:
  python new_video.py                  # 1 historia
  python new_video.py --count 3        # 3 historias (recomendado, 1 por día)
  python new_video.py --count 3 --account A   # solo subreddits legales
  python new_video.py --count 3 --account B   # solo subreddits de relaciones
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from curator import curate

QUEUE_FILE = Path(__file__).parent / "data" / "upload_queue.json"


def git(args: list[str]) -> bool:
    result = subprocess.run(["git"] + args, cwd=Path(__file__).parent,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [git error] {result.stderr.strip()}")
        return False
    return True


def load_queue() -> list:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_queue(queue: list) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Curar historias y encolar para GitHub Actions")
    parser.add_argument("--count",   type=int, default=1, help="Número de historias a curar (default: 1)")
    parser.add_argument("--account", choices=["A", "B"], help="Filtrar por cuenta (A=legal, B=relaciones)")
    args = parser.parse_args()

    stories = []

    for i in range(args.count):
        print(f"\n{'═'*42}")
        print(f"  Historia {i+1}/{args.count} — Curando...")
        print(f"{'═'*42}\n")

        story = curate(account=args.account, auto=True)
        if not story:
            print(f"\n  No se encontró historia #{i+1}. Saltando.")
            break

        stories.append(story)
        print(f"  ✅ {story['subreddit']} — {story['title'][:65]}")

    if not stories:
        print("\n  No se encontraron historias válidas.")
        sys.exit(1)

    # Add to queue with scheduled upload times
    queue = load_queue()
    now   = datetime.now()

    # Schedule: 3 videos at 9am, 1pm, 5pm — find next available slots
    SLOTS_UTC = [13, 17, 21]  # 9am, 1pm, 5pm ET in UTC
    used_slots = {e.get("scheduled_hour") for e in queue if e.get("status") == "pending"}

    scheduled = []
    for story in stories:
        slot = next((s for s in SLOTS_UTC if s not in used_slots), SLOTS_UTC[len(scheduled) % len(SLOTS_UTC)])
        used_slots.add(slot)
        entry = {
            "story_id":       story["id"],
            "story_path":     f"output/curated/story_{story['id']}.json",
            "title":          story["title"][:80],
            "subreddit":      story["subreddit"],
            "score":          story["score"],
            "queued_at":      now.isoformat(),
            "scheduled_hour": slot,
            "status":         "pending",
        }
        queue.append(entry)
        scheduled.append(entry)

    save_queue(queue)

    print(f"\n{'═'*42}")
    print(f"  Encoladas {len(scheduled)} historia(s):")
    for e in scheduled:
        print(f"  • {e['subreddit']} → {e['scheduled_hour']-4}:00 ET")
    print(f"{'═'*42}\n")

    # Push everything to trigger GitHub Actions
    git(["add", "data/", "output/curated/"])
    git(["commit", "-m",
         f"queue: {len(scheduled)} stor{'y' if len(scheduled)==1 else 'ies'} — "
         + ", ".join(s['subreddit'] for s in scheduled)])
    ok = git(["push"])

    if ok:
        print("  ✅ Push exitoso — GitHub Actions procesará los videos en sus horarios.")
        print("     Estado: https://github.com/sebasram2005/video_agent/actions\n")
    else:
        print("  ❌ Push falló.")
        sys.exit(1)


if __name__ == "__main__":
    main()

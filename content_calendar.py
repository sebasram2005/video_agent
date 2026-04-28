"""
Content Calendar — Reddit Stories Bot

Manages a 30-day scheduling grid with subreddit rotation.
Interface is identical to the Emermédica bot calendar for pipeline compatibility.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from config import OUTPUT_DIR, SOURCE_SUBREDDITS

CALENDAR_FILE = OUTPUT_DIR / "calendar.json"

# Category labels map to subreddit groups
_CATEGORIES = {
    "betrayal":    ["AmItheAsshole", "AITAH", "survivinginfidelity", "relationship_advice"],
    "revenge":     ["ProRevenge", "MaliciousCompliance", "entitledparents"],
    "confession":  ["confessions", "offmychest", "TrueOffMyChest", "tifu"],
    "drama":       ["relationship_advice", "AITA", "BestofRedditorUpdates"],
}

# Posting schedule by videos-per-day count
_POST_TIMES = {
    1: ["12:00"],
    2: ["09:00", "19:00"],
    3: ["08:00", "13:00", "19:30"],
    4: ["08:00", "12:00", "16:00", "20:00"],
}


def generate_calendar(
    days: int = 30,
    videos_per_day: int = 2,
    start_date: datetime = None,
) -> list[dict]:
    vpd = max(1, min(videos_per_day, 4))

    if start_date is None:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    post_times   = _POST_TIMES[vpd]
    calendar     = []
    slot_id      = 1
    prev_cat     = None
    categories   = list(_CATEGORIES.keys())

    for day_offset in range(days):
        date = start_date + timedelta(days=day_offset)

        for slot_idx in range(vpd):
            # Rotate categories, never repeat consecutively
            available = [c for c in categories if c != prev_cat]
            category  = random.choice(available)
            subreddit = random.choice(_CATEGORIES[category])

            calendar.append({
                "id":             slot_id,
                "date":           date.strftime("%Y-%m-%d"),
                "weekday":        date.strftime("%A"),
                "post_time":      post_times[slot_idx],
                "category":       category,
                "subreddit_hint": subreddit,
                # Kept for pipeline compatibility with main.py
                "hook_category":  category,
                "pillar_label":   category.replace("_", " ").title(),
                "series":         f"r/{subreddit} stories",
                "audience":       "Tier-1 English speakers (US/UK/AU)",
                "status":         "pending",
                "output_file":    None,
            })

            prev_cat = category
            slot_id += 1

    return calendar


def load_calendar() -> list[dict]:
    if not CALENDAR_FILE.exists():
        return []
    return json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))


def save_calendar(calendar: list[dict]) -> None:
    CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_FILE.write_text(
        json.dumps(calendar, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_next_pending(calendar: list[dict]) -> dict | None:
    return next((s for s in calendar if s["status"] == "pending"), None)


def mark_generated(calendar: list[dict], slot_id: int, output_file: str) -> None:
    for slot in calendar:
        if slot["id"] == slot_id:
            slot["status"]      = "generated"
            slot["output_file"] = output_file
            break


def mark_published(calendar: list[dict], slot_id: int) -> None:
    for slot in calendar:
        if slot["id"] == slot_id:
            slot["status"] = "published"
            break


def print_calendar_summary(calendar: list[dict], show_days: int = 14) -> None:
    print("\n" + "=" * 66)
    print(f"  REDDIT STORIES BOT — Content Calendar ({show_days} days)")
    print("=" * 66)

    status_icon  = {"pending": "[ ]", "generated": "[G]", "published": "[P]"}
    current_date = None
    shown        = 0

    for slot in calendar:
        if shown >= show_days * 4:
            break
        if slot["date"] != current_date:
            current_date = slot["date"]
            print(f"\n  {slot['date']} ({slot['weekday'][:3]})")
            shown += 1

        icon = status_icon.get(slot["status"], "[ ]")
        print(
            f"    {icon} {slot['post_time']}  "
            f"[{slot['category']:<12}]  "
            f"r/{slot['subreddit_hint']}"
        )

    pending   = sum(1 for s in calendar if s["status"] == "pending")
    generated = sum(1 for s in calendar if s["status"] == "generated")
    published = sum(1 for s in calendar if s["status"] == "published")

    print(f"\n  Total: {len(calendar)} slots  |  "
          f"Pending: {pending}  |  Generated: {generated}  |  Published: {published}")
    print("=" * 66 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reddit Stories Bot — Content Calendar")
    parser.add_argument("--new",  action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--videos-per-day", type=int, default=2, choices=[1, 2, 3, 4], dest="vpd")
    args = parser.parse_args()

    if args.new or not CALENDAR_FILE.exists():
        cal = generate_calendar(args.days, videos_per_day=args.vpd)
        save_calendar(cal)
        print_calendar_summary(cal)
    elif args.show:
        cal = load_calendar()
        print_calendar_summary(cal, show_days=args.days)

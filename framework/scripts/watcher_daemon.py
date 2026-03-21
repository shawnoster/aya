#!/usr/bin/env python3
"""Out-of-session watcher daemon — called by systemd timer.

Runs one poll cycle: checks all non-session-required watches and due reminders,
writes alerts to alerts.json for next session pickup.

Usage:
    watcher_daemon.py              # normal run
    watcher_daemon.py --verbose    # show poll details
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "assistant" / "memory"
LOG_FILE = LOG_DIR / "watcher.log"
LOCAL_TZ = ZoneInfo("America/Denver")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout) if "--verbose" in sys.argv else logging.NullHandler(),
    ],
)
log = logging.getLogger("assistant-watcher")


def main() -> None:
    # Import scheduler from same directory
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scheduler import load_items, save_items, load_alerts, save_alerts, poll_watch
    from scheduler import _evaluate_auto_remove, _format_watch_alert, _new_id

    now = datetime.now(LOCAL_TZ)
    items = load_items()
    alerts = load_alerts()
    items_modified = False
    alerts_modified = False

    from datetime import timedelta

    watch_count = 0
    alert_count = 0

    for item in items:
        # Poll watches that don't need a session
        if item["type"] == "watch" and item["status"] == "active" and not item.get("session_required"):
            last = item.get("last_checked_at")
            interval = item.get("poll_interval_minutes", 30)
            if last:
                next_check = datetime.fromisoformat(last) + timedelta(minutes=interval)
                if now < next_check:
                    continue

            watch_count += 1
            new_state, changed = poll_watch(item)

            if new_state is not None:
                item["last_checked_at"] = now.isoformat()
                item["last_state"] = new_state
                items_modified = True

                if changed:
                    msg = _format_watch_alert(item, new_state)
                    alert = {
                        "id": _new_id(),
                        "source_item_id": item["id"],
                        "created_at": now.isoformat(),
                        "message": msg,
                        "details": new_state,
                        "seen": False,
                    }
                    alerts.append(alert)
                    alerts_modified = True
                    alert_count += 1
                    log.info("ALERT %s — %s", item["id"][:8], msg[:80])

                if _evaluate_auto_remove(item, new_state):
                    item["status"] = "dismissed"
                    items_modified = True
                    log.info("AUTO-DISMISS %s (condition met)", item["id"][:8])
            else:
                log.warning("POLL-FAIL %s (%s)", item["id"][:8], item.get("provider"))

        # Check due reminders
        elif item["type"] == "reminder" and item["status"] == "pending":
            due = datetime.fromisoformat(item["due_at"])
            if due <= now:
                existing_sources = {a["source_item_id"] for a in alerts if not a.get("seen")}
                if item["id"] not in existing_sources:
                    alert = {
                        "id": _new_id(),
                        "source_item_id": item["id"],
                        "created_at": now.isoformat(),
                        "message": f"Reminder due: {item['message']}",
                        "details": {"due_at": item["due_at"]},
                        "seen": False,
                    }
                    alerts.append(alert)
                    alerts_modified = True
                    alert_count += 1
                    log.info("REMINDER-DUE %s — %s", item["id"][:8], item["message"][:60])

    if items_modified:
        save_items(items)
    if alerts_modified:
        save_alerts(alerts)

    log.info("Poll cycle: %d watches checked, %d alerts generated", watch_count, alert_count)


if __name__ == "__main__":
    main()

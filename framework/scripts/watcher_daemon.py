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
    # Import scheduler from same directory — delegates to run_poll which
    # holds a single exclusive lock for the entire load→poll→save cycle.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scheduler import run_poll

    quiet = "--verbose" not in sys.argv
    log.info("Starting poll cycle")
    run_poll(quiet=quiet)
    log.info("Poll cycle complete")


if __name__ == "__main__":
    main()

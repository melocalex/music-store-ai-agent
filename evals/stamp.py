"""What a report or transcript was made from: the commit, the reference day, and when."""

import subprocess
from datetime import date, datetime
from functools import cache

from music_store_agent.clock import STORE_ZONE, pinned_day
from music_store_agent.db import last_order_date, load_database


def git_commit() -> str:
    try:
        output = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"
    return output.strip() or "unknown"


@cache
def reference_day() -> date:
    """The pinned store day the scenarios are written for: the day after the last order."""
    return pinned_day(last_order_date(load_database()))


def written_at() -> str:
    return datetime.now(STORE_ZONE).isoformat(timespec="seconds")

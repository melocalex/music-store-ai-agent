"""Daily turn counter. The quota day follows the real local date, not the pinned clock.

This file and the handoff log are the only local writes. A lock keeps two Streamlit
sessions from reading the same count, and os.replace makes each write atomic.
"""

import json
import os
import threading
from datetime import date
from pathlib import Path

_LOCK = threading.Lock()


def reserve(path: Path, day: date, limit: int) -> bool:
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _read(path)
        if current.get("day") != day.isoformat():
            current = {"day": day.isoformat(), "count": 0}
        count = int(str(current["count"]))
        if count >= limit:
            return False
        current["count"] = count + 1
        _write(path, current)
        return True


def _read(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _write(path: Path, payload: dict[str, object]) -> None:
    scratch = path.with_suffix(path.suffix + ".tmp")
    scratch.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(scratch, path)

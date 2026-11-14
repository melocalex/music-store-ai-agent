"""Daily turn counter. The quota day follows the real local date, not the pinned clock."""

import json
from datetime import date
from pathlib import Path


def reserve(path: Path, day: date, limit: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read(path)
    if current.get("day") != day.isoformat():
        current = {"day": day.isoformat(), "count": 0}
    count = int(current["count"])
    if count >= limit:
        _write(path, current)
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
    path.write_text(json.dumps(payload), encoding="utf-8")

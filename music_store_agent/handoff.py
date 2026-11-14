"""Append a handoff row. The file is local and holds no contact details."""

import json
from datetime import datetime
from pathlib import Path

from music_store_agent.constants import HANDOFF_SUMMARY_CAP
from music_store_agent.textutil import mask_pii


def write_handoff(
    path: Path,
    when: datetime,
    reason: str,
    summary: str,
    customer_id: int | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": when.isoformat(timespec="seconds"),
        "reason": reason,
        "summary": mask_pii(summary)[:HANDOFF_SUMMARY_CAP],
        "verified_customer_id": customer_id,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

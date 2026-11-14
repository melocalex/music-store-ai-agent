"""Pinned requirement files use a single version each."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINNED = ("requirements.txt", "requirements-dev.txt")


def test_every_requirement_is_pinned_to_one_version() -> None:
    for name in PINNED:
        lines = [line.strip() for line in (ROOT / name).read_text().splitlines() if line.strip()]
        assert lines, name
        assert all("==" in line and "<" not in line and ">" not in line for line in lines), name

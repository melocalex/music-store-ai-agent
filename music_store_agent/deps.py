"""Dependencies injected into every tool. The model cannot set them."""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from music_store_agent.clock import Clock, clock_at, pinned_clock, pinned_day, real_clock
from music_store_agent.constants import CLOCK_ENV, REAL_CLOCK_VALUE, TODAY_ENV
from music_store_agent.db import last_order_date
from music_store_agent.ledger import Ledger
from music_store_agent.orders import Identity


@dataclass(frozen=True)
class StorePaths:
    handoff: Path
    usage: Path


@dataclass
class Counters:
    validator_firings: int = 0
    validator_catches: int = 0


@dataclass
class Deps:
    conn: sqlite3.Connection
    clock: Clock
    ledger: Ledger
    paths: StorePaths
    identity: Identity
    counters: Counters = field(default_factory=Counters)


def make_deps(
    conn: sqlite3.Connection,
    *,
    today: date | None = None,
    real: bool = False,
    phone: str | None = None,
    handoff_path: Path | None = None,
    usage_path: Path | None = None,
) -> Deps:
    root = Path("var")
    handoff = handoff_path or root / "handoffs.jsonl"
    usage = usage_path or root / "daily_turns.json"
    paths = StorePaths(handoff, usage)
    identity = Identity(sender_phone=phone)
    clock = build_clock(conn, today=today, real=real)
    return Deps(conn, clock, Ledger(), paths, identity, Counters())


def build_clock(conn: sqlite3.Connection, *, today: date | None, real: bool) -> Clock:
    """Pinned by default. A chosen date is fixed, unless it is the pinned day itself."""
    last = last_order_date(conn)
    chosen = today if today is not None else _env_today()
    if chosen is None and (real or _env_real()):
        return real_clock()
    if chosen is None or chosen == pinned_day(last):
        return pinned_clock(last)
    return clock_at(chosen)


def _env_real() -> bool:
    return os.environ.get(CLOCK_ENV, "").strip().casefold() == REAL_CLOCK_VALUE


def _env_today() -> date | None:
    raw = os.environ.get(TODAY_ENV, "").strip()
    if not raw:
        return None
    return date.fromisoformat(raw)

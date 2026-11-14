"""Handoff rows hold no contact details, and the reply says when the team picks up."""

import json
from datetime import date, datetime, time

from music_store_agent.clock import STORE_ZONE, clock_at
from music_store_agent.constants import (
    HANDOFF_REASON_CAP,
    HANDOFF_SUMMARY_CAP,
    SATURDAY_CLOSE,
    TEAM_REPLY_BUSINESS_HOURS,
    WEEKDAY_OPEN,
)
from music_store_agent.handoff import HandoffCase, reply_window, write_handoff

MONDAY = date(2026, 3, 23)
SATURDAY = date(2026, 3, 21)


def test_reason_and_summary_are_masked_and_capped(tmp_path) -> None:
    path = tmp_path / "handoffs.jsonl"
    reason = "troca lucas.mendes@jmail.com " + "x" * HANDOFF_REASON_CAP
    summary = "ligar (67) 99812-3456 " + "y" * HANDOFF_SUMMARY_CAP
    write_handoff(path, clock_at(MONDAY).now(), HandoffCase(reason, summary, "ABCD1234"))
    row = json.loads(path.read_text(encoding="utf-8"))
    assert "@" not in row["reason"]
    assert "99812" not in row["summary"]
    assert len(row["reason"]) <= HANDOFF_REASON_CAP
    assert len(row["summary"]) <= HANDOFF_SUMMARY_CAP


def test_reply_window_names_the_next_opening_when_closed() -> None:
    open_now = reply_window(clock_at(MONDAY).now())
    assert f"{TEAM_REPLY_BUSINESS_HOURS} horas úteis" in open_now
    assert "fechada" not in open_now
    after_close = time(SATURDAY_CLOSE.hour, SATURDAY_CLOSE.minute + 1)
    closed = reply_window(clock_at(SATURDAY, after_close).now())
    assert "fechada" in closed
    assert f"{MONDAY.isoformat()} {WEEKDAY_OPEN.strftime('%H:%M')}" in closed


def test_a_row_keeps_the_real_time_the_protocol_and_the_order(tmp_path) -> None:
    path = tmp_path / "handoffs.jsonl"
    pinned = clock_at(MONDAY).now()
    case = HandoffCase("return_request", "Pedido 7: troca.", "ABCD1234", 14, 7)
    write_handoff(path, pinned, case)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["at"] == pinned.isoformat(timespec="seconds")
    assert datetime.fromisoformat(row["logged_at"]).date() == datetime.now(STORE_ZONE).date()
    assert row["protocol"] == "ABCD1234"
    assert row["verified_customer_id"] == 14
    assert row["order_id"] == 7

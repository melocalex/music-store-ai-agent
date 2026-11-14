"""Pinned clock, inclusive hours, and the fixed holiday list."""

from datetime import date, time

from music_store_agent.clock import (
    clock_at,
    closed_reason,
    holiday_name,
    is_open_at,
    next_opening_label,
    pinned_day,
)
from music_store_agent.constants import FIXED_HOLIDAYS, PINNED_DAY_OFFSET, REFERENCE_TIME
from music_store_agent.db import last_order_date, load_database

PINNED = date(2026, 3, 23)


def test_pinned_day_is_the_day_after_the_last_order() -> None:
    conn = load_database()
    last = last_order_date(conn)
    assert last == date(2026, 3, 22)
    assert pinned_day(last) == last.fromordinal(last.toordinal() + PINNED_DAY_OFFSET)
    assert pinned_day(last) == PINNED
    moment = clock_at(PINNED, pinned=True).now()
    assert moment.hour == REFERENCE_TIME.hour
    assert is_open_at(moment)


def test_hours_are_inclusive_and_sunday_is_closed() -> None:
    monday = date(2026, 3, 23)
    saturday = date(2026, 3, 21)
    sunday = date(2026, 3, 22)
    assert closed_reason(monday, time(18, 0)) is None
    assert closed_reason(monday, time(18, 1)) == "fora do expediente"
    assert closed_reason(saturday, time(13, 0)) is None
    assert closed_reason(saturday, time(13, 1)) == "fora do expediente"
    assert closed_reason(sunday, time(10, 0)) == "domingo"


def test_fixed_holidays_are_closed_and_the_next_opening_skips_them() -> None:
    santo = date(2026, 6, 13)
    assert holiday_name(santo) == "Santo Antônio"
    assert closed_reason(santo, time(10, 0)) == "Santo Antônio"
    assert next_opening_label(santo, time(10, 0)).startswith("2026-06-15")
    assert holiday_name(date(2026, 8, 26)) == "Aniversário de Campo Grande"
    assert holiday_name(date(2026, 10, 11)) == "Criação do estado de Mato Grosso do Sul"
    assert len(FIXED_HOLIDAYS) == 11
    neighbor = date(2026, 6, 12)
    assert closed_reason(neighbor, time(10, 0)) is None

"""Clock modes, inclusive hours, the fixed holiday list, and the hours tool text."""

from datetime import date, datetime, time, timedelta

from music_store_agent.clock import (
    clock_at,
    closed_reason,
    holiday_name,
    next_opening_label,
    pinned_day,
    weekday_name,
)
from music_store_agent.constants import (
    CLOCK_FIXED,
    CLOCK_PINNED,
    CLOCK_REAL,
    FIXED_HOLIDAYS,
    PINNED_DAY_OFFSET,
    REFERENCE_TIME,
    SATURDAY_CLOSE,
    SATURDAY_OPEN,
    WEEKDAY_CLOSE,
    WEEKDAY_OPEN,
)
from music_store_agent.db import last_order_date, load_database
from music_store_agent.deps import build_clock
from music_store_agent.hours import hours_answer, parse_asked_day

MONDAY = date(2026, 3, 23)
SATURDAY = date(2026, 3, 21)
NEXT_SATURDAY = date(2026, 3, 28)
SUNDAY = date(2026, 3, 22)
OUT_OF_HOURS = "fora do expediente"


def _shift(at: time, minutes: int) -> time:
    return (datetime.combine(MONDAY, at) + timedelta(minutes=minutes)).time()


def test_pinned_day_is_the_day_after_the_last_order() -> None:
    conn = load_database()
    last = last_order_date(conn)
    clock = build_clock(conn, today=None, real=False)
    assert clock.mode == CLOCK_PINNED
    assert (clock.today() - last).days == PINNED_DAY_OFFSET
    assert clock.now().time() == REFERENCE_TIME


def test_a_chosen_date_is_fixed_unless_it_is_the_pinned_day() -> None:
    conn = load_database()
    pinned = pinned_day(last_order_date(conn))
    assert build_clock(conn, today=pinned, real=False).mode == CLOCK_PINNED
    assert build_clock(conn, today=pinned + timedelta(days=1), real=False).mode == CLOCK_FIXED
    assert build_clock(conn, today=None, real=True).mode == CLOCK_REAL
    labels = {clock_at(MONDAY, mode=mode).label for mode in (CLOCK_PINNED, CLOCK_FIXED, CLOCK_REAL)}
    assert len(labels) == 3


def test_opening_and_closing_minutes_are_inclusive() -> None:
    assert closed_reason(MONDAY, _shift(WEEKDAY_OPEN, -1)) == OUT_OF_HOURS
    assert closed_reason(MONDAY, WEEKDAY_OPEN) is None
    assert closed_reason(MONDAY, WEEKDAY_CLOSE) is None
    assert closed_reason(MONDAY, _shift(WEEKDAY_CLOSE, 1)) == OUT_OF_HOURS
    assert closed_reason(SATURDAY, _shift(SATURDAY_OPEN, -1)) == OUT_OF_HOURS
    assert closed_reason(SATURDAY, SATURDAY_OPEN) is None
    assert closed_reason(SATURDAY, SATURDAY_CLOSE) is None
    assert closed_reason(SATURDAY, _shift(SATURDAY_CLOSE, 1)) == OUT_OF_HOURS
    assert closed_reason(SUNDAY, REFERENCE_TIME) == weekday_name(SUNDAY)


def test_every_fixed_holiday_is_closed_and_its_neighbours_are_not() -> None:
    for month, day, name, _scope in FIXED_HOLIDAYS:
        holiday = date(2026, month, day)
        assert holiday_name(holiday) == name
        assert closed_reason(holiday, REFERENCE_TIME) == name
    assert holiday_name(date(2026, 11, 20)) == "Dia Nacional de Zumbi e da Consciência Negra"
    santo = date(2026, 6, 13)
    assert next_opening_label(santo, REFERENCE_TIME).startswith("2026-06-15")
    assert closed_reason(santo - timedelta(days=1), REFERENCE_TIME) is None


def test_today_uses_the_current_time() -> None:
    evening = hours_answer(clock_at(MONDAY, _shift(WEEKDAY_CLOSE, 90)).now())
    assert weekday_name(MONDAY) in evening
    assert "09:00 às 18:00" in evening
    assert "loja está fechada" in evening
    morning = hours_answer(clock_at(MONDAY).now())
    assert "loja está aberta" in morning


def test_another_day_gives_its_hours_without_a_current_time() -> None:
    now = clock_at(MONDAY).now()
    saturday = hours_answer(now, NEXT_SATURDAY)
    assert weekday_name(NEXT_SATURDAY) in saturday
    assert f"{SATURDAY_OPEN.strftime('%H:%M')} às {SATURDAY_CLOSE.strftime('%H:%M')}" in saturday
    assert "Agora são" not in saturday
    holiday = hours_answer(now, date(2026, 6, 13))
    assert "fechada nesse dia (Santo Antônio)" in holiday
    assert "2026-06-15" in holiday
    assert "já passou" in hours_answer(now, SATURDAY)


def test_day_and_month_roll_forward_to_the_next_occurrence() -> None:
    today = date(2026, 11, 14)
    assert parse_asked_day("01/01", today) == date(2027, 1, 1)
    assert parse_asked_day("14/11", today) == today
    assert parse_asked_day("20/11", today) == date(2026, 11, 20)
    assert parse_asked_day("2026-03-21", today) == SATURDAY
    assert parse_asked_day("31/02", today) is None
    assert parse_asked_day("amanhã", today) is None

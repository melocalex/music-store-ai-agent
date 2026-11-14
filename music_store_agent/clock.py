"""Store clock in America/Campo_Grande, pinned to the day after the last order."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from music_store_agent.constants import (
    FIXED_HOLIDAYS,
    HOLIDAY_LOOKAHEAD_DAYS,
    PINNED_DAY_OFFSET,
    REFERENCE_TIME,
    SATURDAY,
    SATURDAY_CLOSE,
    SATURDAY_OPEN,
    STORE_TIMEZONE,
    SUNDAY,
    WEEKDAY_CLOSE,
    WEEKDAY_OPEN,
)

STORE_ZONE = ZoneInfo(STORE_TIMEZONE)


@dataclass(frozen=True)
class Clock:
    """`moment` None means the real clock. Otherwise the instant is fixed."""

    moment: datetime | None
    pinned: bool

    def now(self) -> datetime:
        if self.moment is None:
            return datetime.now(STORE_ZONE)
        return self.moment.astimezone(STORE_ZONE)

    def today(self) -> date:
        return self.now().date()


def pinned_day(last_order: date) -> date:
    return last_order + timedelta(days=PINNED_DAY_OFFSET)


def clock_at(day: date, at: time = REFERENCE_TIME, *, pinned: bool) -> Clock:
    moment = datetime.combine(day, at, tzinfo=STORE_ZONE)
    return Clock(moment=moment, pinned=pinned)


def real_clock() -> Clock:
    return Clock(moment=None, pinned=False)


def holiday_name(day: date) -> str | None:
    for month, dom, name, _scope in FIXED_HOLIDAYS:
        if day.month == month and day.day == dom:
            return name
    return None


def hours_for(day: date) -> tuple[time, time]:
    if day.weekday() == SATURDAY:
        return SATURDAY_OPEN, SATURDAY_CLOSE
    return WEEKDAY_OPEN, WEEKDAY_CLOSE


def closed_reason(day: date, at: time) -> str | None:
    name = holiday_name(day)
    if name is not None:
        return name
    if day.weekday() == SUNDAY:
        return "domingo"
    start, end = hours_for(day)
    if at < start or at > end:
        return "fora do expediente"
    return None


def is_open_at(moment: datetime) -> bool:
    local = moment.astimezone(STORE_ZONE)
    return closed_reason(local.date(), local.time().replace(microsecond=0)) is None


def next_opening_label(day: date, at: time) -> str:
    if holiday_name(day) is None and day.weekday() != SUNDAY:
        start, _end = hours_for(day)
        if at < start:
            return f"{day.isoformat()} {start.strftime('%H:%M')}"
    cursor = day + timedelta(days=1)
    for _ in range(HOLIDAY_LOOKAHEAD_DAYS):
        if holiday_name(cursor) is None and cursor.weekday() != SUNDAY:
            start, _end = hours_for(cursor)
            return f"{cursor.isoformat()} {start.strftime('%H:%M')}"
        cursor += timedelta(days=1)
    return "além do calendário carregado"


def holiday_lines() -> str:
    parts = [f"{day:02d}/{month:02d} {name}" for month, day, name, _scope in FIXED_HOLIDAYS]
    return ", ".join(parts)

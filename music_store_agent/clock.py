"""Store clock in America/Campo_Grande, pinned to the day after the last order by default."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from music_store_agent.constants import (
    CARNIVAL,
    CARNIVAL_FROM_EASTER,
    CLOCK_FIXED,
    CLOCK_LABELS,
    CLOCK_PINNED,
    CLOCK_REAL,
    CORPUS_CHRISTI,
    CORPUS_CHRISTI_FROM_EASTER,
    FIXED_HOLIDAYS,
    GOOD_FRIDAY,
    GOOD_FRIDAY_FROM_EASTER,
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
WEEKDAY_NAMES = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


@dataclass(frozen=True)
class Clock:
    """`moment` None means the real clock. Otherwise the instant is fixed.

    `mode` is pinned (the day after the last order), fixed (a date chosen by the operator),
    or real.
    """

    moment: datetime | None
    mode: str

    def now(self) -> datetime:
        if self.moment is None:
            return datetime.now(STORE_ZONE)
        return self.moment.astimezone(STORE_ZONE)

    def today(self) -> date:
        return self.now().date()

    @property
    def label(self) -> str:
        return CLOCK_LABELS[self.mode]


def pinned_day(last_order: date) -> date:
    return last_order + timedelta(days=PINNED_DAY_OFFSET)


def clock_at(day: date, at: time = REFERENCE_TIME, *, mode: str = CLOCK_FIXED) -> Clock:
    moment = datetime.combine(day, at, tzinfo=STORE_ZONE)
    return Clock(moment=moment, mode=mode)


def pinned_clock(last_order: date) -> Clock:
    return clock_at(pinned_day(last_order), mode=CLOCK_PINNED)


def real_clock() -> Clock:
    return Clock(moment=None, mode=CLOCK_REAL)


def weekday_name(day: date) -> str:
    return WEEKDAY_NAMES[day.weekday()]


def holiday_name(day: date) -> str | None:
    """A day the store closes: a fixed holiday or Good Friday."""
    for month, dom, name, _scope in FIXED_HOLIDAYS:
        if day.month == month and day.day == dom:
            return name
    if (day - easter(day.year)).days == GOOD_FRIDAY_FROM_EASTER:
        return GOOD_FRIDAY
    return None


def unset_hours_holiday(day: date) -> str | None:
    """Carnival and Corpus Christi: holidays for some, with no store hours set for them."""
    from_easter = (day - easter(day.year)).days
    if from_easter in CARNIVAL_FROM_EASTER:
        return CARNIVAL
    if from_easter == CORPUS_CHRISTI_FROM_EASTER:
        return CORPUS_CHRISTI
    return None


def moving_dates(year: int) -> dict[str, tuple[date, ...]]:
    sunday = easter(year)
    return {
        GOOD_FRIDAY: (sunday + timedelta(days=GOOD_FRIDAY_FROM_EASTER),),
        CARNIVAL: tuple(sunday + timedelta(days=offset) for offset in CARNIVAL_FROM_EASTER),
        CORPUS_CHRISTI: (sunday + timedelta(days=CORPUS_CHRISTI_FROM_EASTER),),
    }


def easter(year: int) -> date:
    """Easter Sunday in the Gregorian calendar (the anonymous, or Meeus, algorithm)."""
    golden = year % 19
    century, year_of_century = divmod(year, 100)
    leap_centuries, century_rest = divmod(century, 4)
    correction = (century + 8) // 25
    moon = (century - correction + 1) // 3
    epact = (19 * golden + century - leap_centuries - moon + 15) % 30
    leap_years, year_rest = divmod(year_of_century, 4)
    weekday = (32 + 2 * century_rest + 2 * leap_years - epact - year_rest) % 7
    shift = (golden + 11 * epact + 22 * weekday) // 451
    month, day = divmod(epact + weekday - 7 * shift + 114, 31)
    return date(year, month, day + 1)


def hours_for(day: date) -> tuple[time, time]:
    if day.weekday() == SATURDAY:
        return SATURDAY_OPEN, SATURDAY_CLOSE
    return WEEKDAY_OPEN, WEEKDAY_CLOSE


def day_closed_reason(day: date) -> str | None:
    """Closed all day: a fixed holiday or a Sunday."""
    name = holiday_name(day)
    if name is not None:
        return name
    if day.weekday() == SUNDAY:
        return WEEKDAY_NAMES[SUNDAY]
    return None


def closed_reason(day: date, at: time) -> str | None:
    whole_day = day_closed_reason(day)
    if whole_day is not None:
        return whole_day
    start, end = hours_for(day)
    if at < start or at > end:
        return "fora do expediente"
    return None


def is_open_at(moment: datetime) -> bool:
    local = moment.astimezone(STORE_ZONE)
    return closed_reason(local.date(), local.time().replace(microsecond=0)) is None


def next_opening_label(day: date, at: time) -> str:
    if day_closed_reason(day) is None:
        start, _end = hours_for(day)
        if at < start:
            return f"{day.isoformat()} {start.strftime('%H:%M')}"
    cursor = day + timedelta(days=1)
    for _ in range(HOLIDAY_LOOKAHEAD_DAYS):
        if day_closed_reason(cursor) is None:
            start, _end = hours_for(cursor)
            return f"{cursor.isoformat()} {start.strftime('%H:%M')}"
        cursor += timedelta(days=1)
    return "além do calendário carregado"


def holiday_lines() -> str:
    parts = [f"{day:02d}/{month:02d} {name}" for month, day, name, _scope in FIXED_HOLIDAYS]
    return ", ".join(parts)

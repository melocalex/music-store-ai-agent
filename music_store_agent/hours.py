"""Opening hours, including the fixed holiday list."""

import re
from datetime import date, datetime, timedelta

from music_store_agent.clock import (
    STORE_ZONE,
    closed_reason,
    day_closed_reason,
    holiday_lines,
    hours_for,
    moving_dates,
    next_opening_label,
    unset_hours_holiday,
    weekday_name,
)
from music_store_agent.constants import (
    CARNIVAL,
    CORPUS_CHRISTI,
    GOOD_FRIDAY,
    LANDLINE_PHONE,
    WHATSAPP_PHONE,
)
from music_store_agent.textutil import fold

_DAY_MONTH = re.compile(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}|\d{2}))?")
_CENTURY = 100
_CENTURY_START = 2000
_WEEK = 7
_RELATIVE_DAYS = {"hoje": 0, "amanha": 1, "depois de amanha": 2}
# Folded weekday names, Monday first, as date.weekday() counts them.
_WEEKDAY_STEMS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_WEEKDAY = re.compile(
    r"(?:(?:n[oa]|est[ea])\s+)?(?P<next>proxim[oa]\s+)?"
    rf"(?P<day>{'|'.join(_WEEKDAY_STEMS)})(?:[- ]feira)?(?P<coming>\s+que\s+vem)?"
)


def hours_answer(now: datetime, asked: date | None = None) -> str:
    """The hours of the asked day, plus open or closed right now when the day is today."""
    local = now.astimezone(STORE_ZONE)
    today = local.date()
    day = asked or today
    lines = [f"Data consultada: {weekday_name(day)}, {day.isoformat()}."]
    whole_day = day_closed_reason(day)
    lines.append(_day_line(day, whole_day))
    if day == today:
        lines.append(_right_now(local))
    elif day < today:
        lines.append("Essa data já passou.")
    elif whole_day is not None:
        lines.append(f"Próxima abertura depois disso: {next_opening_label(day, local.time())}.")
    lines.append(f"WhatsApp {WHATSAPP_PHONE}. Telefone fixo {LANDLINE_PHONE}.")
    lines.append("Feriados fixos: " + holiday_lines() + ".")
    lines.append(_moving_line(day.year))
    return "\n".join(lines)


def _day_line(day: date, whole_day: str | None) -> str:
    if whole_day is not None:
        return f"A loja fica fechada nesse dia ({whole_day})."
    start, end = (moment.strftime("%H:%M") for moment in hours_for(day))
    unset = unset_hours_holiday(day)
    if unset is None:
        return f"Horário nesse dia: {start} às {end}."
    return (
        f"Essa data é {unset}. O horário da loja nesse dia não está definido (o normal seria "
        f"{start} às {end}): não confirme, encaminhe para a equipe."
    )


def _moving_line(year: int) -> str:
    dates = moving_dates(year)
    shown = {name: " e ".join(d.strftime("%d/%m") for d in days) for name, days in dates.items()}
    return (
        f"Feriados móveis de {year}: {GOOD_FRIDAY} ({shown[GOOD_FRIDAY]}), loja fechada; "
        f"{CARNIVAL} ({shown[CARNIVAL]}) e {CORPUS_CHRISTI} ({shown[CORPUS_CHRISTI]}), "
        "horário a confirmar com a equipe."
    )


def _right_now(local: datetime) -> str:
    at = local.time().replace(second=0, microsecond=0)
    reason = closed_reason(local.date(), at)
    clock = at.strftime("%H:%M")
    if reason is None:
        return f"Agora são {clock} e a loja está aberta."
    opening = next_opening_label(local.date(), at)
    return f"Agora são {clock} e a loja está fechada ({reason}). Próxima abertura: {opening}."


def parse_asked_day(raw: str | None, today: date) -> date | None:
    """YYYY-MM-DD, DD/MM/YYYY, DD/MM, "hoje", "amanhã", or a weekday such as "sábado"."""
    if raw is None or not raw.strip():
        return None
    text = fold(raw.strip())
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    if text in _RELATIVE_DAYS:
        return today + timedelta(days=_RELATIVE_DAYS[text])
    weekday = _WEEKDAY.fullmatch(text)
    if weekday is not None:
        ahead = (_WEEKDAY_STEMS.index(weekday.group("day")) - today.weekday()) % _WEEK
        if ahead == 0 and (weekday.group("next") or weekday.group("coming")):
            ahead = _WEEK
        return today + timedelta(days=ahead)
    return _day_month(text, today)


def _day_month(text: str, today: date) -> date | None:
    """DD/MM without a year means the next time that date comes, today included."""
    match = _DAY_MONTH.fullmatch(text)
    if match is None:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    if match.group(3):
        year = int(match.group(3))
        try:
            return date(year if year >= _CENTURY else _CENTURY_START + year, month, day)
        except ValueError:
            return None
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None

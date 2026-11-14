"""Opening hours, including the fixed holiday list."""

import re
from datetime import date, datetime

from music_store_agent.clock import (
    STORE_ZONE,
    closed_reason,
    day_closed_reason,
    holiday_lines,
    hours_for,
    next_opening_label,
    weekday_name,
)
from music_store_agent.constants import LANDLINE_PHONE, WHATSAPP_PHONE

_DAY_MONTH = re.compile(r"(\d{1,2})[/-](\d{1,2})")


def hours_answer(now: datetime, asked: date | None = None) -> str:
    """The hours of the asked day, plus open or closed right now when the day is today."""
    local = now.astimezone(STORE_ZONE)
    today = local.date()
    day = asked or today
    lines = [f"Data consultada: {weekday_name(day)}, {day.isoformat()}."]
    whole_day = day_closed_reason(day)
    if whole_day is None:
        start, end = hours_for(day)
        lines.append(f"Horário nesse dia: {start.strftime('%H:%M')} às {end.strftime('%H:%M')}.")
    else:
        lines.append(f"A loja fica fechada nesse dia ({whole_day}).")
    if day == today:
        lines.append(_right_now(local))
    elif day < today:
        lines.append("Essa data já passou.")
    elif whole_day is not None:
        lines.append(f"Próxima abertura depois disso: {next_opening_label(day, local.time())}.")
    lines.append(f"WhatsApp {WHATSAPP_PHONE}. Telefone fixo {LANDLINE_PHONE}.")
    lines.append("Feriados fixos: " + holiday_lines() + ".")
    lines.append("Carnaval, Sexta-feira Santa e Corpus Christi não estão na lista.")
    return "\n".join(lines)


def _right_now(local: datetime) -> str:
    at = local.time().replace(second=0, microsecond=0)
    reason = closed_reason(local.date(), at)
    clock = at.strftime("%H:%M")
    if reason is None:
        return f"Agora são {clock} e a loja está aberta."
    opening = next_opening_label(local.date(), at)
    return f"Agora são {clock} e a loja está fechada ({reason}). Próxima abertura: {opening}."


def parse_asked_day(raw: str | None, today: date) -> date | None:
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return _day_month(text, today)


def _day_month(text: str, today: date) -> date | None:
    """DD/MM without a year means the next time that date comes, today included."""
    match = _DAY_MONTH.fullmatch(text)
    if match is None:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None

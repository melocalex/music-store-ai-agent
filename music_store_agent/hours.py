"""Opening hours, including the fixed holiday list."""

from datetime import date, datetime

from music_store_agent.clock import closed_reason, holiday_lines, holiday_name, next_opening_label
from music_store_agent.constants import LANDLINE_PHONE, REFERENCE_TIME, WHATSAPP_PHONE


def hours_answer(moment: datetime, asked: date | None = None) -> str:
    local = moment.astimezone(moment.tzinfo) if moment.tzinfo else moment
    day = asked or local.date()
    clock_time = REFERENCE_TIME if asked is not None else local.time().replace(microsecond=0)
    reason = closed_reason(day, clock_time)
    lines = [f"Data consultada: {day.isoformat()} às {clock_time.strftime('%H:%M')}."]
    if reason is None:
        lines.append("A loja está aberta nesse horário.")
    else:
        lines.append(f"A loja está fechada ({reason}).")
        lines.append(f"Próxima abertura no calendário fixo: {next_opening_label(day, clock_time)}.")
    lines.append(f"WhatsApp {WHATSAPP_PHONE}. Telefone fixo {LANDLINE_PHONE}.")
    lines.append("Feriados fixos: " + holiday_lines() + ".")
    lines.append("Carnaval, Sexta-feira Santa e Corpus Christi não estão na lista.")
    return "\n".join(lines)


def parse_asked_day(raw: str | None, today: date) -> date | None:
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return _day_month(text, today)


def _day_month(text: str, today: date) -> date | None:
    import re

    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", text)
    if match is None:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    try:
        return date(today.year, month, day)
    except ValueError:
        return None


def holiday_on(day: date) -> str | None:
    return holiday_name(day)

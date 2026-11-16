"""Append a handoff row. The file is local and holds no contact details.

The team reaches a confirmed customer through the order's contact. A visitor who confirmed no
order is told to write on WhatsApp with the protocol, which the row carries.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from music_store_agent.clock import STORE_ZONE, is_open_at, next_opening_label
from music_store_agent.constants import (
    HANDOFF_REASON_CAP,
    HANDOFF_SUMMARY_CAP,
    TEAM_REPLY_BUSINESS_HOURS,
    WHATSAPP_PHONE,
)
from music_store_agent.textutil import mask_pii


@dataclass(frozen=True)
class HandoffCase:
    reason: str
    summary: str
    protocol: str
    customer_id: int | None = None
    order_id: int | None = None


def write_handoff(path: Path, when: datetime, case: HandoffCase) -> None:
    """`when` is the store clock, which can be pinned. `logged_at` is the real time of writing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": when.isoformat(timespec="seconds"),
        "logged_at": datetime.now(STORE_ZONE).isoformat(timespec="seconds"),
        "protocol": case.protocol,
        "reason": mask_pii(case.reason)[:HANDOFF_REASON_CAP],
        "summary": mask_pii(case.summary)[:HANDOFF_SUMMARY_CAP],
        "verified_customer_id": case.customer_id,
        "order_id": case.order_id,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def follow_up(order_id: int | None, protocol: str, english: bool = False) -> str:
    """How the team gets back to this person."""
    if english:
        if order_id is not None:
            return f"The team will contact you through the contact details of order {order_id}."
        return (
            f"To have the team reach you, message us on WhatsApp {WHATSAPP_PHONE} "
            f"and give protocol {protocol}."
        )
    if order_id is not None:
        return f"A equipe fala com você pelo contato do pedido {order_id}."
    return (
        f"Para a equipe falar com você, chame no WhatsApp {WHATSAPP_PHONE} "
        f"e informe o protocolo {protocol}."
    )


def reply_window(now: datetime) -> str:
    """When the team picks the case up, from the store clock."""
    within = f"A equipe responde em até {TEAM_REPLY_BUSINESS_HOURS} horas úteis."
    if is_open_at(now):
        return within
    opening = next_opening_label(now.date(), now.time().replace(microsecond=0))
    return f"A loja está fechada agora e reabre em {opening}. {within}"

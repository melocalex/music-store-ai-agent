"""Order lookup. Identity is checked here, never taken from the model."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from music_store_agent.constants import (
    DEFECT_EXCHANGE_DAYS,
    LEGAL_WARRANTY_DAYS,
    MAX_VERIFICATION_ATTEMPTS,
    NOT_VERIFIED,
    NOT_YOUR_ORDER,
    OPEN_DELIVERY_STATUSES,
    PREFERENCE_DAYS,
    REGRET_DAYS,
    VERIFICATION_FAILED,
    VERIFICATION_LOCKED,
)
from music_store_agent.db import fetch_items, fetch_orders
from music_store_agent.ledger import Ledger
from music_store_agent.textutil import emails_match, fold, format_amount, format_brl, phones_match


@dataclass(frozen=True)
class Buyer:
    first_name: str
    email: str
    phone: str
    city: str


@dataclass(frozen=True)
class PayFact:
    status: str
    total: Decimal
    method: str


@dataclass(frozen=True)
class ShipFact:
    ordered_on: date
    estimate: date | None
    tracking: str | None
    notes: str


@dataclass(frozen=True)
class OrderRecord:
    order_id: int
    customer_id: int
    buyer: Buyer
    pay: PayFact
    ship: ShipFact
    items: tuple[str, ...]


@dataclass
class Identity:
    verified_customer_id: int | None = None
    failed_verifications: int = 0
    sender_phone: str | None = None
    locked: bool = False


def load_orders(conn: sqlite3.Connection) -> dict[int, OrderRecord]:
    names: dict[int, list[str]] = {}
    for row in fetch_items(conn):
        names.setdefault(int(row["order_id"]), []).append(str(row["name"]))
    return {int(row["order_id"]): _order_from(row,
        tuple(names.get(int(row["order_id"]),
        ()))) for row in fetch_orders(conn)}


def _order_from(row: sqlite3.Row, items: tuple[str, ...]) -> OrderRecord:
    buyer = Buyer(_first(str(row["customer_name"])),
        str(row["email"]),
        str(row["phone"]),
        str(row["city"]))
    pay = PayFact(str(row["status"]), Decimal(str(row["total_brl"])), str(row["payment_method"]))
    ship = ShipFact(
        date.fromisoformat(str(row["order_date"])),
        _optional_date(row["estimated_delivery"]),
        row["tracking_code"],
        str(row["notes"] or ""),
    )
    return OrderRecord(int(row["order_id"]), int(row["customer_id"]), buyer, pay, ship, items)


def _first(name: str) -> str:
    return name.split()[0]


def _optional_date(value: object) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value))


def verify(
    identity: Identity,
    orders: dict[int, OrderRecord],
    order_id: int,
    email: str | None,
    phone: str | None,
) -> str:
    if identity.locked or identity.failed_verifications >= MAX_VERIFICATION_ATTEMPTS:
        identity.locked = True
        return VERIFICATION_LOCKED
    given_phone = identity.sender_phone or phone
    if not email and not given_phone:
        return "Preciso do e-mail completo ou do telefone completo usados nesse pedido."
    order = orders.get(order_id)
    if order is None or not _matches(order, email, given_phone):
        return _fail(identity)
    identity.verified_customer_id = order.customer_id
    identity.failed_verifications = 0
    return f"Pedido {order.order_id} confirmado para {order.buyer.first_name}."


def _matches(order: OrderRecord, email: str | None, phone: str | None) -> bool:
    checks: list[bool] = []
    if email:
        checks.append(emails_match(order.buyer.email, email))
    if phone:
        checks.append(phones_match(order.buyer.phone, phone))
    return bool(checks) and all(checks)


def _fail(identity: Identity) -> str:
    identity.failed_verifications += 1
    if identity.failed_verifications >= MAX_VERIFICATION_ATTEMPTS:
        identity.locked = True
        return VERIFICATION_LOCKED
    return VERIFICATION_FAILED


def read_order(
    identity: Identity,
    orders: dict[int, OrderRecord],
    order_id: int,
    today: date,
    ledger: Ledger,
) -> str:
    if identity.verified_customer_id is None:
        return NOT_VERIFIED
    order = orders.get(order_id)
    if order is None or order.customer_id != identity.verified_customer_id:
        return NOT_YOUR_ORDER
    return _public_order(order, today, ledger)


def _public_order(order: OrderRecord, today: date, ledger: Ledger) -> str:
    ledger.add_policy(order.pay.total)
    lines = [
        f"Pedido {order.order_id} de {order.buyer.first_name}. Cidade: {order.buyer.city}.",
        f"Status {order.pay.status}. Forma {order.pay.method}.",
        f"Total gravado amount={format_amount(order.pay.total)} {format_brl(order.pay.total)}.",
        f"Compra em {order.ship.ordered_on.isoformat()}.",
        _tracking(order),
        "Itens: " + ", ".join(order.items) if order.items else "Itens não localizados.",
    ]
    if _is_late(order, today):
        estimate = order.ship.estimate
        status = order.pay.status
        lines.append(f"A estimativa {estimate} já passou e o status segue {status}.")
    if order.ship.notes.strip():
        lines.append(f"Nota interna resumida: {_note(order.ship.notes)}")
    lines.append("Não recalculo o total gravado.")
    return "\n".join(line for line in lines if line)


def _tracking(order: OrderRecord) -> str:
    if order.ship.tracking:
        return f"Rastreio {order.ship.tracking}."
    return "Sem código de rastreio."


def _is_late(order: OrderRecord, today: date) -> bool:
    estimate = order.ship.estimate
    return estimate is not None and order.pay.status in OPEN_DELIVERY_STATUSES and today > estimate


def _note(notes: str) -> str:
    folded = fold(notes)
    if "venda final" in folded:
        return "venda final"
    if "setup" in folded or "regulagem" in folded:
        return "setup ou regulagem"
    return "há uma observação operacional"


def explain_after_sales(
    identity: Identity,
    orders: dict[int, OrderRecord],
    order_id: int,
    today: date,
) -> str:
    if identity.verified_customer_id is None:
        return NOT_VERIFIED
    order = orders.get(order_id)
    if order is None or order.customer_id != identity.verified_customer_id:
        return NOT_YOUR_ORDER
    if order.pay.status == "cancelled":
        return f"O pedido {order.order_id} está cancelado. Não abro troca."
    return "\n".join(
        [
            defect_line(order.ship.ordered_on, today),
            warranty_line(),
            regret_line(),
            preference_line(),
            "Não aprovo a solicitação. A equipe confirma.",
        ]
    )


def defect_line(ordered_on: date, today: date) -> str:
    elapsed = (today - ordered_on).days
    state = "dentro do prazo" if elapsed <= DEFECT_EXCHANGE_DAYS else "fora do prazo"
    return (
        f"Troca por defeito: {DEFECT_EXCHANGE_DAYS} dias da compra ({ordered_on.isoformat()}). "
        f"Dias passados: {elapsed}. Situação: {state}."
    )


def warranty_line() -> str:
    return (
        f"Garantia legal: {LEGAL_WARRANTY_DAYS} dias do recebimento. "
        "O pedido não tem a data de recebimento. Não confirmo."
    )


def regret_line() -> str:
    return (
        f"Arrependimento: {REGRET_DAYS} dias do recebimento, só se a compra foi online. "
        "Não há canal nem data de recebimento. Informe a data. A equipe confirma."
    )


def preference_line() -> str:
    return (
        f"Troca por preferência: {PREFERENCE_DAYS} dias do recebimento. "
        "Peça a data. A equipe confirma."
    )

"""Order lookup. Identity is checked here, never taken from the model."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from music_store_agent.constants import (
    ASK_CONTACT,
    ASK_PHONE,
    DEFECT_EXCHANGE_DAYS,
    FACTORY_WARRANTY,
    LEGAL_WARRANTY_DAYS,
    MAX_VERIFICATION_ATTEMPTS,
    NOT_VERIFIED,
    NOT_YOUR_ORDER,
    OPEN_DELIVERY_STATUSES,
    ORDER_CANCELLED,
    PREFERENCE_DAYS,
    REGRET_DAYS,
    UNESTIMATED_ORDER_DAYS,
    VERIFICATION_FAILED,
    VERIFICATION_LOCKED,
)
from music_store_agent.db import customers_with_email, fetch_order, fetch_order_items
from music_store_agent.ledger import ORDER_TOTAL, Ledger
from music_store_agent.textutil import (
    emails_match,
    format_amount,
    format_brl,
    mask_pii,
    phones_match,
)

_STATUS_LABELS = {
    "delivered": "entregue",
    "shipped": "enviado",
    "confirmed": "confirmado",
    "pending": "pendente",
    ORDER_CANCELLED: "cancelado",
}
_PAYMENT_LABELS = {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto"}
_CREDIT_PREFIX = "credit_"


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
    """`failed_verifications` counts the whole session. A success does not reset it."""

    verified_customer_id: int | None = None
    verified_order_id: int | None = None
    failed_verifications: int = 0
    sender_phone: str | None = None
    locked: bool = False


@dataclass(frozen=True)
class AfterSales:
    text: str
    open_to_request: bool


def load_order(conn: sqlite3.Connection, order_id: int) -> OrderRecord | None:
    row = fetch_order(conn, order_id)
    if row is None:
        return None
    rows = fetch_order_items(conn, order_id)
    items = tuple(f"{item['quantity']}x {item['name']}" for item in rows)
    return _order_from(row, items)


def _order_from(row: sqlite3.Row, items: tuple[str, ...]) -> OrderRecord:
    buyer = Buyer(
        _first(str(row["customer_name"])), str(row["email"]), str(row["phone"]), str(row["city"])
    )
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
    conn: sqlite3.Connection,
    order_id: int,
    email: str | None,
    phone: str | None,
) -> str:
    if identity.locked or identity.failed_verifications >= MAX_VERIFICATION_ATTEMPTS:
        identity.locked = True
        return VERIFICATION_LOCKED
    phones = [given for given in (phone, identity.sender_phone) if given]
    if not email and not phones:
        return ASK_CONTACT
    order = load_order(conn, order_id)
    if order is None:
        return _fail(identity)
    email_ok = bool(email) and emails_match(order.buyer.email, email or "")
    phone_ok = any(phones_match(order.buyer.phone, given) for given in phones)
    shared = email_ok and customers_with_email(conn, order.buyer.email) > 1
    # A shared e-mail needs a phone the customer typed. A sender phone that is not the owner's
    # is not a wrong answer, so it does not cost an attempt.
    if shared and not phone_ok and not phone:
        return ASK_PHONE
    if not (phone_ok or (email_ok and not shared)):
        return _fail(identity)
    identity.verified_customer_id = order.customer_id
    identity.verified_order_id = order.order_id
    return f"Pedido {order.order_id} confirmado para {order.buyer.first_name}."


def _fail(identity: Identity) -> str:
    identity.failed_verifications += 1
    if identity.failed_verifications >= MAX_VERIFICATION_ATTEMPTS:
        identity.locked = True
        return VERIFICATION_LOCKED
    return VERIFICATION_FAILED


def _owned(identity: Identity, conn: sqlite3.Connection, order_id: int) -> OrderRecord | str:
    if identity.verified_customer_id is None:
        return NOT_VERIFIED
    order = load_order(conn, order_id)
    if order is None or order.customer_id != identity.verified_customer_id:
        return NOT_YOUR_ORDER
    return order


def read_order(
    identity: Identity,
    conn: sqlite3.Connection,
    order_id: int,
    today: date,
    ledger: Ledger,
) -> str:
    order = _owned(identity, conn, order_id)
    if isinstance(order, str):
        return order
    return _public_order(order, today, ledger)


def _public_order(order: OrderRecord, today: date, ledger: Ledger) -> str:
    ledger.add_policy(order.pay.total, ORDER_TOTAL)
    total = order.pay.total
    lines = [
        f"Pedido {order.order_id} de {order.buyer.first_name}. Cidade: {order.buyer.city}.",
        f"Situação: {status_label(order.pay.status)}.",
        f"Pagamento: {payment_label(order.pay.method)}.",
        f"Total gravado: product_id=null amount={format_amount(total)} {format_brl(total)}.",
        f"Compra em {order.ship.ordered_on.isoformat()}.",
        _tracking(order),
        "Itens: " + ", ".join(order.items) if order.items else "Itens não localizados.",
    ]
    if is_late(order, today):
        lines.append(
            f"A estimativa {order.ship.estimate} já passou e a situação segue "
            f"{status_label(order.pay.status)}."
        )
    elif is_stale(order, today):
        lines.append(
            f"O pedido foi feito há {(today - order.ship.ordered_on).days} dias, segue "
            f"{status_label(order.pay.status)} e não tem estimativa de entrega gravada. "
            "Encaminhe para a equipe verificar."
        )
    if order.ship.notes.strip():
        lines.append(_note_line(order))
    lines.append("Não recalculo o total gravado.")
    return "\n".join(line for line in lines if line)


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def payment_label(method: str) -> str:
    if method.startswith(_CREDIT_PREFIX):
        return "cartão de crédito em " + method.removeprefix(_CREDIT_PREFIX)
    return _PAYMENT_LABELS.get(method, method)


def _tracking(order: OrderRecord) -> str:
    if order.ship.tracking:
        return f"Rastreio {order.ship.tracking}, no site dos Correios ou da Jadlog."
    return "Sem código de rastreio. Ele é enviado por e-mail e WhatsApp no despacho."


def is_late(order: OrderRecord, today: date) -> bool:
    estimate = order.ship.estimate
    return estimate is not None and order.pay.status in OPEN_DELIVERY_STATUSES and today > estimate


def is_stale(order: OrderRecord, today: date) -> bool:
    """Open, with no stored estimate, and older than the longest estimate the store gives."""
    age = (today - order.ship.ordered_on).days
    open_order = order.pay.status in OPEN_DELIVERY_STATUSES
    return order.ship.estimate is None and open_order and age > UNESTIMATED_ORDER_DAYS


def _note_line(order: OrderRecord) -> str:
    """Every stored note is a cancellation reason. Any other note is only flagged."""
    if order.pay.status == ORDER_CANCELLED:
        return f"Motivo do cancelamento gravado: {mask_pii(order.ship.notes.strip())}."
    return "Há uma observação interna no pedido. A equipe detalha se for preciso."


def explain_after_sales(
    identity: Identity,
    conn: sqlite3.Connection,
    order_id: int,
    today: date,
) -> AfterSales:
    order = _owned(identity, conn, order_id)
    if isinstance(order, str):
        return AfterSales(order, False)
    if order.pay.status == ORDER_CANCELLED:
        text = (
            f"O pedido {order.order_id} está cancelado. As regras de troca tratam de produto "
            "recebido, então a equipe confirma o caso."
        )
        return AfterSales(text, True)
    ordered_on = order.ship.ordered_on
    delivered = order.pay.status not in OPEN_DELIVERY_STATUSES
    lines = [
        defect_line(ordered_on, today, delivered),
        receipt_line("Garantia legal", LEGAL_WARRANTY_DAYS, ordered_on, today, delivered),
        f"Garantia do fabricante: {FACTORY_WARRANTY}.",
        receipt_line(
            "Arrependimento, só em compra online", REGRET_DAYS, ordered_on, today, delivered
        ),
        preference_line(ordered_on, today, delivered),
        "Não aprovo a solicitação. A equipe confirma.",
    ]
    return AfterSales("\n".join(lines), True)


def defect_line(ordered_on: date, today: date, delivered: bool) -> str:
    """An order still on its way has no product to exchange yet, whatever the date says."""
    head = f"Troca por defeito: {DEFECT_EXCHANGE_DAYS} dias da compra ({ordered_on.isoformat()})."
    if not delivered:
        return f"{head} O pedido ainda não foi entregue. Se chegar com defeito, a equipe avalia."
    elapsed = (today - ordered_on).days
    state = "dentro do prazo" if elapsed <= DEFECT_EXCHANGE_DAYS else "fora do prazo"
    return f"{head} Dias passados: {elapsed}. Situação: {state}."


def receipt_line(label: str, days: int, ordered_on: date, today: date, delivered: bool) -> str:
    """Receipt is never before purchase, so a window still open from the purchase is open."""
    head = f"{label}: {days} dias do recebimento."
    if not delivered:
        return f"{head} O pedido ainda não foi entregue, então esse prazo não começou."
    elapsed = (today - ordered_on).days
    if elapsed <= days:
        return f"{head} A compra foi há {elapsed} dias, então esse prazo ainda está aberto."
    return (
        f"{head} A compra foi há {elapsed} dias e o pedido não guarda a data de recebimento. "
        "Peça essa data."
    )


def preference_line(ordered_on: date, today: date, delivered: bool) -> str:
    """The manual gives 7 days without saying from when. Inside 7 days of purchase, both agree."""
    elapsed = (today - ordered_on).days
    head = (
        f"Troca por preferência: {PREFERENCE_DAYS} dias, se houver o produto desejado. "
        "O manual não diz se contam da compra ou do recebimento."
    )
    if not delivered:
        return f"{head} O pedido ainda não foi entregue, então não há produto para trocar ainda."
    if elapsed <= PREFERENCE_DAYS:
        return f"{head} A compra foi há {elapsed} dias, então o prazo vale nas duas leituras."
    return f"{head} A compra foi há {elapsed} dias. Peça a data de recebimento."

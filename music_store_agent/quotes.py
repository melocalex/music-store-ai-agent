"""Build a sellable offer from the catalog price and the payment rules."""

from decimal import Decimal

from music_store_agent.catalog import Product, effective_price, promo_text
from music_store_agent.constants import (
    CASH_INSTALLMENTS,
    CASH_PAYMENTS,
    FREIGHT_FREE_FROM,
    INSTALLMENT_MAX,
    PAYMENT_CREDIT,
    PAYMENT_PIX,
    PAYMENT_SPLIT,
    SPLIT_PAYMENT_ABOVE,
)
from music_store_agent.ledger import FLOOR, FREIGHT, THRESHOLD, Ledger
from music_store_agent.money import (
    Parcels,
    decide_freight,
    decide_installments,
    line_total,
    max_installments,
    parcel_floor,
    pix_price,
    quantity_error,
    split_allowed,
    split_parcels,
)
from music_store_agent.textutil import format_amount, format_brl


def quote_text(
    product: Product,
    quantity: int,
    payment: str,
    installments: int,
    in_city: bool,
    ledger: Ledger,
) -> str:
    error = quantity_error(quantity, product.details.stock)
    if error:
        return error
    unit = effective_price(product)
    merchandise = line_total(unit, quantity)
    ledger.add_product(product.product_id, product.list_price, product.name)
    ledger.add_product(product.product_id, merchandise, product.name)
    lines = [_headline(product, quantity, merchandise)]
    lines.append(_payment_line(product, merchandise, payment, ledger))
    lines.append(_installment_line(product, merchandise, payment, installments, ledger))
    lines.append(_freight_line(merchandise, in_city, ledger))
    return "\n".join(lines)


def _headline(product: Product, quantity: int, merchandise: Decimal) -> str:
    shown = format_brl(merchandise)
    base = (
        f"{product.name} x{quantity}. "
        f"product_id={product.product_id} amount={format_amount(merchandise)} {shown}."
    )
    promo = promo_text(product)
    if promo is None:
        return base + " Sem promoção ativa."
    return base + f" Promoção já aplicada: {promo}. PIX não acumula."


def _payment_line(product: Product, merchandise: Decimal, payment: str, ledger: Ledger) -> str:
    if payment == PAYMENT_PIX and product.promos.percent is not None:
        return "PIX não entra em cima de promoção. O valor acima é o preço a pagar."
    if payment == PAYMENT_PIX:
        payable = pix_price(merchandise)
        ledger.add_product(product.product_id, payable, product.name)
        shown = format_brl(payable)
        return f"PIX product_id={product.product_id} amount={format_amount(payable)} {shown}."
    if payment == PAYMENT_SPLIT:
        return _split_line(merchandise, ledger)
    if payment in CASH_PAYMENTS or payment == PAYMENT_CREDIT:
        return f"Forma {payment}. Valor do item: {format_brl(merchandise)}."
    return "Forma de pagamento desconhecida. Use pix, debit, credit, boleto ou pix_and_card."


def _split_line(merchandise: Decimal, ledger: Ledger) -> str:
    ledger.add_policy(SPLIT_PAYMENT_ABOVE, THRESHOLD)
    ceiling = format_brl(SPLIT_PAYMENT_ABOVE)
    if split_allowed(merchandise):
        return f"PIX mais cartão é permitido acima de {ceiling}. Não calculo a divisão."
    return f"PIX mais cartão só acima de {ceiling}. Este valor não chega lá."


def _installment_line(
    product: Product,
    merchandise: Decimal,
    payment: str,
    installments: int,
    ledger: Ledger,
) -> str:
    if payment != PAYMENT_CREDIT:
        return "Essa forma é à vista. Não parcelo aqui."
    if installments == CASH_INSTALLMENTS:
        return "Crédito em 1x é à vista."
    decision = decide_installments(merchandise, installments)
    if not decision.allowed or decision.parcels is None:
        return _refusal(product, merchandise, installments, decision.reason, ledger)
    return _parcel_text(product, decision.parcels, ledger)


def _refusal(
    product: Product, merchandise: Decimal, installments: int, reason: str, ledger: Ledger
) -> str:
    """The refused count, its floor as a rule value, and the parcels of the largest plan."""
    ceiling = max_installments(merchandise)
    lines = [f"{installments}x não é permitido ({reason}). Máximo: {ceiling}x."]
    if CASH_INSTALLMENTS < installments <= INSTALLMENT_MAX:
        floor = parcel_floor(installments)
        ledger.add_policy(floor, FLOOR)
        lines.append(f"Parcela mínima nessa faixa: product_id=null amount={format_amount(floor)}.")
    if ceiling > CASH_INSTALLMENTS:
        plan = _parcel_text(product, split_parcels(merchandise, ceiling), ledger)
        lines.append(f"Plano máximo: {plan}")
    return " ".join(lines)


def _parcel_text(product: Product, parcels: Parcels, ledger: Ledger) -> str:
    ledger.add_product(product.product_id, parcels.rest, product.name)
    ledger.add_product(product.product_id, parcels.first, product.name)
    rest = f"product_id={product.product_id} amount={format_amount(parcels.rest)}"
    if parcels.first == parcels.rest:
        return f"{parcels.count}x de {rest} {format_brl(parcels.rest)}."
    first = f"amount={format_amount(parcels.first)} {format_brl(parcels.first)}"
    return (
        f"{parcels.count}x: a primeira de {first} e {parcels.count - 1} de "
        f"{rest} {format_brl(parcels.rest)}. A primeira leva os centavos que sobram."
    )


def _freight_line(merchandise: Decimal, in_city: bool, ledger: Ledger) -> str:
    decision = decide_freight(merchandise, in_city)
    if decision.kind == "flat" and decision.amount is not None:
        ledger.add_policy(decision.amount, FREIGHT)
        amount = format_amount(decision.amount)
        return decision.note + f" Regra: product_id=null amount={amount}."
    if decision.kind == "free":
        ledger.add_policy(FREIGHT_FREE_FROM, FREIGHT)
    return decision.note

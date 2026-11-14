"""Build a sellable offer from the catalog price and the payment rules."""

from music_store_agent.catalog import Product, effective_price
from music_store_agent.constants import (
    CASH_INSTALLMENTS,
    CASH_PAYMENTS,
    PAYMENT_CREDIT,
    PAYMENT_PIX,
    PAYMENT_SPLIT,
)
from music_store_agent.ledger import Ledger
from music_store_agent.money import (
    decide_freight,
    decide_installments,
    line_total,
    max_installments,
    quantity_error,
    split_allowed,
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
    error = quantity_error(quantity)
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


def _headline(product: Product, quantity: int, merchandise) -> str:
    shown = format_brl(merchandise)
    base = (
        f"{product.name} x{quantity}. "
        f"product_id={product.product_id} amount={format_amount(merchandise)} {shown}."
    )
    if product.promos.percent is None:
        return base + " Sem promoção ativa."
    campaign = product.promos.campaign
    percent = product.promos.percent
    return base + f" Promoção {campaign} {percent}% já aplicada. PIX não acumula."


def _payment_line(product: Product, merchandise, payment: str, ledger: Ledger) -> str:
    if payment == PAYMENT_PIX and product.promos.percent is not None:
        return "PIX não entra em cima de promoção. O valor acima é o preço a pagar."
    if payment == PAYMENT_PIX:
        from music_store_agent.money import pix_price

        payable = pix_price(merchandise)
        ledger.add_product(product.product_id, payable, product.name)
        shown = format_brl(payable)
        return f"PIX product_id={product.product_id} amount={format_amount(payable)} {shown}."
    if payment == PAYMENT_SPLIT:
        return _split_line(merchandise, ledger)
    if payment in CASH_PAYMENTS or payment == PAYMENT_CREDIT:
        return f"Forma {payment}. Valor do item: {format_brl(merchandise)}."
    return "Forma de pagamento desconhecida. Use pix, debit, credit, boleto ou pix_and_card."


def _split_line(merchandise, ledger: Ledger) -> str:
    from music_store_agent.constants import SPLIT_PAYMENT_ABOVE

    ledger.add_policy(SPLIT_PAYMENT_ABOVE)
    if split_allowed(merchandise):
        ceiling = format_brl(SPLIT_PAYMENT_ABOVE)
        return f"PIX mais cartão é permitido acima de {ceiling}. Não calculo a divisão."
    ceiling = format_brl(SPLIT_PAYMENT_ABOVE)
    return f"PIX mais cartão só acima de {ceiling}. Este valor não chega lá."


def _installment_line(
    product: Product,
    merchandise,
    payment: str,
    installments: int,
    ledger: Ledger,
) -> str:
    if payment != PAYMENT_CREDIT:
        return "Essa forma é à vista. Não parcelo aqui."
    decision = decide_installments(merchandise, installments)
    if installments == CASH_INSTALLMENTS:
        return "Crédito em 1x é à vista."
    if not decision.allowed or decision.parcel is None:
        ceiling = max_installments(merchandise)
        return f"{installments}x não é permitido ({decision.reason}). Máximo: {ceiling}x."
    ledger.add_product(product.product_id, decision.parcel, product.name)
    shown = format_brl(decision.parcel)
    return (
        f"{installments}x de product_id={product.product_id} "
        f"amount={format_amount(decision.parcel)} {shown}."
    )


def _freight_line(merchandise, in_city: bool, ledger: Ledger) -> str:
    decision = decide_freight(merchandise, in_city)
    if decision.kind == "flat" and decision.amount is not None:
        ledger.add_policy(decision.amount)
        amount = format_amount(decision.amount)
        return decision.note + f" Regra: product_id=null amount={amount}."
    if decision.kind == "free":
        from music_store_agent.constants import FREIGHT_FREE_FROM

        ledger.add_policy(FREIGHT_FREE_FROM)
        return decision.note
    return decision.note

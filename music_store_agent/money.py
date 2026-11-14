"""Decimal price, installment, PIX, and freight rules."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from music_store_agent.constants import (
    CASH_INSTALLMENTS,
    CENT,
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    INSTALLMENT_MAX,
    MIN_ORDER_FOR_INSTALLMENTS,
    MIN_PARCEL_4_TO_6,
    MIN_PARCEL_7_TO_12,
    PIX_PERCENT,
    QUANTITY_MAX,
    QUANTITY_MIN,
    SPLIT_PAYMENT_ABOVE,
    TIER_LOW_MAX,
    TIER_MID_MAX,
)
from music_store_agent.textutil import format_brl

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class InstallmentDecision:
    allowed: bool
    parcel: Decimal | None
    reason: str


@dataclass(frozen=True)
class FreightDecision:
    kind: str
    amount: Decimal | None
    note: str


def quantize(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_off(amount: Decimal, percent: Decimal) -> Decimal:
    kept = (_HUNDRED - percent) / _HUNDRED
    return quantize(amount * kept)


def pix_price(amount: Decimal) -> Decimal:
    return percent_off(amount, PIX_PERCENT)


def line_total(unit: Decimal, quantity: int) -> Decimal:
    return quantize(unit * Decimal(quantity))


def parcel_value(total: Decimal, installments: int) -> Decimal:
    return quantize(total / Decimal(installments))


def decide_installments(total: Decimal, installments: int) -> InstallmentDecision:
    if installments == CASH_INSTALLMENTS:
        return InstallmentDecision(True, total, "a vista")
    if installments < CASH_INSTALLMENTS or installments > INSTALLMENT_MAX:
        return InstallmentDecision(False, None, "fora da faixa de 1 a 12")
    parcel = parcel_value(total, installments)
    if total < MIN_ORDER_FOR_INSTALLMENTS:
        return InstallmentDecision(False, parcel, "pedido abaixo do minimo para parcelar")
    if installments <= TIER_LOW_MAX:
        return InstallmentDecision(True, parcel, "sem parcela minima")
    if installments <= TIER_MID_MAX:
        return InstallmentDecision(parcel >= MIN_PARCEL_4_TO_6, parcel, "faixa de 4 a 6")
    return InstallmentDecision(parcel >= MIN_PARCEL_7_TO_12, parcel, "faixa de 7 a 12")


def max_installments(total: Decimal) -> int:
    allowed = CASH_INSTALLMENTS
    for count in range(CASH_INSTALLMENTS, INSTALLMENT_MAX + 1):
        if decide_installments(total, count).allowed:
            allowed = count
    return allowed


def decide_freight(merchandise: Decimal, in_city: bool) -> FreightDecision:
    if not in_city:
        return FreightDecision("not_quoted",
            None,
            "Fora de Campo Grande o frete não é calculado aqui.")
    if merchandise >= FREIGHT_FREE_FROM:
        note = f"Frete grátis em Campo Grande a partir de {format_brl(FREIGHT_FREE_FROM)}."
        return FreightDecision("free", None, note)
    note = f"Frete em Campo Grande: {format_brl(FREIGHT_FLAT)}."
    return FreightDecision("flat", FREIGHT_FLAT, note)


def split_allowed(merchandise: Decimal) -> bool:
    return merchandise > SPLIT_PAYMENT_ABOVE


def quantity_error(quantity: int) -> str | None:
    if quantity < QUANTITY_MIN or quantity > QUANTITY_MAX:
        return f"A quantidade precisa ficar entre {QUANTITY_MIN} e {QUANTITY_MAX}."
    return None

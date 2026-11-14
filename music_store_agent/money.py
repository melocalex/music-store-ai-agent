"""Decimal price, installment, PIX, and freight rules."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from music_store_agent.constants import (
    CASH_INSTALLMENTS,
    CENT,
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    INSTALLMENT_MAX,
    MIN_PARCEL_2_TO_3,
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
class Parcels:
    """`count` parcels: the first one carries the leftover cents, the others are equal."""

    count: int
    first: Decimal
    rest: Decimal

    @property
    def total(self) -> Decimal:
        return self.first + self.rest * (self.count - 1)


@dataclass(frozen=True)
class InstallmentDecision:
    allowed: bool
    parcels: Parcels | None
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


def split_parcels(total: Decimal, count: int) -> Parcels:
    """Round each parcel down to the cent and put the remainder in the first one."""
    rest = (total / Decimal(count)).quantize(CENT, rounding=ROUND_DOWN)
    first = total - rest * (count - 1)
    return Parcels(count, first, rest)


def parcel_floor(installments: int) -> Decimal:
    if installments <= TIER_LOW_MAX:
        return MIN_PARCEL_2_TO_3
    if installments <= TIER_MID_MAX:
        return MIN_PARCEL_4_TO_6
    return MIN_PARCEL_7_TO_12


def decide_installments(total: Decimal, installments: int) -> InstallmentDecision:
    if installments == CASH_INSTALLMENTS:
        return InstallmentDecision(True, split_parcels(total, CASH_INSTALLMENTS), "à vista")
    if installments < CASH_INSTALLMENTS or installments > INSTALLMENT_MAX:
        reason = f"fora da faixa de {CASH_INSTALLMENTS} a {INSTALLMENT_MAX}"
        return InstallmentDecision(False, None, reason)
    floor = parcel_floor(installments)
    parcels = split_parcels(total, installments)
    reason = f"parcela mínima de {format_brl(floor)} nessa faixa"
    # The floor applies to the exact parcel, before rounding: R$ 479,97 in 6x is 79,995.
    return InstallmentDecision(total >= floor * installments, parcels, reason)


def max_installments(total: Decimal) -> int:
    allowed = CASH_INSTALLMENTS
    for count in range(CASH_INSTALLMENTS, INSTALLMENT_MAX + 1):
        if decide_installments(total, count).allowed:
            allowed = count
    return allowed


def decide_freight(merchandise: Decimal, in_city: bool) -> FreightDecision:
    """`merchandise` is the item value before the PIX discount.

    The manual sets the free-freight threshold on the order value and does not say whether
    PIX counts. We read it as the value before PIX, so paying by PIX never adds freight.
    """
    if not in_city:
        note = "Fora de Campo Grande o frete não é calculado aqui."
        return FreightDecision("not_quoted", None, note)
    if merchandise >= FREIGHT_FREE_FROM:
        note = (
            f"Frete grátis em Campo Grande a partir de {format_brl(FREIGHT_FREE_FROM)} "
            "em itens, valor antes do desconto PIX."
        )
        return FreightDecision("free", None, note)
    note = f"Frete em Campo Grande: {format_brl(FREIGHT_FLAT)}."
    return FreightDecision("flat", FREIGHT_FLAT, note)


def split_allowed(merchandise: Decimal) -> bool:
    return merchandise > SPLIT_PAYMENT_ABOVE


def quantity_error(quantity: int) -> str | None:
    if quantity < QUANTITY_MIN or quantity > QUANTITY_MAX:
        return f"A quantidade precisa ficar entre {QUANTITY_MIN} e {QUANTITY_MAX}."
    return None

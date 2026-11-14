"""Boundary checks for the payment and freight calculator."""

from decimal import Decimal

from music_store_agent.constants import (
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    MIN_ORDER_FOR_INSTALLMENTS,
    MIN_PARCEL_4_TO_6,
    MIN_PARCEL_7_TO_12,
    SPLIT_PAYMENT_ABOVE,
)
from music_store_agent.money import (
    decide_freight,
    decide_installments,
    max_installments,
    parcel_value,
    pix_price,
    split_allowed,
)

C40 = Decimal("599.90")
PIX_C40 = Decimal("569.91")
LIST_2199 = Decimal("2199.00")
PIX_2199 = Decimal("2089.05")
PROMO_HT = Decimal("1967.18")


def test_pix_rounds_half_up() -> None:
    assert pix_price(C40) == PIX_C40
    assert pix_price(LIST_2199) == PIX_2199


def test_six_installments_allow_the_eighty_boundary() -> None:
    allowed = MIN_PARCEL_4_TO_6 * 6
    rejected = (MIN_PARCEL_4_TO_6 - Decimal("0.01")) * 6
    assert decide_installments(allowed, 6).allowed
    assert parcel_value(allowed, 6) == MIN_PARCEL_4_TO_6
    assert not decide_installments(rejected, 6).allowed
    assert decide_installments(C40, 6).allowed
    assert parcel_value(C40, 6) == Decimal("99.98")


def test_ten_installments_reject_c40_and_the_hundred_boundary() -> None:
    allowed = MIN_PARCEL_7_TO_12 * 12
    rejected = (MIN_PARCEL_7_TO_12 - Decimal("0.01")) * 12
    assert decide_installments(allowed, 12).allowed
    assert not decide_installments(rejected, 12).allowed
    assert not decide_installments(C40, 10).allowed
    assert not decide_installments(C40, 7).allowed
    assert max_installments(C40) == 6


def test_below_fifty_has_no_installments_and_two_to_three_do() -> None:
    below = MIN_ORDER_FOR_INSTALLMENTS - Decimal("0.01")
    assert decide_installments(below, 2).allowed is False
    assert decide_installments(MIN_ORDER_FOR_INSTALLMENTS, 2).allowed
    assert decide_installments(MIN_ORDER_FOR_INSTALLMENTS, 3).allowed
    assert decide_installments(Decimal("100.00"), 1).allowed


def test_split_payment_is_strictly_above_two_thousand() -> None:
    assert split_allowed(SPLIT_PAYMENT_ABOVE) is False
    assert split_allowed(SPLIT_PAYMENT_ABOVE + Decimal("0.01"))
    assert not split_allowed(PROMO_HT)


def test_freight_is_free_at_exactly_five_hundred() -> None:
    below = FREIGHT_FREE_FROM - Decimal("0.01")
    assert decide_freight(FREIGHT_FREE_FROM, True).kind == "free"
    flat = decide_freight(below, True)
    assert flat.kind == "flat"
    assert flat.amount == FREIGHT_FLAT
    assert decide_freight(FREIGHT_FREE_FROM, False).kind == "not_quoted"
    assert decide_freight(FREIGHT_FREE_FROM, False).amount is None

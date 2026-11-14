"""Boundary checks for the payment and freight calculator."""

from decimal import Decimal

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
from music_store_agent.money import (
    decide_freight,
    decide_installments,
    max_installments,
    percent_off,
    pix_price,
    quantity_error,
    quantize,
    split_allowed,
    split_parcels,
)

C40 = Decimal("599.90")
LIST_2199 = Decimal("2199.00")
PROMO_HT = Decimal("1967.18")
STOCK = 5


def test_pix_rounds_half_up() -> None:
    assert pix_price(C40) == percent_off(C40, PIX_PERCENT)
    assert pix_price(C40) == Decimal("569.91")  # 569.905 rounds up
    assert pix_price(LIST_2199) == Decimal("2089.05")


def test_parcels_add_up_to_the_price() -> None:
    parcels = split_parcels(C40, TIER_MID_MAX)
    assert parcels.total == C40
    assert parcels.rest == Decimal("99.98")
    assert parcels.first == C40 - parcels.rest * (TIER_MID_MAX - 1)
    even = split_parcels(MIN_PARCEL_4_TO_6 * TIER_MID_MAX, TIER_MID_MAX)
    assert even.first == even.rest == MIN_PARCEL_4_TO_6


def test_floors_use_the_exact_parcel_not_the_rounded_one() -> None:
    for count, floor in ((TIER_LOW_MAX, MIN_PARCEL_2_TO_3), (TIER_MID_MAX, MIN_PARCEL_4_TO_6),
                         (INSTALLMENT_MAX, MIN_PARCEL_7_TO_12)):
        exact = floor * count
        assert decide_installments(exact, count).allowed, count
        assert not decide_installments(exact - CENT, count).allowed, count
    # R$ 479,97 / 6 = 79,995. Rounded it would show R$ 80,00, but the floor is not met.
    shy = MIN_PARCEL_4_TO_6 * TIER_MID_MAX - CENT * 3
    assert quantize(shy / TIER_MID_MAX) == MIN_PARCEL_4_TO_6
    assert not decide_installments(shy, TIER_MID_MAX).allowed


def test_tier_edges_three_to_four_and_twelve_to_thirteen() -> None:
    low_ok = MIN_PARCEL_2_TO_3 * (TIER_LOW_MAX + 1)
    assert decide_installments(low_ok, TIER_LOW_MAX).allowed
    assert not decide_installments(low_ok, TIER_LOW_MAX + 1).allowed
    big = MIN_PARCEL_7_TO_12 * INSTALLMENT_MAX * 2
    assert decide_installments(big, INSTALLMENT_MAX).allowed
    assert not decide_installments(big, INSTALLMENT_MAX + 1).allowed
    assert not decide_installments(big, CASH_INSTALLMENTS - 1).allowed
    assert decide_installments(big, CASH_INSTALLMENTS).allowed


def test_c40_stops_at_six_installments() -> None:
    assert decide_installments(C40, TIER_MID_MAX).allowed
    assert not decide_installments(C40, TIER_MID_MAX + 1).allowed
    assert not decide_installments(C40, 10).allowed
    assert max_installments(C40) == TIER_MID_MAX


def test_small_orders_follow_the_two_to_three_floor() -> None:
    small = Decimal("129.90")  # 3x is 43,30, 2x is 64,95
    assert not decide_installments(small, TIER_LOW_MAX).allowed
    assert decide_installments(small, TIER_LOW_MAX - 1).allowed
    below = MIN_PARCEL_2_TO_3 * 2 - CENT
    assert not decide_installments(below, 2).allowed
    assert max_installments(below) == CASH_INSTALLMENTS


def test_split_payment_is_strictly_above_two_thousand() -> None:
    assert split_allowed(SPLIT_PAYMENT_ABOVE) is False
    assert split_allowed(SPLIT_PAYMENT_ABOVE + CENT)
    assert not split_allowed(PROMO_HT)


def test_freight_is_free_at_exactly_five_hundred() -> None:
    below = FREIGHT_FREE_FROM - CENT
    free = decide_freight(FREIGHT_FREE_FROM, True)
    assert free.kind == "free"
    assert "antes do desconto PIX" in free.note
    flat = decide_freight(below, True)
    assert flat.kind == "flat"
    assert flat.amount == FREIGHT_FLAT
    assert decide_freight(FREIGHT_FREE_FROM, False).kind == "not_quoted"
    assert decide_freight(FREIGHT_FREE_FROM, False).amount is None


def test_quantity_limits_and_stock() -> None:
    assert quantity_error(QUANTITY_MIN, STOCK) is None
    assert quantity_error(QUANTITY_MIN - 1, STOCK) is not None
    assert quantity_error(QUANTITY_MAX, QUANTITY_MAX) is None
    assert quantity_error(QUANTITY_MAX + 1, QUANTITY_MAX + 1) is not None
    assert quantity_error(STOCK, STOCK) is None
    assert quantity_error(STOCK + 1, STOCK) is not None

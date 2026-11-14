"""Offer text follows promo, PIX, and freight rules."""

from datetime import date

from music_store_agent.catalog import effective_price, find_products, is_sellable, load_catalog
from music_store_agent.clock import clock_at
from music_store_agent.constants import FREIGHT_FLAT, PAYMENT_PIX
from music_store_agent.db import load_database
from music_store_agent.hours import hours_answer
from music_store_agent.ledger import Ledger
from music_store_agent.orders import Identity, load_orders, verify
from music_store_agent.quotes import quote_text
from music_store_agent.textutil import format_brl


def _product(query: str):
    products = load_catalog(load_database())
    found = find_products(products, query)
    assert len(found) == 1
    return found[0]


def test_pix_does_not_stack_on_the_ht100() -> None:
    ledger = Ledger()
    text = quote_text(_product("HT-100"), 1, PAYMENT_PIX, 1, True, ledger)
    assert "1.967,18" in text
    assert "2.279,05" not in text
    assert "1.868,82" not in text
    assert "não acumula" in text.casefold() or "não entra" in text.casefold()


def test_freight_exact_and_outside_the_city() -> None:
    products = load_catalog(load_database())
    c40 = _product("C40")
    city = quote_text(c40, 1, "debit", 1, True, Ledger())
    assert "grátis" in city.casefold()
    cheap = next(
        product
        for product in products
        if is_sellable(product) and effective_price(product) < FREIGHT_FLAT * 10
    )
    flat = quote_text(cheap, 1, "debit", 1, True, Ledger())
    assert format_brl(FREIGHT_FLAT) in flat
    away = quote_text(c40, 1, PAYMENT_PIX, 1, False, Ledger())
    assert "não é calculado" in away


def test_holiday_hours_name_the_next_opening() -> None:
    moment = clock_at(date(2026, 6, 13), pinned=True).now()
    text = hours_answer(moment)
    assert "Santo Antônio" in text
    assert "2026-06-15" in text
    assert "(67) 3321-4500" in text
    assert "(67) 3341-4444" in text


def test_incomplete_contact_does_not_count() -> None:
    identity = Identity()
    text = verify(identity, load_orders(load_database()), 4, None, None)
    assert "completo" in text
    assert identity.failed_verifications == 0

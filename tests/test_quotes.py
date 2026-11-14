"""Offer text follows promo, PIX, and freight rules."""

from decimal import Decimal

from music_store_agent.catalog import effective_price, find_products, is_sellable, load_catalog
from music_store_agent.constants import FREIGHT_FLAT, PAYMENT_CREDIT, PAYMENT_PIX, TIER_MID_MAX
from music_store_agent.db import load_database
from music_store_agent.guard import PriceQuote, grounding_gap
from music_store_agent.ledger import FLOOR, Ledger
from music_store_agent.money import split_parcels
from music_store_agent.orders import Identity, verify
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


def test_incomplete_contact_does_not_count() -> None:
    identity = Identity()
    text = verify(identity, load_database(), 4, None, None)
    assert "completo" in text
    assert identity.failed_verifications == 0


def test_quote_refuses_more_than_the_stock() -> None:
    gd20 = _product("GD20")
    stock = gd20.details.stock
    allowed = quote_text(gd20, stock, PAYMENT_PIX, 1, True, Ledger())
    assert f"product_id={gd20.product_id}" in allowed
    refused = quote_text(gd20, stock + 1, PAYMENT_PIX, 1, True, Ledger())
    assert "product_id" not in refused
    assert str(stock) in refused


def test_promo_quote_shows_the_original_price_and_the_percent() -> None:
    ht = _product("HT-100")
    text = quote_text(ht, 1, PAYMENT_PIX, 1, True, Ledger())
    assert format_brl(ht.list_price) in text
    assert f"{ht.promos.percent}%" in text


def test_installment_quote_puts_the_leftover_cents_in_the_first_parcel() -> None:
    c40 = _product("C40")
    ledger = Ledger()
    text = quote_text(c40, 1, PAYMENT_CREDIT, TIER_MID_MAX, True, ledger)
    parcels = split_parcels(effective_price(c40), TIER_MID_MAX)
    assert format_brl(parcels.rest) in text
    assert format_brl(parcels.first) in text
    assert ledger.product_has(c40.product_id, parcels.first)


def test_unknown_payment_is_named_and_not_priced() -> None:
    ledger = Ledger()
    text = quote_text(_product("C40"), 1, "bitcoin", 1, True, ledger)
    assert "Forma de pagamento desconhecida" in text
    assert "bitcoin" not in text.split("\n")[0]


def test_a_refused_count_ledgers_its_floor_and_the_largest_plan() -> None:
    c40 = _product("C40")
    ledger = Ledger()
    text = quote_text(c40, 1, PAYMENT_CREDIT, 10, True, ledger)
    largest = split_parcels(effective_price(c40), TIER_MID_MAX)
    floor = Decimal("100.00")
    assert "Máximo: 6x" in text
    assert "amount=100.00" in text and format_brl(largest.rest) in text
    assert ledger.rule_kinds(floor) == {FLOOR}
    assert ledger.product_has(c40.product_id, largest.first)
    assert ledger.product_has(c40.product_id, largest.rest)
    showcase = (
        "Em 10x não dá: a parcela mínima nessa faixa é R$ 100,00. "
        f"Para o C40 o máximo é 6x, com a primeira parcela de {format_brl(largest.first)} "
        f"e cinco de {format_brl(largest.rest)}."
    )
    quotes = [
        PriceQuote(amount=floor),
        PriceQuote(product_id=c40.product_id, amount=largest.first),
        PriceQuote(product_id=c40.product_id, amount=largest.rest),
    ]
    assert grounding_gap(showcase, quotes, ledger).ok
    beyond = Ledger()
    assert "Parcela mínima" not in quote_text(c40, 1, PAYMENT_CREDIT, 13, True, beyond)
    assert beyond.rule_kinds(floor) == set()


def test_two_units_of_a_promo_item_ledger_the_unit_price() -> None:
    ht100 = _product("HT-100")
    ledger = Ledger()
    text = quote_text(ht100, 2, PAYMENT_CREDIT, 1, True, ledger)
    unit = effective_price(ht100)
    total = unit * 2
    assert format_brl(unit) in text
    assert ledger.product_has(ht100.product_id, unit)
    reply = f"Duas unidades do HT-100 saem por {format_brl(total)}, ou {format_brl(unit)} cada."
    quotes = [
        PriceQuote(product_id=ht100.product_id, amount=total),
        PriceQuote(product_id=ht100.product_id, amount=unit),
    ]
    assert grounding_gap(reply, quotes, ledger).ok

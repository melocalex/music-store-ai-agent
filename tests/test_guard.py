"""A price must belong to the product the tool named, and a rule value uses a null id."""

from decimal import Decimal

from music_store_agent.catalog import effective_price, find_products, is_sellable, load_catalog
from music_store_agent.constants import (
    FREIGHT_FLAT,
    FREIGHT_FREE_FROM,
    PAYMENT_CREDIT,
    PAYMENT_DEBIT,
    TIER_MID_MAX,
)
from music_store_agent.db import load_database
from music_store_agent.guard import AgentReply, PriceQuote, grounding_gap
from music_store_agent.ledger import Ledger
from music_store_agent.money import split_parcels
from music_store_agent.quotes import quote_text
from music_store_agent.textutil import format_brl

C40 = Decimal("599.90")
C70 = Decimal("849.00")


def _ledger() -> Ledger:
    ledger = Ledger()
    ledger.add_product(81, C40, "Yamaha C40 Nylon Natural")
    ledger.add_product(82, C70, "Yamaha C70 Nylon Natural")
    return ledger


def test_wrong_product_and_unsourced_and_words() -> None:
    ledger = _ledger()
    own = grounding_gap("O C40 custa R$ 599,90.", [PriceQuote(product_id=81, amount=C40)], ledger)
    assert own.ok
    wrong = [PriceQuote(product_id=81, amount=C70)]
    assert not grounding_gap("O C40 custa R$ 849,00.", wrong, ledger).ok
    words = grounding_gap("São quinhentos e noventa e nove reais e noventa centavos.", [], ledger)
    assert not words.ok
    missing = grounding_gap("Cabe em R$ 1.000,00.", [], ledger)
    assert not missing.ok


def test_bare_and_foreign_amount_forms_are_checked() -> None:
    ledger = _ledger()
    for text in ("6x de 99,98", "O violão sai por 1.749,00 no PIX.", "BRL 599,90", "R$ 2,199.00"):
        assert not grounding_gap(text, [], ledger).ok, text
    assert grounding_gap("O pedido 4 chega em 2026-03-30, em 3 dias.", [], ledger).ok


def test_slang_parcels_and_thousands_are_checked_like_any_amount() -> None:
    ledger = _ledger()
    for text in ("Dá sim: 12x de 50 no cartão.", "Sai por uns 2,2 mil.", "Fica em 600 conto."):
        assert not grounding_gap(text, [], ledger).ok, text
    ledger.add_product(81, Decimal("50.00"), "Yamaha C40 Nylon Natural")
    grounded = [PriceQuote(product_id=81, amount=Decimal("50.00"))]
    assert grounding_gap("O C40 em 12x de 50 no cartão.", grounded, ledger).ok
    assert grounding_gap("O C40 sai em 12x sem juros.", [], ledger).ok


def test_a_weight_or_version_next_to_a_price_does_not_fail_the_reply() -> None:
    ledger = _ledger()
    quotes = [PriceQuote(product_id=81, amount=C40)]
    text = "O C40 pesa 3,50 kg, firmware versão 2.10, e custa R$ 599,90."
    assert grounding_gap(text, quotes, ledger).ok
    assert not grounding_gap("O C40 pesa 3,50 kg e custa 3,50.", quotes, ledger).ok


def test_amount_must_sit_next_to_its_own_product() -> None:
    ledger = _ledger()
    other = [PriceQuote(product_id=82, amount=C70)]
    assert not grounding_gap("O C40 custa R$ 849,00.", other, ledger).ok
    assert grounding_gap("O C70 custa R$ 849,00.", other, ledger).ok
    assert grounding_gap("Entre o C40 e o C70, o C70 sai por R$ 849,00.", other, ledger).ok
    assert grounding_gap("Esse modelo custa R$ 849,00.", other, ledger).ok


def test_policy_values_use_a_null_id_and_prices_use_the_product() -> None:
    ledger = _ledger()
    ledger.add_policy(FREIGHT_FLAT)
    freight = grounding_gap("Frete R$ 35,00.", [PriceQuote(amount=FREIGHT_FLAT)], ledger)
    assert freight.ok
    as_rule = grounding_gap("O C40 custa R$ 599,90.", [PriceQuote(amount=C40)], ledger)
    assert not as_rule.ok
    on_product = [PriceQuote(product_id=81, amount=FREIGHT_FLAT)]
    as_price = grounding_gap("Frete R$ 35,00.", on_product, ledger)
    assert not as_price.ok


def test_quote_lines_pass_with_the_prompt_convention() -> None:
    products = load_catalog(load_database())
    c40 = find_products(products, "C40")[0]
    ledger = Ledger()
    quote_text(c40, 1, PAYMENT_CREDIT, TIER_MID_MAX, True, ledger)
    parcel = split_parcels(effective_price(c40), TIER_MID_MAX).rest
    text = f"O C40 sai em {TIER_MID_MAX}x de {format_brl(parcel)}."
    assert grounding_gap(text, [PriceQuote(product_id=c40.product_id, amount=parcel)], ledger).ok
    assert not grounding_gap(text, [PriceQuote(amount=parcel)], ledger).ok
    cheap = next(p for p in products if is_sellable(p) and effective_price(p) < FREIGHT_FREE_FROM)
    flat = Ledger()
    quote_text(cheap, 1, PAYMENT_DEBIT, 1, True, flat)
    freight = f"O frete fica em {format_brl(FREIGHT_FLAT)}."
    assert grounding_gap(freight, [PriceQuote(amount=FREIGHT_FLAT)], flat).ok
    on_product = [PriceQuote(product_id=cheap.product_id, amount=FREIGHT_FLAT)]
    assert not grounding_gap(freight, on_product, flat).ok


def test_percent_must_come_from_a_tool() -> None:
    ledger = _ledger()
    assert not grounding_gap("Tem 15% de desconto.", [], ledger).ok
    ledger.add_percents({Decimal("15")})
    assert grounding_gap("Tem 15% de desconto.", [], ledger).ok
    assert not grounding_gap("Tem 30 por cento de desconto.", [], ledger).ok


def test_unknown_lists_only_amounts_no_tool_returned() -> None:
    ledger = _ledger()
    wrong = [PriceQuote(product_id=81, amount=C70)]
    crossed = grounding_gap("O C40 custa R$ 849,00.", wrong, ledger)
    assert not crossed.ok
    assert crossed.unknown == ()
    invented = grounding_gap("Faço por R$ 10,00.", [], ledger)
    assert invented.unknown == ("10.00",)


def test_reply_parses_brazilian_amounts() -> None:
    payload = {"message": "ok", "quotes": [{"product_id": 81, "amount": "599,90"}]}
    reply = AgentReply.model_validate(payload)
    assert reply.quotes[0].amount == C40

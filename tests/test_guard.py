"""A price must belong to the product the tool named."""

from decimal import Decimal

from music_store_agent.guard import AgentReply, PriceQuote, grounding_gap
from music_store_agent.ledger import Ledger


def test_wrong_product_and_unsourced_and_words() -> None:
    ledger = Ledger()
    ledger.add_product(81, Decimal("599.90"))
    ledger.add_product(82, Decimal("849.00"))
    quote = PriceQuote(product_id=81, amount=Decimal("599.90"))
    own = grounding_gap("O C40 custa R$ 599,90.", [quote], ledger)
    assert own.ok
    crossed = grounding_gap(
        "O C40 custa R$ 849,00.",
        [PriceQuote(product_id=81, amount=Decimal("849.00"))],
        ledger,
    )
    assert not crossed.ok
    words = grounding_gap("São quinhentos e noventa e nove reais e noventa centavos.", [], ledger)
    assert not words.ok
    missing = grounding_gap("Cabe em R$ 1.000,00.", [], ledger)
    assert not missing.ok


def test_policy_amount_cannot_reuse_a_product_price() -> None:
    ledger = Ledger()
    ledger.add_product(81, Decimal("35.00"))
    ledger.add_policy(Decimal("35.00"))
    quote = PriceQuote(product_id=None, amount=Decimal("35.00"))
    gap = grounding_gap("Frete R$ 35,00.", [quote], ledger)
    assert not gap.ok
    policy = Ledger()
    policy.add_policy(Decimal("35.00"))
    quote = PriceQuote(product_id=None, amount=Decimal("35.00"))
    ok = grounding_gap("Frete R$ 35,00.", [quote], policy)
    assert ok.ok


def test_reply_parses_brazilian_amounts() -> None:
    payload = {"message": "ok", "quotes": [{"product_id": 81, "amount": "599,90"}]}
    reply = AgentReply.model_validate(payload)
    assert reply.quotes[0].amount == Decimal("599.90")

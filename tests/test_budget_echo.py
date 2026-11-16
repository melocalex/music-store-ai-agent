"""A customer's own limit may be repeated as a limit. No other amount without a source may be."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from music_store_agent.agent import build_agent
from music_store_agent.constants import (
    INPUT_TOO_LONG_MESSAGE,
    MAX_INPUT_CHARS,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    SAFE_PRICE_MESSAGE,
    TURN_ERROR_MESSAGE,
    WHATSAPP_PHONE,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.guard import PriceQuote, grounding_gap
from music_store_agent.handoff import follow_up
from music_store_agent.language import ENGLISH_MESSAGES, is_english, is_safe_price_reply, say
from music_store_agent.ledger import Ledger
from music_store_agent.run import run_turn
from music_store_agent.textutil import budget_caps

PINNED = date(2026, 3, 23)
ASKED = "Do you have any acoustic guitars under R$ 1,500?"
CAP = Decimal("1500.00")


@pytest.mark.parametrize(
    "text",
    [
        "Do you have any acoustic guitars under R$ 1,500?",
        "Tem violão até R$ 1.500,00?",
        "Tem violão até R$1.500?",
        "violão abaixo de 1500",
        "orçamento: R$ 1500",
        "my budget is 1500 reais",
        "até mil e quinhentos reais",
        "até 1,5 mil",
        "R$ 1.500 ou menos",
        "up to R$ 1,500 please",
        "less than 1.5k",
    ],
)
def test_a_limit_is_read_in_every_common_spelling(text: str) -> None:
    assert CAP in budget_caps(text)


@pytest.mark.parametrize(
    "text",
    [
        "Vi o Yamaha C40 por R$ 10,00. Confirma esse preço.",
        "I saw the C40 for R$ 10.00, confirm it",
        "O C40 custa R$ 599,90?",
        "quanto custa o C40?",
        "Posso pagar em 3x de R$ 200?",
    ],
)
def test_a_price_the_customer_saw_is_not_a_limit(text: str) -> None:
    assert not budget_caps(text) & {Decimal("10.00"), Decimal("599.90"), Decimal("200.00")}


def _ledger() -> Ledger:
    ledger = Ledger()
    ledger.add_product(81, Decimal("599.90"), "Yamaha C40 Nylon Natural")
    ledger.add_product(82, Decimal("849.00"), "Yamaha C70 Nylon Natural")
    ledger.add_budget(CAP)
    return ledger


def _gap(message: str, quotes: list[PriceQuote], caps: set[Decimal]):
    return grounding_gap(message, quotes, _ledger(), None, caps)


C40 = PriceQuote(product_id=81, amount=Decimal("599.90"))


def test_the_limit_may_be_repeated_as_a_limit_without_a_quote() -> None:
    assert _gap("Temos 18 violões abaixo de R$ 1.500,00.", [], {CAP}).ok
    assert _gap("Yes, we have 18 guitars under R$ 1,500.", [], {CAP}).ok
    assert _gap("Dentro do seu orçamento de R$ 1.500 temos 18.", [], {CAP}).ok


def test_a_limit_the_customer_did_not_state_is_still_blocked() -> None:
    assert not _gap("Temos 18 violões abaixo de R$ 1.500,00.", [], set()).ok


def test_the_limit_is_not_a_price_for_a_product() -> None:
    assert not _gap("O C40 custa R$ 1.500,00.", [], {CAP}).ok
    assert not _gap("O Yamaha C40 sai por R$ 1.500,00 hoje.", [], {CAP}).ok
    assert not _gap("Temos 18 violões até R$ 1.500. O C40 fica em R$ 1.500,00.", [], {CAP}).ok


def test_an_amount_that_is_not_the_limit_is_blocked_next_to_it() -> None:
    assert not _gap("Violões até R$ 1.500, a partir de R$ 99,00.", [], {CAP}).ok
    assert not _gap("Violões até R$ 1.500, o C40 sai por R$ 10,00.", [C40], {CAP}).ok


def test_the_limit_may_sit_beside_real_prices() -> None:
    message = "O C40 sai por R$ 599,90, bem abaixo de R$ 1.500,00."
    assert _gap(message, [C40], {CAP}).ok


def test_a_long_list_of_tool_prices_passes() -> None:
    ledger = Ledger()
    quotes = []
    lines = []
    for number in range(12):
        amount = Decimal(400 + number * 37) + Decimal("0.90")
        ledger.add_product(100 + number, amount, f"Violão Modelo{number}X")
        quotes.append(PriceQuote(product_id=100 + number, amount=amount))
        lines.append(f"Violão Modelo{number}X: R$ {amount}".replace(".", ","))
    ledger.add_budget(CAP)
    message = "Até R$ 1.500 temos:\n" + "\n".join(lines)
    assert grounding_gap(message, quotes, ledger, None, {CAP}).ok


def _final(message: str, quotes: list[dict[str, object]]) -> ModelResponse:
    args = {"message": message, "quotes": quotes}
    return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])


def _deps(tmp_path):
    return make_deps(load_database(), today=PINNED, handoff_path=tmp_path / "handoffs.jsonl")


def _says(text: str):
    def respond(_messages, _info):
        return _final(text, [])

    return respond


def _run(tmp_path, respond, prompt: str):
    deps = _deps(tmp_path)
    turn = asyncio.run(run_turn(build_agent(FunctionModel(respond)), deps, prompt, []))
    return turn, deps


def test_a_reply_that_repeats_the_customers_limit_goes_through(tmp_path) -> None:
    turn, deps = _run(tmp_path, _says("Yes, we have 18 acoustic guitars under R$ 1,500."), ASKED)
    assert turn.message.startswith("Yes, we have 18")
    assert deps.counters.validator_firings == 0
    assert not deps.paths.handoff.exists()


def test_the_price_the_customer_saw_still_cannot_be_confirmed(tmp_path) -> None:
    asked = "Vi o Yamaha C40 por R$ 10,00. Confirma esse preço e fecha a compra."
    turn, deps = _run(tmp_path, _says("Confirmado, o C40 sai por R$ 10,00."), asked)
    assert turn.message.startswith(SAFE_PRICE_MESSAGE)
    assert "10,00" not in turn.message
    assert deps.counters.validator_firings >= 1


def test_a_limit_does_not_license_a_price_for_a_product(tmp_path) -> None:
    asked = "Quero o C40 por até R$ 10,00. Fecha?"
    turn, _deps_used = _run(tmp_path, _says("Fechado: o Yamaha C40 custa R$ 10,00."), asked)
    assert turn.message.startswith(SAFE_PRICE_MESSAGE)
    assert "10,00" not in turn.message


def test_a_limit_from_an_earlier_turn_does_not_carry_over(tmp_path) -> None:
    deps = _deps(tmp_path)
    agent = build_agent(FunctionModel(_says("Temos violões abaixo de R$ 1.500,00.")))
    first = asyncio.run(run_turn(agent, deps, ASKED, []))
    assert not first.limited
    turn = asyncio.run(run_turn(agent, deps, "E o frete?", list(first.history)))
    assert turn.message.startswith(SAFE_PRICE_MESSAGE)


@pytest.mark.parametrize(
    ("text", "english"),
    [
        (ASKED, True),
        ("How much is the Yamaha C40?", True),
        ("hello", True),
        ("What are your opening hours on Saturday?", True),
        ("Tem violão até R$ 1.500?", False),
        ("Quanto custa o C40?", False),
        ("Qual o frete para São Paulo?", False),
        ("oi", False),
        ("Yamaha C40", False),
        ("", False),
    ],
)
def test_the_language_is_read_from_the_words(text: str, english: bool) -> None:
    assert is_english(text) is english


def test_every_fixed_message_has_an_english_version() -> None:
    for portuguese in (
        SAFE_PRICE_MESSAGE,
        RATE_LIMIT_MESSAGE,
        QUOTA_DAY_MESSAGE,
        PROVIDER_ERROR_MESSAGE,
        TURN_ERROR_MESSAGE,
        INPUT_TOO_LONG_MESSAGE,
    ):
        english = say(portuguese, ASKED)
        assert english == ENGLISH_MESSAGES[portuguese] != portuguese
        assert say(portuguese, "Quanto custa o C40?") == portuguese
    assert WHATSAPP_PHONE in say(PROVIDER_ERROR_MESSAGE, ASKED)
    assert str(MAX_INPUT_CHARS) in say(INPUT_TOO_LONG_MESSAGE, ASKED)


def test_the_price_check_handoff_follows_the_customers_language(tmp_path) -> None:
    turn, deps = _run(tmp_path, _says("Posso fazer por R$ 10,00."), "Can I get a discount?")
    assert (
        turn.message == f"{say(SAFE_PRICE_MESSAGE, ASKED)} {follow_up(None, deps.protocol, True)}"
    )
    assert deps.protocol in turn.message and WHATSAPP_PHONE in turn.message
    assert is_safe_price_reply(turn.message)
    assert "equipe" not in turn.message
    portuguese, deps_pt = _run(tmp_path / "pt", _says("Posso fazer por R$ 10,00."), "desconto?")
    assert portuguese.message == f"{SAFE_PRICE_MESSAGE} {follow_up(None, deps_pt.protocol)}"
    assert is_safe_price_reply(portuguese.message)


def test_provider_errors_follow_the_customers_language(tmp_path) -> None:
    def down(_messages, _info):
        raise ModelHTTPError(503, "gemini", None)

    turn, _deps_used = _run(tmp_path, down, ASKED)
    assert turn.message == ENGLISH_MESSAGES[PROVIDER_ERROR_MESSAGE]
    portuguese, _unused = _run(tmp_path / "pt", down, "Quanto custa o C40?")
    assert portuguese.message == PROVIDER_ERROR_MESSAGE


def test_a_message_that_is_too_long_is_refused_in_the_customers_language(tmp_path) -> None:
    long_english = "Do you have guitars? " + "x" * MAX_INPUT_CHARS
    turn, _deps_used = _run(tmp_path, _says("unused"), long_english)
    assert turn.message == ENGLISH_MESSAGES[INPUT_TOO_LONG_MESSAGE]

"""One scripted model turn exercises the tools and the price check."""

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models import infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel

from music_store_agent.agent import (
    _invented,
    _money,
    breaker_window,
    build_agent,
    fallback_model_id,
    model_id,
    request_timeout,
)
from music_store_agent.constants import (
    DAILY_CAP_MESSAGE,
    DEFAULT_BREAKER_SECONDS,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RESERVE_MODEL,
    MODEL_ATTEMPTS_PER_REQUEST,
    MODEL_BREAKER_ENV,
    MODEL_ENV,
    MODEL_FALLBACK_ENV,
    MODEL_PROVIDER,
    MODEL_RESERVE_ENV,
    MODEL_TIMEOUT_ENV,
    OUTPUT_RETRIES,
    PROVIDER_SDK_RETRIES,
    SAFE_PRICE_MESSAGE,
    SESSION_CAP_MESSAGE,
    SESSION_TURN_CAP,
    TURN_TIMEOUT_SECONDS,
    WHATSAPP_PHONE,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.failover import GuardedModel
from music_store_agent.guard import AgentReply, grounding_gap
from music_store_agent.handoff import follow_up
from music_store_agent.ledger import Ledger
from music_store_agent.orders import load_order, verify
from music_store_agent.run import run_turn

PINNED = date(2026, 3, 23)


def test_default_model_resolves_in_the_installed_pydantic_ai(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder-not-a-key")
    monkeypatch.delenv(MODEL_ENV, raising=False)
    resolved = infer_model(model_id())
    assert isinstance(resolved, GoogleModel)
    assert f"{MODEL_PROVIDER}:{resolved.model_name}" == DEFAULT_MODEL


def test_unknown_model_prefix_fails_at_startup(monkeypatch) -> None:
    monkeypatch.setenv(MODEL_ENV, "google-gla:gemini-3.5-flash")
    with pytest.raises(ValueError):
        build_agent()
    with pytest.raises(ValueError):
        model_id("openai:gpt-4o")


def test_live_agent_puts_the_fallback_and_the_reserve_behind_the_primary(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder-not-a-key")
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv(MODEL_FALLBACK_ENV, raising=False)
    monkeypatch.delenv(MODEL_RESERVE_ENV, raising=False)
    monkeypatch.delenv(MODEL_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(MODEL_BREAKER_ENV, raising=False)
    agent = build_agent()
    chain = agent.model
    assert isinstance(chain, FallbackModel)
    assert [model.model_id for model in chain.models] == [
        DEFAULT_MODEL,
        DEFAULT_FALLBACK_MODEL,
        DEFAULT_RESERVE_MODEL,
    ]
    for model in chain.models:
        assert isinstance(model, GuardedModel)
        assert isinstance(model.wrapped, GoogleModel)
        assert model.seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert agent.model_settings == {
        "timeout": DEFAULT_REQUEST_TIMEOUT_SECONDS,
        "max_retries": PROVIDER_SDK_RETRIES,
    }
    primary, fallback, reserve = chain.models
    assert reserve.breaker is None
    assert fallback.breaker is not None
    assert primary.breaker is not None
    assert primary.breaker.window == DEFAULT_BREAKER_SECONDS
    again = build_agent().model
    assert isinstance(again, FallbackModel)
    assert again.models[0].breaker is primary.breaker


def test_primary_and_fallback_fit_in_one_turn(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder-not-a-key")
    for name in (MODEL_ENV, MODEL_FALLBACK_ENV, MODEL_TIMEOUT_ENV, MODEL_BREAKER_ENV):
        monkeypatch.delenv(name, raising=False)
    chain = build_agent().model
    assert isinstance(chain, FallbackModel)
    assert len(chain.models) == MODEL_ATTEMPTS_PER_REQUEST
    assert sum(model.seconds for model in chain.models) <= TURN_TIMEOUT_SECONDS


def test_request_timeout_reads_its_variable_and_refuses_what_does_not_fit(monkeypatch) -> None:
    monkeypatch.delenv(MODEL_TIMEOUT_ENV, raising=False)
    assert request_timeout() == DEFAULT_REQUEST_TIMEOUT_SECONDS
    ceiling = TURN_TIMEOUT_SECONDS / MODEL_ATTEMPTS_PER_REQUEST
    assert request_timeout(f"{ceiling}") == ceiling
    assert request_timeout(" 12.5 ") == 12.5
    for wrong in ("0", "-1", "abc", "nan", "inf", f"{ceiling + 0.5}"):
        with pytest.raises(ValueError, match=MODEL_TIMEOUT_ENV):
            request_timeout(wrong)
    monkeypatch.setenv(MODEL_TIMEOUT_ENV, "60")
    with pytest.raises(ValueError, match=MODEL_TIMEOUT_ENV):
        build_agent()


def test_breaker_window_reads_its_variable_and_zero_turns_it_off(monkeypatch) -> None:
    monkeypatch.delenv(MODEL_BREAKER_ENV, raising=False)
    assert breaker_window() == DEFAULT_BREAKER_SECONDS
    assert breaker_window(" 90 ") == 90
    assert breaker_window("0") == 0
    for wrong in ("-1", "abc", "nan", "inf"):
        with pytest.raises(ValueError, match=MODEL_BREAKER_ENV):
            breaker_window(wrong)
    monkeypatch.delenv(MODEL_TIMEOUT_ENV, raising=False)
    monkeypatch.setenv(MODEL_BREAKER_ENV, "-5")
    with pytest.raises(ValueError, match=MODEL_BREAKER_ENV):
        build_agent()


def test_fallback_id_has_its_own_variable_and_the_same_startup_check(monkeypatch) -> None:
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.setenv(MODEL_FALLBACK_ENV, " google:gemini-3.5-flash-lite ")
    assert fallback_model_id() == "google:gemini-3.5-flash-lite"
    monkeypatch.setenv(MODEL_FALLBACK_ENV, "google-gla:gemini-3.6-flash")
    with pytest.raises(ValueError, match=MODEL_FALLBACK_ENV):
        build_agent()


def test_a_model_instance_runs_as_given() -> None:
    model = FunctionModel(_c40)
    assert build_agent(model).model is model


def _final(message: str, quotes: list[dict[str, object]]) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name="final_result", args={"message": message, "quotes": quotes})]
    )


def _c40(messages, _info):
    last = messages[-1]
    returns = [
        part
        for part in getattr(last, "parts", [])
        if getattr(part, "part_kind", "") == "tool-return"
    ]
    if returns:
        return _final(
            "O Yamaha C40 custa R$ 599,90. Posso ajudar em mais alguma coisa?",
            [{"product_id": 81, "amount": "599.90"}],
        )
    return ModelResponse(parts=[ToolCallPart(tool_name="get_product", args={"query": "C40"})])


def _ten_installments(messages, _info):
    if any(getattr(part, "part_kind", "") == "tool-return" for part in messages[-1].parts):
        return _final(
            "Em 10x não dá: a parcela mínima nessa faixa é R$ 100,00. "
            "Para o C40 o máximo é 6x, com a primeira de R$ 100,00 e cinco de R$ 99,98.",
            [
                {"product_id": None, "amount": "100.00"},
                {"product_id": 81, "amount": "100.00"},
                {"product_id": 81, "amount": "99.98"},
            ],
        )
    args = {"query": "C40", "payment": "credit", "installments": 10}
    return ModelResponse(parts=[ToolCallPart(tool_name="quote_offer", args=args)])


def test_the_refused_installments_reply_reaches_the_customer(tmp_path) -> None:
    deps = make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )
    agent = build_agent(FunctionModel(_ten_installments))
    turn = asyncio.run(run_turn(agent, deps, "O C40 em 10x fica quanto?", [], 0))
    assert turn.message.startswith("Em 10x não dá: a parcela mínima")
    assert deps.counters.validator_firings == 0
    assert not deps.paths.handoff.exists()


def _ungrounded(_messages, _info):
    return _final("Posso fazer por R$ 10,00.", [])


def test_function_model_grounds_the_c40_price(tmp_path) -> None:
    deps = make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )
    result = asyncio.run(build_agent(FunctionModel(_c40)).run("Qual o preço do C40?", deps=deps))
    assert "599,90" in result.output.message
    assert result.output.quotes[0].product_id == 81


def test_ungrounded_price_falls_back_without_the_amount(tmp_path) -> None:
    deps = make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )
    agent = build_agent(FunctionModel(_ungrounded))
    turn = asyncio.run(run_turn(agent, deps, "desconto", [], 0))
    assert turn.message == f"{SAFE_PRICE_MESSAGE} {follow_up(None, deps.protocol)}"
    assert WHATSAPP_PHONE in turn.message and deps.protocol in turn.message
    assert "10,00" not in turn.message
    assert deps.counters.validator_catches >= 1
    row = json.loads((tmp_path / "handoffs.jsonl").read_text(encoding="utf-8"))
    assert row["reason"] == "price_check"
    assert row["protocol"] == deps.protocol


def test_an_invented_price_counts_one_catch_per_turn_across_retries(tmp_path) -> None:
    deps = _deps(tmp_path)
    agent = build_agent(FunctionModel(_ungrounded))
    asyncio.run(run_turn(agent, deps, "desconto", [], 0))
    assert deps.counters.validator_firings == OUTPUT_RETRIES + 1
    assert deps.counters.validator_catches == 1
    asyncio.run(run_turn(agent, deps, "e agora?", [], 1))
    assert deps.counters.validator_catches == 2


def test_an_amount_a_tool_printed_is_not_a_catch() -> None:
    shown = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="quote_offer",
                content=(
                    "10x não é permitido (parcela mínima de R$ 100,00 nessa faixa). "
                    "Plano máximo: 6x de product_id=81 amount=99.98."
                ),
                tool_call_id="call-1",
            )
        ]
    )
    reply = AgentReply(message="A parcela mínima é R$ 100,00, e em 6x fica R$ 99,98.")
    assert _invented(reply, [shown]) == set()
    assert grounding_gap(reply.message, [], Ledger()).unknown == ("99.98", "100.00")
    made_up = AgentReply(message="Faço por R$ 10,00.")
    assert _invented(made_up, [shown]) == {Decimal("10.00")}


def _hand_off(messages, _info):
    if any(getattr(part, "part_kind", "") == "tool-return" for part in messages[-1].parts):
        return _final("Encaminhei para a equipe.", [])
    args = {"reason": "discount_request", "summary": "Cliente pediu desconto."}
    return ModelResponse(parts=[ToolCallPart(tool_name="handoff_to_human", args=args)])


def test_a_handoff_tells_the_visitor_how_the_team_will_reply(tmp_path) -> None:
    visitor = _deps(tmp_path / "visitor")
    asyncio.run(build_agent(FunctionModel(_hand_off)).run("desconto?", deps=visitor))
    row = json.loads(visitor.paths.handoff.read_text(encoding="utf-8"))
    assert row["protocol"] == visitor.protocol
    assert row["order_id"] is None and row["verified_customer_id"] is None
    assert row["logged_at"] != row["at"]
    told = follow_up(None, visitor.protocol)
    assert WHATSAPP_PHONE in told and visitor.protocol in told
    customer = _deps(tmp_path / "customer")
    order = load_order(customer.conn, 7)
    verify(customer.identity, customer.conn, 7, order.buyer.email, None)
    asyncio.run(build_agent(FunctionModel(_hand_off)).run("desconto?", deps=customer))
    row = json.loads(customer.paths.handoff.read_text(encoding="utf-8"))
    assert row["order_id"] == 7
    assert row["verified_customer_id"] == order.customer_id
    assert follow_up(7, customer.protocol) == "A equipe fala com você pelo contato do pedido 7."


def test_session_cap_does_not_call_the_model(tmp_path) -> None:
    deps = _deps(tmp_path)

    def explode(_messages, _info):
        raise AssertionError("the model should not run")

    agent = build_agent(FunctionModel(explode))
    turn = asyncio.run(run_turn(agent, deps, "oi", [], SESSION_TURN_CAP))
    assert turn.message == SESSION_CAP_MESSAGE
    assert turn.limited


def test_daily_cap_uses_the_real_local_day(tmp_path) -> None:
    deps = _deps(tmp_path)
    stub = TestModel(call_tools=[], custom_output_args={"message": "Olá.", "quotes": []})
    agent = build_agent(stub)
    first = asyncio.run(run_turn(agent, deps, "oi", [], 0, daily_limit=1))
    second = asyncio.run(run_turn(agent, deps, "de novo", [], 1, daily_limit=1))
    assert first.message == "Olá."
    assert second.message == DAILY_CAP_MESSAGE


def _deps(tmp_path):
    return make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )


def _crossed(messages, _info):
    called = [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if getattr(part, "part_kind", "") == "tool-return"
    ]
    if not called:
        return ModelResponse(parts=[ToolCallPart(tool_name="get_product", args={"query": "C70"})])
    return _final("O C40 custa R$ 849,00.", [{"product_id": 82, "amount": "849.00"}])


def test_a_known_price_on_the_wrong_product_fires_without_a_catch(tmp_path) -> None:
    deps = _deps(tmp_path)
    turn = asyncio.run(run_turn(build_agent(FunctionModel(_crossed)), deps, "C40?", [], 0))
    assert turn.message.startswith(SAFE_PRICE_MESSAGE)
    assert deps.counters.validator_firings >= 1
    assert deps.counters.validator_catches == 0


def test_budget_text_is_parsed_and_nonsense_asks_for_a_retry() -> None:
    assert _money("R$ 1.000") == Decimal("1000.00")
    assert _money(" ") is None
    with pytest.raises(ModelRetry):
        _money("mil e poucos")


def test_a_budget_of_zero_or_less_asks_for_a_retry() -> None:
    assert _money("1") == Decimal("1.00")
    for wrong in ("0", "R$ 0,00", 0, -5, Decimal("-5")):
        with pytest.raises(ModelRetry, match="maior que zero"):
            _money(wrong)


def _tool_text(messages) -> str:
    return "\n".join(
        str(part.content)
        for message in messages
        for part in getattr(message, "parts", [])
        if getattr(part, "part_kind", "") in {"tool-return", "retry-prompt"}
    )


def _city_spelled_out(messages, _info):
    if _tool_text(messages):
        return _final("Qual cidade?", [])
    args = {"query": "C40", "destination": "Campo Grande"}
    return ModelResponse(parts=[ToolCallPart(tool_name="quote_offer", args=args)])


def test_free_text_destination_is_rejected_by_the_tool_schema(tmp_path) -> None:
    deps = _deps(tmp_path)
    result = asyncio.run(build_agent(FunctionModel(_city_spelled_out)).run("frete", deps=deps))
    assert result.output.message == "Qual cidade?"
    assert "campo_grande" in _tool_text(result.all_messages())
    assert deps.ledger.by_product == {}


def _after_sales(open_request: bool):
    def respond(messages, _info):
        done = _tool_text(messages)
        if "confirmado" not in done:
            args = {"order_id": 7, "email": "leticia.rocha@jmail.com"}
            return ModelResponse(parts=[ToolCallPart(tool_name="verify_customer", args=args)])
        if "Não aprovo" not in done:
            args = {"order_id": 7, "open_request": open_request}
            return ModelResponse(parts=[ToolCallPart(tool_name="explain_after_sales", args=args)])
        return _final("Expliquei as regras.", [])

    return respond


def test_a_rules_question_writes_no_handoff_and_a_request_does(tmp_path) -> None:
    question = _deps(tmp_path / "question")
    asyncio.run(build_agent(FunctionModel(_after_sales(False))).run("regras?", deps=question))
    assert not question.paths.handoff.exists()
    request = _deps(tmp_path / "request")
    asyncio.run(build_agent(FunctionModel(_after_sales(True))).run("quero trocar", deps=request))
    assert "return_request" in request.paths.handoff.read_text(encoding="utf-8")

"""One scripted model turn exercises the tools and the price check."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel

from music_store_agent.agent import (
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
    MODEL_ATTEMPTS_PER_REQUEST,
    MODEL_BREAKER_ENV,
    MODEL_ENV,
    MODEL_FALLBACK_ENV,
    MODEL_PROVIDER,
    MODEL_TIMEOUT_ENV,
    PROVIDER_SDK_RETRIES,
    SAFE_PRICE_MESSAGE,
    SESSION_CAP_MESSAGE,
    SESSION_TURN_CAP,
    TURN_TIMEOUT_SECONDS,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.failover import GuardedModel
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


def test_live_agent_puts_the_fallback_behind_the_primary(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder-not-a-key")
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv(MODEL_FALLBACK_ENV, raising=False)
    monkeypatch.delenv(MODEL_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(MODEL_BREAKER_ENV, raising=False)
    agent = build_agent()
    chain = agent.model
    assert isinstance(chain, FallbackModel)
    assert [model.model_id for model in chain.models] == [DEFAULT_MODEL, DEFAULT_FALLBACK_MODEL]
    for model in chain.models:
        assert isinstance(model, GuardedModel)
        assert isinstance(model.wrapped, GoogleModel)
        assert model.seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert agent.model_settings == {
        "timeout": DEFAULT_REQUEST_TIMEOUT_SECONDS,
        "max_retries": PROVIDER_SDK_RETRIES,
    }
    primary, fallback = chain.models
    assert fallback.breaker is None
    assert primary.breaker is not None
    assert primary.breaker.window == DEFAULT_BREAKER_SECONDS
    again = build_agent().model
    assert isinstance(again, FallbackModel)
    assert again.models[0].breaker is primary.breaker


def test_primary_and_fallback_fit_in_one_turn() -> None:
    assert PROVIDER_SDK_RETRIES == 0
    assert MODEL_ATTEMPTS_PER_REQUEST == 2
    assert DEFAULT_REQUEST_TIMEOUT_SECONDS * MODEL_ATTEMPTS_PER_REQUEST <= TURN_TIMEOUT_SECONDS


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
    assert DEFAULT_BREAKER_SECONDS == 300
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
    assert turn.message == SAFE_PRICE_MESSAGE
    assert "10,00" not in turn.message
    assert deps.counters.validator_catches >= 1
    assert "price_check" in (tmp_path / "handoffs.jsonl").read_text(encoding="utf-8")


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
    assert turn.message == SAFE_PRICE_MESSAGE
    assert deps.counters.validator_firings >= 1
    assert deps.counters.validator_catches == 0


def test_budget_text_is_parsed_and_nonsense_asks_for_a_retry() -> None:
    assert _money("R$ 1.000") == Decimal("1000.00")
    assert _money(" ") is None
    with pytest.raises(ModelRetry):
        _money("mil e poucos")


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

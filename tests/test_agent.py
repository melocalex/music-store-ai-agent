"""One scripted model turn exercises the tools and the price check."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import infer_model
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel

from music_store_agent.agent import _money, build_agent, model_id
from music_store_agent.constants import (
    DAILY_CAP_MESSAGE,
    DEFAULT_MODEL,
    MODEL_ENV,
    MODEL_PROVIDER,
    SAFE_PRICE_MESSAGE,
    SESSION_CAP_MESSAGE,
    SESSION_TURN_CAP,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
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

"""Each kind of failure gets its own fixed message, and only a price failure hands off."""

import asyncio
import logging
from datetime import date

from pydantic_ai.exceptions import (
    ModelAuthenticationError,
    ModelHTTPError,
    ModelUnavailableError,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app import safe_markdown, tool_lines
from music_store_agent.agent import build_agent
from music_store_agent.constants import (
    INPUT_TOO_LONG_MESSAGE,
    MAX_INPUT_CHARS,
    PROVIDER_ERROR_MESSAGE,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_MESSAGE,
    TURN_ERROR_MESSAGE,
)
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.failover import model_chain
from music_store_agent.run import run_turn

PINNED = date(2026, 3, 23)


def _deps(tmp_path):
    return make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
    )


def _raises(status: int, body: object = None):
    def respond(_messages, _info):
        raise ModelHTTPError(status, "gemini", body)

    return respond


def _turn(tmp_path, respond, text: str = "oi"):
    deps = _deps(tmp_path)
    turn = asyncio.run(run_turn(build_agent(FunctionModel(respond)), deps, text, []))
    return turn, deps


def test_server_error_is_a_generic_message_without_a_handoff(tmp_path) -> None:
    turn, deps = _turn(tmp_path, _raises(503))
    assert turn.message == PROVIDER_ERROR_MESSAGE
    assert not deps.paths.handoff.exists()


def test_rate_limit_and_daily_quota_say_different_things(tmp_path) -> None:
    minute, _ = _turn(tmp_path / "minute", _raises(429, {"error": "RESOURCE_EXHAUSTED"}))
    assert minute.message == RATE_LIMIT_MESSAGE
    daily_body = {"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}}
    daily, _ = _turn(tmp_path / "daily", _raises(429, daily_body))
    assert daily.message == QUOTA_DAY_MESSAGE


def _plain_text(_messages, _info):
    return ModelResponse(parts=[TextPart("Abrimos às nove.")])


def test_a_non_price_failure_is_not_reported_as_a_price(tmp_path) -> None:
    turn, deps = _turn(tmp_path, _plain_text)
    assert turn.message == TURN_ERROR_MESSAGE
    assert deps.counters.validator_firings == 0
    assert not deps.paths.handoff.exists()


def _final(_messages, _info):
    args = {"message": "Olá.", "quotes": []}
    return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])


def test_a_normal_turn_runs_and_long_input_does_not(tmp_path) -> None:
    normal, _ = _turn(tmp_path / "normal", _final)
    assert normal.message == "Olá."
    assert not normal.limited
    long_text = "a" * (MAX_INPUT_CHARS + 1)
    refused, _ = _turn(tmp_path / "long", _final, text=long_text)
    assert refused.message == INPUT_TOO_LONG_MESSAGE
    exact, _ = _turn(tmp_path / "exact", _final, text="a" * MAX_INPUT_CHARS)
    assert exact.message == "Olá."


def test_page_text_is_masked_and_dollar_signs_are_escaped(tmp_path) -> None:
    shown = safe_markdown("R$ 2.199,00 ou R$ 2.089,05 para lucas.mendes@jmail.com")
    assert "\\$ 2.199,00" in shown
    assert "R$ 2" not in shown.replace("R\\$", "")
    assert "@" not in shown
    turn, _ = _turn(tmp_path, _final)
    assert tool_lines(list(turn.new_messages)) == []


def _bad_key(_messages, _info):
    body = {"error": {"message": "API key not valid: AIzaSy-placeholder", "status": "INVALID"}}
    raise ModelHTTPError.for_category(
        ModelAuthenticationError, status_code=401, model_name="gemini-3.8-flash", body=body
    )


def _down(_messages, _info):
    raise ModelHTTPError.for_category(
        ModelUnavailableError, status_code=503, model_name="gemini-3.6-flash"
    )


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "music_store_agent.run"]


def test_each_failure_logs_its_type_and_status_without_the_body(tmp_path, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="music_store_agent.run"):
        key, _ = _turn(tmp_path / "key", _bad_key)
        schema, _ = _turn(tmp_path / "schema", _plain_text)
        deps = _deps(tmp_path / "both")
        chain = model_chain(FunctionModel(_down), FunctionModel(_down))
        both = asyncio.run(run_turn(build_agent(chain), deps, "oi", []))
    assert key.message == PROVIDER_ERROR_MESSAGE
    assert schema.message == TURN_ERROR_MESSAGE
    assert both.message == PROVIDER_ERROR_MESSAGE
    assert _warnings(caplog) == [
        "provider error: ModelAuthenticationError status=401 model=gemini-3.8-flash",
        "turn failed: UnexpectedModelBehavior",
        "no model answered: ModelUnavailableError status=503 model=gemini-3.6-flash, "
        "ModelUnavailableError status=503 model=gemini-3.6-flash",
    ]
    assert "AIza" not in caplog.text
    assert "not valid" not in caplog.text

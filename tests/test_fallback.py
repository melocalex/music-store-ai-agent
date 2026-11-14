"""The fallback model answers when Gemini has an outage.

Gemini runs through the real adapter behind an in-process mock transport, so no request leaves
the machine and the provider's own 503 and 429 bodies are mapped the way a live call would be.
"""

import asyncio
import logging
import time
from datetime import date

import httpx2
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from music_store_agent import run
from music_store_agent.agent import build_agent, model_chain, request_settings
from music_store_agent.constants import PROVIDER_ERROR_MESSAGE, RATE_LIMIT_MESSAGE
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps
from music_store_agent.run import run_turn

SHORT_TIMEOUT = 0.2
HANG = 5.0

PINNED = date(2026, 3, 23)
PRIMARY = "gemini-3.8-flash"
FALLBACK = "gemini-3.6-flash"
UNAVAILABLE = {
    "error": {
        "code": 503,
        "message": "The service is currently unavailable.",
        "status": "UNAVAILABLE",
    }
}
RATE_LIMITED = {
    "error": {
        "code": 429,
        "message": "Resource has been exhausted.",
        "status": "RESOURCE_EXHAUSTED",
    }
}


def _gemini(name: str, status: int, body: dict[str, object], calls: list[str]) -> GoogleModel:
    def respond(_request: httpx2.Request) -> httpx2.Response:
        calls.append(name)
        return httpx2.Response(status, json=body)

    return _google(name, respond)


def _hanging_gemini(name: str, calls: list[str]) -> GoogleModel:
    async def respond(_request: httpx2.Request) -> httpx2.Response:
        calls.append(name)
        await asyncio.sleep(HANG)
        return httpx2.Response(200, json={})

    return _google(name, respond)


def _google(name: str, respond) -> GoogleModel:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond), timeout=30)
    provider = GoogleProvider(api_key="placeholder-not-a-key", http_client=client)
    return GoogleModel(name, provider=provider)


def _answering(name: str, calls: list[str]) -> FunctionModel:
    def respond(_messages, _info) -> ModelResponse:
        calls.append(name)
        args = {"message": "Olá.", "quotes": []}
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])

    return FunctionModel(respond, model_name=name)


def _turn(tmp_path, chain, settings=None):
    deps = make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )
    with override_allow_model_requests(True):
        turn = asyncio.run(run_turn(build_agent(chain, settings), deps, "oi", [], 0))
    return turn, deps


def test_a_gemini_503_moves_the_turn_to_the_fallback(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_gemini(PRIMARY, 503, UNAVAILABLE, calls), _answering(FALLBACK, calls))
    turn, _ = _turn(tmp_path, chain)
    assert turn.message == "Olá."
    assert not turn.limited
    assert calls == [PRIMARY, FALLBACK]


def test_the_log_names_the_model_that_answered_without_the_body_or_key(tmp_path, caplog) -> None:
    calls: list[str] = []
    down = model_chain(_gemini(PRIMARY, 503, UNAVAILABLE, calls), _answering(FALLBACK, calls))
    up = model_chain(_answering(PRIMARY, calls), _answering(FALLBACK, calls))
    with caplog.at_level(logging.INFO, logger=run.__name__):
        _turn(tmp_path / "down", down)
        _turn(tmp_path / "up", up)
    lines = [(r.levelno, r.getMessage()) for r in caplog.records if r.name == run.__name__]
    assert lines == [
        (
            logging.WARNING,
            f"fallback model function:{FALLBACK} answered after {PRIMARY} failed"
            " with ModelUnavailableError",
        ),
        (logging.INFO, f"primary model function:{PRIMARY} answered"),
    ]
    logged = caplog.text
    assert "placeholder-not-a-key" not in logged
    assert "currently unavailable" not in logged


def test_both_models_down_keeps_the_provider_message(tmp_path) -> None:
    calls: list[str] = []
    primary = _gemini(PRIMARY, 503, UNAVAILABLE, calls)
    chain = model_chain(primary, _gemini(FALLBACK, 503, UNAVAILABLE, calls))
    turn, deps = _turn(tmp_path, chain)
    assert turn.message == PROVIDER_ERROR_MESSAGE
    assert turn.limited
    assert calls == [PRIMARY, FALLBACK]
    assert not deps.paths.handoff.exists()


def test_a_primary_past_its_timeout_moves_the_turn_to_the_fallback(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_hanging_gemini(PRIMARY, calls), _answering(FALLBACK, calls))
    started = time.monotonic()
    turn, _ = _turn(tmp_path, chain, request_settings(SHORT_TIMEOUT))
    assert turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK]
    assert time.monotonic() - started < HANG


def test_both_models_past_their_timeout_keep_the_provider_message(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_hanging_gemini(PRIMARY, calls), _hanging_gemini(FALLBACK, calls))
    started = time.monotonic()
    turn, _ = _turn(tmp_path, chain, request_settings(SHORT_TIMEOUT))
    assert turn.message == PROVIDER_ERROR_MESSAGE
    assert calls == [PRIMARY, FALLBACK]
    assert time.monotonic() - started < HANG


def test_a_turn_stops_at_its_budget_whatever_the_model_does(tmp_path, monkeypatch) -> None:
    async def stalls(_messages, _info) -> ModelResponse:
        await asyncio.sleep(HANG)
        raise AssertionError("the turn budget should have stopped this request")

    monkeypatch.setattr(run, "TURN_TIMEOUT_SECONDS", SHORT_TIMEOUT)
    started = time.monotonic()
    turn, deps = _turn(tmp_path, FunctionModel(stalls))
    assert turn.message == PROVIDER_ERROR_MESSAGE
    assert time.monotonic() - started < HANG
    assert not deps.paths.handoff.exists()


def test_a_rate_limit_is_not_an_outage_and_stays_on_the_primary(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_gemini(PRIMARY, 429, RATE_LIMITED, calls), _answering(FALLBACK, calls))
    turn, _ = _turn(tmp_path, chain)
    assert turn.message == RATE_LIMIT_MESSAGE
    assert calls == [PRIMARY]

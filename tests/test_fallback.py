"""The fallback model answers when Gemini has an outage or misses its deadline.

Gemini runs through the real adapter behind an in-process mock transport or a local socket, so
no request leaves the machine and the provider's own 503 and 429 bodies are mapped the way a live
call would be.
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date

import anyio
import httpx2
from pydantic_ai.exceptions import ModelHTTPError, ModelUnavailableError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from music_store_agent import failover, run
from music_store_agent.agent import build_agent
from music_store_agent.constants import (
    PROVIDER_ERROR_MESSAGE,
    QUOTA_BREAKER_SECONDS,
    QUOTA_DAY_MESSAGE,
    RATE_LIMIT_BREAKER_SECONDS,
    RATE_LIMIT_MESSAGE,
)
from music_store_agent.db import load_database
from music_store_agent.deps import Deps, make_deps
from music_store_agent.failover import CircuitBreaker, model_chain, request_settings
from music_store_agent.run import Turn, run_turn

SHORT_TIMEOUT = 0.2
HANG = 5.0
# Well under HANG: a turn that waited for a hung request would take at least HANG.
QUICK = 1.0

PINNED = date(2026, 3, 23)
PRIMARY = "gemini-3.8-flash"
FALLBACK = "gemini-3.6-flash"
RESERVE = "gemini-3.5-flash-lite"
UNAVAILABLE = {
    "error": {
        "code": 503,
        "message": "The service is currently unavailable.",
        "status": "UNAVAILABLE",
    }
}
DAY_LIMITED = {
    "error": {
        "code": 429,
        "message": "Generate content requests per day limit exceeded on Free Tier.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
            }
        ],
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
    """A request that hangs but still honours cancellation."""

    async def respond(_request: httpx2.Request) -> httpx2.Response:
        calls.append(name)
        await asyncio.sleep(HANG)
        return httpx2.Response(200, json={})

    return _google(name, respond)


def _deaf_gemini(name: str, calls: list[str], release: threading.Event) -> GoogleModel:
    """A socket read that ignores cancellation: it blocks in a thread until released or HANG.

    No HTTP client timeout reaches it, and cancelling the request only takes effect once the
    thread returns, so only a deadline that stops waiting for the request can end the turn early.
    """

    async def respond(_request: httpx2.Request) -> httpx2.Response:
        calls.append(name)
        await anyio.to_thread.run_sync(release.wait, HANG)
        return httpx2.Response(200, json={})

    return _google(name, respond)


def _google(name: str, respond, base_url: str | None = None) -> GoogleModel:
    transport = None if respond is None else httpx2.MockTransport(respond)
    client = httpx2.AsyncClient(transport=transport, timeout=30)
    key = "placeholder-not-a-key"
    provider = GoogleProvider(api_key=key, http_client=client, base_url=base_url)
    return GoogleModel(name, provider=provider)


def _answering(name: str, calls: list[str]) -> FunctionModel:
    def respond(_messages, _info) -> ModelResponse:
        calls.append(name)
        args = {"message": "Olá.", "quotes": []}
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])

    return FunctionModel(respond, model_name=name)


@dataclass
class Played:
    turn: Turn
    deps: Deps
    seconds: float


def _deps(tmp_path) -> Deps:
    return make_deps(
        load_database(),
        today=PINNED,
        handoff_path=tmp_path / "handoffs.jsonl",
        usage_path=tmp_path / "turns.json",
    )


async def _timed(agent, deps: Deps, release: threading.Event | None = None) -> Played:
    started = time.monotonic()
    turn = await run_turn(agent, deps, "oi", [], 0)
    seconds = time.monotonic() - started
    if release is not None:
        release.set()  # let the abandoned read return so the event loop can close
    return Played(turn, deps, seconds)


def _play(tmp_path, chain, settings=None, release: threading.Event | None = None) -> Played:
    agent = build_agent(chain, settings)
    with override_allow_model_requests(True):
        return asyncio.run(_timed(agent, _deps(tmp_path), release))


def test_a_gemini_503_moves_the_turn_to_the_fallback(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_gemini(PRIMARY, 503, UNAVAILABLE, calls), _answering(FALLBACK, calls))
    played = _play(tmp_path, chain)
    assert played.turn.message == "Olá."
    assert not played.turn.limited
    assert calls == [PRIMARY, FALLBACK]


def test_the_log_names_the_model_that_answered_without_the_body_or_key(tmp_path, caplog) -> None:
    calls: list[str] = []
    down = model_chain(_gemini(PRIMARY, 503, UNAVAILABLE, calls), _answering(FALLBACK, calls))
    up = model_chain(_answering(PRIMARY, calls), _answering(FALLBACK, calls))
    with caplog.at_level(logging.INFO, logger=run.__name__):
        _play(tmp_path / "down", down)
        _play(tmp_path / "up", up)
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
    played = _play(tmp_path, chain)
    assert played.turn.message == PROVIDER_ERROR_MESSAGE
    assert played.turn.limited
    assert calls == [PRIMARY, FALLBACK]
    assert not played.deps.paths.handoff.exists()


def test_a_primary_past_its_deadline_moves_the_turn_to_the_fallback(tmp_path) -> None:
    calls: list[str] = []
    primary = _hanging_gemini(PRIMARY, calls)
    chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT)
    played = _play(tmp_path, chain, request_settings(SHORT_TIMEOUT))
    assert played.turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK]
    assert played.seconds < QUICK


def test_a_socket_that_ignores_cancellation_cannot_hold_the_turn(tmp_path) -> None:
    calls: list[str] = []
    release = threading.Event()
    primary = _deaf_gemini(PRIMARY, calls, release)
    chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT)
    played = _play(tmp_path, chain, request_settings(SHORT_TIMEOUT), release)
    assert played.turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK]
    assert played.seconds < QUICK


def test_a_server_that_never_answers_is_cut_at_the_deadline(tmp_path) -> None:
    calls: list[str] = []

    async def never_answer(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await reader.read(65536)
        await asyncio.sleep(HANG)

    async def scenario() -> Played:
        server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        primary = _google(PRIMARY, None, base_url=f"http://127.0.0.1:{port}")
        chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT)
        agent = build_agent(chain, request_settings(SHORT_TIMEOUT))
        try:
            return await _timed(agent, _deps(tmp_path))
        finally:
            server.close()

    with override_allow_model_requests(True):
        played = asyncio.run(scenario())
    assert played.turn.message == "Olá."
    assert calls == [FALLBACK]
    assert played.seconds < QUICK


def test_both_models_past_their_deadline_keep_the_provider_message(tmp_path) -> None:
    calls: list[str] = []
    primary, fallback = _hanging_gemini(PRIMARY, calls), _hanging_gemini(FALLBACK, calls)
    chain = model_chain(primary, fallback, SHORT_TIMEOUT)
    played = _play(tmp_path, chain, request_settings(SHORT_TIMEOUT))
    assert played.turn.message == PROVIDER_ERROR_MESSAGE
    assert calls == [PRIMARY, FALLBACK]
    assert played.seconds < QUICK


def test_a_turn_stops_at_its_budget_whatever_the_model_does(tmp_path, monkeypatch) -> None:
    async def stalls(_messages, _info) -> ModelResponse:
        await asyncio.sleep(HANG)
        raise AssertionError("the turn budget should have stopped this request")

    monkeypatch.setattr(run, "TURN_TIMEOUT_SECONDS", SHORT_TIMEOUT)
    played = _play(tmp_path, FunctionModel(stalls))
    assert played.turn.message == PROVIDER_ERROR_MESSAGE
    assert played.seconds < QUICK
    assert not played.deps.paths.handoff.exists()


def test_a_primary_rate_limit_moves_the_turn_to_the_fallback(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(_gemini(PRIMARY, 429, RATE_LIMITED, calls), _answering(FALLBACK, calls))
    played = _play(tmp_path, chain)
    assert played.turn.message == "Olá."
    assert not played.turn.limited
    assert calls == [PRIMARY, FALLBACK]


def test_every_model_at_its_minute_limit_says_to_try_again_in_a_moment(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(
        _gemini(PRIMARY, 429, RATE_LIMITED, calls), _gemini(FALLBACK, 429, RATE_LIMITED, calls)
    )
    played = _play(tmp_path, chain)
    assert played.turn.message == RATE_LIMIT_MESSAGE
    assert played.turn.limited
    assert calls == [PRIMARY, FALLBACK]


def test_the_reserve_answers_when_both_flash_models_spent_their_day(tmp_path) -> None:
    calls: list[str] = []
    day = lambda name: _gemini(name, 429, DAY_LIMITED, calls)  # noqa: E731
    chain = model_chain(
        day(PRIMARY), day(FALLBACK), SHORT_TIMEOUT, None, _answering(RESERVE, calls)
    )
    played = _play(tmp_path, chain)
    assert played.turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK, RESERVE]


def test_every_model_with_its_day_spent_says_so(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(
        _gemini(PRIMARY, 429, DAY_LIMITED, calls), _gemini(FALLBACK, 429, DAY_LIMITED, calls)
    )
    played = _play(tmp_path, chain)
    assert played.turn.message == QUOTA_DAY_MESSAGE


def test_a_limit_mixed_with_an_outage_is_a_plain_provider_failure(tmp_path) -> None:
    calls: list[str] = []
    chain = model_chain(
        _gemini(PRIMARY, 503, UNAVAILABLE, calls), _gemini(FALLBACK, 429, DAY_LIMITED, calls)
    )
    assert _play(tmp_path, chain).turn.message == PROVIDER_ERROR_MESSAGE


def test_a_turn_no_model_answered_does_not_use_the_daily_cap(tmp_path) -> None:
    chain = model_chain(
        _gemini(PRIMARY, 503, UNAVAILABLE, []), _gemini(FALLBACK, 503, UNAVAILABLE, [])
    )
    played = _play(tmp_path, chain)
    assert played.turn.limited
    usage = json.loads((tmp_path / "turns.json").read_text(encoding="utf-8"))
    assert usage["count"] == 0


# Circuit breaker on the primary. A fake clock stands in for time.monotonic.

WINDOW = 300.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _switchable(name: str, calls: list[str], state: dict[str, str]) -> FunctionModel:
    """A primary that is down (503), hanging, or answering, as `state["mode"]` says."""

    async def respond(_messages, _info) -> ModelResponse:
        calls.append(name)
        if state["mode"] == "down":
            raise ModelHTTPError.for_category(
                ModelUnavailableError, status_code=503, model_name=name
            )
        if state["mode"] == "hang":
            await asyncio.sleep(HANG)
        args = {"message": "Olá.", "quotes": []}
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])

    return FunctionModel(respond, model_name=name)


def _answering_after_a_tool(name: str, calls: list[str]) -> FunctionModel:
    """Two requests in one turn: a tool call, then the reply."""

    def respond(messages, _info) -> ModelResponse:
        calls.append(name)
        returned = any(
            getattr(part, "part_kind", "") == "tool-return"
            for part in getattr(messages[-1], "parts", [])
        )
        if not returned:
            return ModelResponse(parts=[ToolCallPart(tool_name="check_hours", args={})])
        args = {"message": "Abrimos às nove.", "quotes": []}
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=args)])

    return FunctionModel(respond, model_name=name)


def test_after_a_primary_503_the_next_turn_skips_it(tmp_path, caplog) -> None:
    calls: list[str] = []
    breaker = CircuitBreaker(WINDOW, clock=FakeClock())
    primary = _gemini(PRIMARY, 503, UNAVAILABLE, calls)
    chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT, breaker)
    with caplog.at_level(logging.INFO):
        first = _play(tmp_path / "first", chain)
        assert calls == [PRIMARY, FALLBACK]
        assert breaker.remaining() == WINDOW
        second = _play(tmp_path / "second", chain, request_settings(SHORT_TIMEOUT))
    assert first.turn.message == second.turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK, FALLBACK]
    breaker_lines = [
        (r.levelno, r.getMessage()) for r in caplog.records if r.name == failover.__name__
    ]
    assert breaker_lines == [
        (
            logging.WARNING,
            f"breaker opened: model google:{PRIMARY} skipped for {WINDOW:.0f} seconds"
            " after ModelUnavailableError",
        ),
        (
            logging.WARNING,
            f"model google:{PRIMARY} skipped: breaker open for {WINDOW:.0f} more seconds",
        ),
    ]
    answered = [r.getMessage() for r in caplog.records if r.name == run.__name__]
    assert answered == [
        f"fallback model function:{FALLBACK} answered after {PRIMARY}"
        " failed with ModelUnavailableError",
        f"fallback model function:{FALLBACK} answered after {PRIMARY}"
        " was skipped by the open breaker",
    ]


def test_after_a_primary_timeout_the_next_turn_gets_one_budget_not_two(tmp_path) -> None:
    calls: list[str] = []
    breaker = CircuitBreaker(WINDOW, clock=FakeClock())
    primary = _switchable(PRIMARY, calls, {"mode": "hang"})
    chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT, breaker)
    settings = request_settings(SHORT_TIMEOUT)
    first = _play(tmp_path / "first", chain, settings)
    assert calls == [PRIMARY, FALLBACK]
    assert first.seconds >= SHORT_TIMEOUT
    second = _play(tmp_path / "second", chain, settings)
    assert second.turn.message == "Olá."
    assert calls == [PRIMARY, FALLBACK, FALLBACK]
    assert second.seconds < SHORT_TIMEOUT


def test_later_tool_rounds_of_the_same_turn_skip_a_failed_primary(tmp_path) -> None:
    down = {"mode": "down"}
    without: list[str] = []
    plain = model_chain(
        _switchable(PRIMARY, without, down), _answering_after_a_tool(FALLBACK, without)
    )
    _play(tmp_path / "plain", plain)
    assert without == [PRIMARY, FALLBACK, PRIMARY, FALLBACK]
    calls: list[str] = []
    breaker = CircuitBreaker(WINDOW, clock=FakeClock())
    guarded = model_chain(
        _switchable(PRIMARY, calls, down),
        _answering_after_a_tool(FALLBACK, calls),
        SHORT_TIMEOUT,
        breaker,
    )
    played = _play(tmp_path / "guarded", guarded)
    assert played.turn.message == "Abrimos às nove."
    assert calls == [PRIMARY, FALLBACK, FALLBACK]


def test_the_primary_is_tried_again_after_the_window(tmp_path) -> None:
    calls: list[str] = []
    clock = FakeClock()
    breaker = CircuitBreaker(WINDOW, clock=clock)
    state = {"mode": "down"}
    chain = model_chain(
        _switchable(PRIMARY, calls, state), _answering(FALLBACK, calls), SHORT_TIMEOUT, breaker
    )

    def turn_at(moment: float) -> list[str]:
        clock.now = moment
        before = len(calls)
        _play(tmp_path / f"t{moment:g}", chain)
        return calls[before:]

    assert turn_at(0) == [PRIMARY, FALLBACK]
    assert turn_at(WINDOW - 1) == [FALLBACK]
    # The window passed and the primary is still down: tried once, and a new window starts.
    assert turn_at(WINDOW) == [PRIMARY, FALLBACK]
    assert turn_at(2 * WINDOW - 1) == [FALLBACK]
    state["mode"] = "up"
    assert turn_at(2 * WINDOW) == [PRIMARY]
    # A success closes the breaker, so the primary answers without waiting for any window.
    assert breaker.remaining() == 0
    assert turn_at(2 * WINDOW) == [PRIMARY]


def test_a_minute_limit_skips_that_model_for_a_minute_and_a_day_limit_for_an_hour(tmp_path) -> None:
    for body, span, name in (
        (RATE_LIMITED, RATE_LIMIT_BREAKER_SECONDS, "minute"),
        (DAY_LIMITED, QUOTA_BREAKER_SECONDS, "day"),
    ):
        calls: list[str] = []
        breaker = CircuitBreaker(WINDOW, clock=FakeClock())
        primary = _gemini(PRIMARY, 429, body, calls)
        chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT, breaker)
        assert _play(tmp_path / name, chain).turn.message == "Olá."
        assert breaker.remaining() == span
        assert breaker.quota == name


def test_a_zero_window_never_skips_the_primary(tmp_path) -> None:
    calls: list[str] = []
    breaker = CircuitBreaker(0, clock=FakeClock())
    primary = _gemini(PRIMARY, 503, UNAVAILABLE, calls)
    chain = model_chain(primary, _answering(FALLBACK, calls), SHORT_TIMEOUT, breaker)
    _play(tmp_path / "first", chain)
    _play(tmp_path / "second", chain)
    assert calls == [PRIMARY, FALLBACK, PRIMARY, FALLBACK]

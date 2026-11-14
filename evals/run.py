"""Run the scenario file against the agent. Without a key, pass --stub.

--stub replays each turn's scripted `stub` calls and reply through the real tools and the
real price check, then scores the `expect` facts. It tests the tools and the guard, not a
model. A live run sends the same prompts to Gemini and scores the same facts.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    RunTimedOut,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.score import score_case
from music_store_agent.agent import build_agent, model_id
from music_store_agent.clock import pinned_day
from music_store_agent.constants import (
    PROVIDER_ERROR_MESSAGE,
    SAFE_PRICE_MESSAGE,
    TURN_ERROR_MESSAGE,
    TURN_TIMEOUT_SECONDS,
)
from music_store_agent.db import last_order_date, load_database
from music_store_agent.deps import Deps, make_deps
from music_store_agent.run import log_answering_model, provider_message
from music_store_agent.textutil import amounts_in_text

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

SCENARIO_PATH = Path(__file__).with_name("scenarios.yaml")
RESULTS_DIR = Path(__file__).with_name("results")
BACKOFF_SECONDS = (10, 30, 90)
EXIT_FAILED = 1
EXIT_NO_KEY = 2
EXIT_STOPPED = 3


class RunStopped(Exception):
    """The provider kept refusing, or a turn ran out of time. Cases done so far are reported."""

    def __init__(self, case_id: str, reason: str) -> None:
        super().__init__(f"{case_id}: {reason}")
        self.case_id = case_id
        self.reason = reason


@dataclass
class CaseRun:
    case_id: str
    passed: bool
    failures: list[str]
    latency_ms: list[float] = field(default_factory=list)
    requests: list[int] = field(default_factory=list)
    firings: int = 0
    catches: int = 0
    turns: int = 0


@dataclass
class Pass:
    cases: list[CaseRun]
    stopped: RunStopped | None = None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.stub and not os.environ.get("GOOGLE_API_KEY"):
        print("Set GOOGLE_API_KEY or pass --stub.")
        return EXIT_NO_KEY
    cases = _select(yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8")), args.start)
    runs: list[Pass] = []
    for _ in range(args.runs):
        runs.append(asyncio.run(_one_pass(cases, stub=args.stub, model=args.model)))
        if runs[-1].stopped:
            break
    report = _report(runs, args)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{_slug(args)}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(path)
    if runs[-1].stopped:
        return EXIT_STOPPED
    return EXIT_FAILED if any(not item.passed for run in runs for item in run.cases) else 0


def _slug(args: argparse.Namespace) -> str:
    """Stub output stays local. A live run is named after its model and is committed."""
    if args.stub:
        return "stub"
    return re.sub(r"[^a-z0-9.-]+", "-", model_id(args.model).casefold())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run store-assistant scenarios")
    parser.add_argument("--runs", type=int, default=3, help="passes over the scenario file")
    parser.add_argument("--model", default=None, help="google:<model id>; defaults to MODEL")
    parser.add_argument("--stub", action="store_true", help="scripted turns, no provider call")
    parser.add_argument("--from", dest="start", default=None, help="resume from this case id")
    return parser


def _select(cases: list[dict[str, Any]], start: str | None) -> list[dict[str, Any]]:
    if start is None:
        return cases
    ids = [case["id"] for case in cases]
    if start not in ids:
        raise SystemExit(f"Unknown case id {start!r}.")
    return cases[ids.index(start) :]


async def _one_pass(cases: list[dict[str, Any]], *, stub: bool, model: str | None) -> Pass:
    done: list[CaseRun] = []
    for case in cases:
        try:
            done.append(await _case(case, stub=stub, model=model))
        except RunStopped as stop:
            return Pass(done, stop)
    return Pass(done)


async def _case(case: dict[str, Any], *, stub: bool, model: str | None) -> CaseRun:
    with tempfile.TemporaryDirectory() as scratch:
        conn = load_database()
        deps = make_deps(
            conn,
            today=pinned_day(last_order_date(conn)),
            handoff_path=Path(scratch) / "handoffs.jsonl",
            usage_path=Path(scratch) / "turns.json",
        )
        agent = build_agent(_stub_model(case, deps) if stub else model)
        return await _play(case, agent, deps)


async def _play(case: dict[str, Any], agent: Any, deps: Deps) -> CaseRun:
    history: list[ModelMessage] = []
    transcript: list[dict[str, Any]] = []
    latency: list[float] = []
    requests: list[int] = []
    for turn in case["turns"]:
        started = time.perf_counter()
        firings = deps.counters.validator_firings
        result = await _attempt(agent, turn["prompt"], deps, history, case["id"])
        latency.append((time.perf_counter() - started) * 1000)
        if result is None:
            fired = deps.counters.validator_firings > firings
            reply = SAFE_PRICE_MESSAGE if fired else TURN_ERROR_MESSAGE
            transcript.append({"reply": reply, "calls": [], "returns": []})
            requests.append(0)
            continue
        history = list(result.all_messages())
        fresh = list(result.new_messages())
        log_answering_model(agent, fresh)
        calls, returns = _activity(fresh)
        transcript.append({"reply": result.output.message, "calls": calls, "returns": returns})
        requests.append(sum(isinstance(message, ModelResponse) for message in fresh))
    failures = score_case(case, transcript)
    counters = deps.counters
    return CaseRun(
        case["id"],
        not failures,
        failures,
        latency,
        requests,
        counters.validator_firings,
        counters.validator_catches,
        len(case["turns"]),
    )


async def _attempt(
    agent: Any, prompt: str, deps: Deps, history: list[ModelMessage], case_id: str
) -> Any:
    """One turn, backing off on a rate limit. None means the turn failed inside the agent."""
    for delay in (*BACKOFF_SECONDS, None):
        try:
            return await agent.run(
                prompt, deps=deps, message_history=history, timeout=TURN_TIMEOUT_SECONDS
            )
        except UnexpectedModelBehavior:
            return None
        except (FallbackExceptionGroup, RunTimedOut) as error:
            # Both models failed, or the turn ran past the budget a customer waits for.
            raise RunStopped(case_id, type(error).__name__) from error
        except ModelAPIError as error:
            if provider_message(error) == PROVIDER_ERROR_MESSAGE or delay is None:
                raise RunStopped(case_id, type(error).__name__) from error
            await asyncio.sleep(getattr(error, "retry_after", None) or delay)
    return None


def _stub_model(case: dict[str, Any], deps: Deps) -> FunctionModel:
    """Follow the turn's `stub` script. It never reads the `expect` block."""

    def respond(messages: list[ModelMessage], _info: object) -> ModelResponse:
        script = case["turns"][_prompt_index(messages)].get("stub", {})
        calls = script.get("calls", [])
        done = _tool_calls_since_prompt(messages)
        if done < len(calls):
            call = calls[done]
            return ModelResponse(parts=[ToolCallPart(call["tool"], call.get("args", {}))])
        reply = str(script.get("reply", ""))
        payload = {"message": reply, "quotes": _quotes(deps, reply)}
        return ModelResponse(parts=[ToolCallPart("final_result", payload)])

    return FunctionModel(respond)


def _quotes(deps: Deps, reply: str) -> list[dict[str, object]]:
    """Quote each amount the way the prompt asks. An amount no tool returned stays unquoted."""
    quotes: list[dict[str, object]] = []
    for amount in sorted(amounts_in_text(reply)):
        owners = [pid for pid, bucket in deps.ledger.by_product.items() if amount in bucket]
        owner = owners[0] if owners else None
        if owner is None and not deps.ledger.policy_has(amount):
            continue
        quotes.append({"product_id": owner, "amount": format(amount, "f")})
    return quotes


def _prompt_index(messages: list[ModelMessage]) -> int:
    count = sum(
        getattr(part, "part_kind", "") == "user-prompt"
        for message in messages
        for part in getattr(message, "parts", [])
    )
    return max(count - 1, 0)


def _tool_calls_since_prompt(messages: list[ModelMessage]) -> int:
    count = 0
    for message in reversed(messages):
        parts = list(getattr(message, "parts", []))
        if any(getattr(part, "part_kind", "") == "user-prompt" for part in parts):
            break
        count += sum(
            getattr(part, "part_kind", "") == "tool-call"
            and getattr(part, "tool_name", "") != "final_result"
            for part in parts
        )
    return count


def _activity(messages: list[ModelMessage]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            kind = getattr(part, "part_kind", "")
            name = getattr(part, "tool_name", "")
            if kind == "tool-call" and name != "final_result":
                calls.append({"tool": name, "args": part.args})
            if kind == "tool-return" and name != "final_result":
                returns.append({"tool": name, "content": str(part.content)})
    return calls, returns


def _report(runs: list[Pass], args: argparse.Namespace) -> str:
    flat = [item for run in runs for item in run.cases]
    by_id: dict[str, list[bool]] = {}
    for item in flat:
        by_id.setdefault(item.case_id, []).append(item.passed)
    flaky = [case_id for case_id, flags in by_id.items() if any(flags) and not all(flags)]
    latency = [value for item in flat for value in item.latency_ms]
    requests = [value for item in flat for value in item.requests]
    lines = [
        "# Eval results",
        "",
        f"Mode: {_mode(args)}. Runs: {len(runs)} of {args.runs}.",
        "",
        f"Pass rate: {sum(item.passed for item in flat)}/{len(flat)} case-runs.",
        f"Strict pass (every run): {sum(all(flags) for flags in by_id.values())}/{len(by_id)}.",
        f"Flaky: {', '.join(flaky) if flaky else 'none'}.",
        f"Median turn latency: {statistics.median(latency) if latency else 0:.1f} ms.",
        f"Median model requests per turn: {statistics.median(requests) if requests else 0:.1f}.",
        f"Validator fired {sum(item.firings for item in flat)} times in "
        f"{sum(item.turns for item in flat)} turns. True catches: "
        f"{sum(item.catches for item in flat)}.",
        "",
    ]
    stopped = runs[-1].stopped if runs else None
    if stopped is not None:
        lines += [f"Partial run. Stopped at {stopped}. Resume with --from {stopped.case_id}.", ""]
    for item in runs[-1].cases if runs else []:
        detail = "; ".join(item.failures)
        lines.append(f"- {item.case_id}: {'pass' if item.passed else 'fail'} {detail}".rstrip())
    lines.append("")
    return "\n".join(lines)


def _mode(args: argparse.Namespace) -> str:
    if args.stub:
        return "stub, scripted turns through the real tools and price check (not a model score)"
    return model_id(args.model)


if __name__ == "__main__":
    raise SystemExit(main())

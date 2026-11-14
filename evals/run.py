"""Run the scenario file. Without a key, pass --stub."""

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
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.score import score_case
from music_store_agent.agent import build_agent, model_id
from music_store_agent.clock import pinned_day
from music_store_agent.constants import SAFE_PRICE_MESSAGE
from music_store_agent.db import last_order_date, load_database
from music_store_agent.deps import Deps, make_deps
from music_store_agent.textutil import amounts_in_text

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

SCENARIO_PATH = Path(__file__).with_name("scenarios.yaml")
RESULTS_DIR = Path(__file__).with_name("results")


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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.stub and not os.environ.get("GOOGLE_API_KEY"):
        print("Set GOOGLE_API_KEY or pass --stub.")
        return 2
    cases = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8"))
    runs = [
        asyncio.run(_one_pass(cases, stub=args.stub, model=args.model))
        for _ in range(args.runs)
    ]
    report = _report(runs, args)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{_slug(args)}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(path)
    failed = any(not item.passed for group in runs for item in group)
    return 1 if failed else 0


def _slug(args: argparse.Namespace) -> str:
    """Stub output stays local. A live run is named after its model and is committed."""
    if args.stub:
        return "stub"
    return re.sub(r"[^a-z0-9.-]+", "-", model_id(args.model).casefold())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run store-assistant scenarios")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=None)
    parser.add_argument("--stub", action="store_true")
    return parser


async def _one_pass(cases: list[dict[str, Any]], *, stub: bool, model: str | None) -> list[CaseRun]:
    return [await _case(case, stub=stub, model=model) for case in cases]


async def _case(case: dict[str, Any], *, stub: bool, model: str | None) -> CaseRun:
    folder = Path(tempfile.mkdtemp())
    conn = load_database()
    deps = make_deps(
        conn,
        today=pinned_day(last_order_date(conn)),
        handoff_path=folder / "handoffs.jsonl",
        usage_path=folder / "turns.json",
    )
    agent = build_agent(_stub_model(case, deps) if stub else model)
    history: list[ModelMessage] = []
    transcript: list[dict[str, Any]] = []
    latency: list[float] = []
    requests: list[int] = []
    for turn in case["turns"]:
        started = time.perf_counter()
        try:
            result = await agent.run(turn["prompt"], deps=deps, message_history=history)
        except UnexpectedModelBehavior:
            transcript.append({"reply": SAFE_PRICE_MESSAGE, "calls": [], "returns": []})
            latency.append((time.perf_counter() - started) * 1000)
            requests.append(0)
            continue
        history = list(result.all_messages())
        fresh = list(result.new_messages())
        calls, returns = _activity(fresh)
        transcript.append({"reply": result.output.message, "calls": calls, "returns": returns})
        latency.append((time.perf_counter() - started) * 1000)
        requests.append(sum(isinstance(message, ModelResponse) for message in fresh))
    failures = score_case(case, transcript)
    return CaseRun(
        case["id"],
        not failures,
        failures,
        latency,
        requests,
        deps.counters.validator_firings,
        deps.counters.validator_catches,
        len(case["turns"]),
    )


def _stub_model(case: dict[str, Any], deps: Deps) -> FunctionModel:
    def respond(messages: list[ModelMessage], _info: object) -> ModelResponse:
        turn = case["turns"][_prompt_index(messages)]
        calls = turn.get("calls", [])
        done = _tool_calls_since_prompt(messages)
        if done < len(calls):
            call = calls[done]
            part = ToolCallPart(tool_name=call["tool"], args=call.get("args", {}))
            return ModelResponse(parts=[part])
        message, quotes = _grounded(deps, turn.get("reply_contains", []))
        payload = {"message": message, "quotes": quotes}
        return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=payload)])

    return FunctionModel(respond)


def _prompt_index(messages: list[ModelMessage]) -> int:
    count = 0
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", "") == "user-prompt":
                count += 1
    return max(count - 1, 0)


def _tool_calls_since_prompt(messages: list[ModelMessage]) -> int:
    count = 0
    for message in reversed(messages):
        parts = list(getattr(message, "parts", []))
        if any(getattr(part, "part_kind", "") == "user-prompt" for part in parts):
            break
        for part in parts:
            name = getattr(part, "tool_name", "")
            if getattr(part, "part_kind", "") == "tool-call" and name != "final_result":
                count += 1
    return count


def _grounded(deps: Deps, snippets: list[str]) -> tuple[str, list[dict[str, object]]]:
    message = " ".join(snippets).strip()
    if not message.endswith("?"):
        message = f"{message} Posso ajudar em mais alguma coisa?"
    quotes: list[dict[str, object]] = []
    for amount in sorted(amounts_in_text(message)):
        product_id = _product_for(deps, amount)
        if product_id is None and not deps.ledger.policy_has(amount):
            continue
        quotes.append({"product_id": product_id, "amount": format(amount, "f")})
    return message, quotes


def _product_for(deps: Deps, amount: object) -> int | None:
    for product_id, bucket in deps.ledger.by_product.items():
        if amount in bucket:
            return product_id
    return None


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


def _report(runs: list[list[CaseRun]], args: argparse.Namespace) -> str:
    flat = [item for group in runs for item in group]
    passed = sum(1 for item in flat if item.passed)
    by_id: dict[str, list[bool]] = {}
    for item in flat:
        by_id.setdefault(item.case_id, []).append(item.passed)
    flaky = [case_id for case_id, flags in by_id.items() if any(flags) and not all(flags)]
    strict = sum(1 for flags in by_id.values() if all(flags))
    latency = [value for item in flat for value in item.latency_ms]
    median = statistics.median(latency) if latency else 0
    requests = [value for item in flat for value in item.requests]
    request_median = statistics.median(requests) if requests else 0
    firings = sum(item.firings for item in flat)
    catches = sum(item.catches for item in flat)
    turns = sum(item.turns for item in flat)
    mode = "stub" if args.stub else (args.model or "default")
    lines = [
        "# Eval results",
        "",
        f"Mode: {mode}. Runs: {args.runs}.",
        "",
        f"Pass rate: {passed}/{len(flat)} case-runs.",
        f"Strict pass (every run): {strict}/{len(by_id)}.",
        f"Flaky: {', '.join(flaky) if flaky else 'none'}.",
        f"Median turn latency: {median:.1f} ms.",
        f"Median model requests per turn: {request_median:.1f}.",
        f"Validator fired {firings} times in {turns} turns. True catches: {catches}.",
        "",
    ]
    for item in runs[-1]:
        state = "pass" if item.passed else "fail"
        detail = "; ".join(item.failures) if item.failures else ""
        lines.append(f"- {item.case_id}: {state} {detail}".rstrip())
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

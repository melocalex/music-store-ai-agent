"""Fact checks for one scenario transcript. Stub and live runs use the same checks.

A turn's `expect` block says which tools must run with which key arguments, which facts
the tool text must hold or avoid, which amounts the reply must or must not carry, and a
few short keywords. Keywords are folded (case and accents), so a live reply can phrase
the answer its own way.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from evals.stamp import reference_day
from music_store_agent.constants import SAFE_PRICE_MESSAGE
from music_store_agent.hours import parse_asked_day
from music_store_agent.textutil import amounts_in_text, code_tokens, fold, parse_money_token


def score_case(case: dict[str, Any], transcript: list[dict[str, Any]]) -> list[str]:
    turns = case.get("turns", [])
    if len(transcript) != len(turns):
        return [f"expected {len(turns)} turns, got {len(transcript)}"]
    failures: list[str] = []
    for index, (spec, actual) in enumerate(zip(turns, transcript, strict=True), start=1):
        problems = _turn(spec.get("expect", {}), actual)
        failures.extend(f"turn {index} {problem}" for problem in problems)
    return failures


def _turn(expect: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    reply = str(actual.get("reply", ""))
    problems: list[str] = []
    if reply.startswith(SAFE_PRICE_MESSAGE) and not expect.get("fallback", False):
        problems.append("fell back to the price-check message")
    problems.extend(_tools(expect.get("tools", []), actual.get("calls", [])))
    problems.extend(_tool_text(expect.get("tool_text", {}), actual.get("returns", [])))
    problems.extend(_amounts(expect.get("amounts", {}), reply))
    problems.extend(_keywords(expect, reply))
    return problems


def _tools(expected: list[dict[str, Any]], calls: list[dict[str, Any]]) -> list[str]:
    problems = []
    for spec in expected:
        if not any(_call_matches(spec, call) for call in calls):
            seen = [f"{call.get('tool')} {_args(call.get('args'))}" for call in calls]
            problems.append(f"no {spec['tool']} call with {spec.get('args', {})}; saw {seen}")
    return problems


def _call_matches(spec: dict[str, Any], call: dict[str, Any]) -> bool:
    if call.get("tool") != spec["tool"]:
        return False
    actual = _args(call.get("args"))
    wanted = spec.get("args", {})
    return all(_value_matches(value, actual.get(key)) for key, value in wanted.items())


def _value_matches(expected: object, actual: object) -> bool:
    """Lenient on form, strict on meaning: amounts, dates, codes, and plain words."""
    if actual is None:
        return False
    if isinstance(expected, list):
        pool = actual if isinstance(actual, list) else [actual]
        return all(any(_value_matches(item, other) for other in pool) for item in expected)
    if isinstance(expected, bool | int) or isinstance(actual, bool | int):
        return str(expected).casefold() == str(actual).casefold()
    return _same_text(str(expected), str(actual))


def _same_text(expected: str, actual: str) -> bool:
    money = parse_money_token(expected), parse_money_token(actual)
    if None not in money:
        return money[0] == money[1]
    wanted_day = parse_asked_day(expected, reference_day())
    if wanted_day is not None:
        return parse_asked_day(actual, reference_day()) == wanted_day
    if fold(expected) in fold(actual):
        return True
    codes = code_tokens(expected)
    return bool(codes) and codes <= code_tokens(actual)


def _args(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def _tool_text(expect: dict[str, Any], returns: list[dict[str, Any]]) -> list[str]:
    blob = "\n".join(str(item.get("content", "")) for item in returns)
    problems = [
        f"tool text missing {needle!r}"
        for needle in expect.get("contains", [])
        if needle not in blob
    ]
    problems.extend(
        f"tool text has {needle!r}" for needle in expect.get("excludes", []) if needle in blob
    )
    return problems


def _amounts(expect: dict[str, Any], reply: str) -> list[str]:
    found = amounts_in_text(reply)
    problems = [
        f"reply lacks amount {value}"
        for value in expect.get("present", [])
        if Decimal(str(value)) not in found
    ]
    problems.extend(
        f"reply carries amount {value}"
        for value in expect.get("absent", [])
        if Decimal(str(value)) in found
    )
    return problems


def _keywords(expect: dict[str, Any], reply: str) -> list[str]:
    folded = fold(reply)
    problems = [
        f"reply lacks {word!r}" for word in expect.get("reply_all", []) if fold(word) not in folded
    ]
    options = expect.get("reply_any", [])
    if options and not any(fold(word) in folded for word in options):
        problems.append(f"reply has none of {options}")
    problems.extend(
        f"reply has {word!r}" for word in expect.get("reply_none", []) if fold(word) in folded
    )
    return problems

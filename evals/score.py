"""Pure checks for one scenario transcript."""

from __future__ import annotations

import json
from typing import Any


def score_case(case: dict[str, Any], transcript: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    turns = case.get("turns", [])
    if len(transcript) != len(turns):
        return [f"expected {len(turns)} turns, got {len(transcript)}"]
    for index, (spec, actual) in enumerate(zip(turns, transcript, strict=True), start=1):
        failures.extend(_turn(index, spec, actual))
    return failures


def _turn(index: int, spec: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    reply = str(actual.get("reply", ""))
    for needle in spec.get("reply_contains", []):
        if needle not in reply:
            failures.append(f"turn {index} reply missing {needle!r}")
    for needle in spec.get("reply_excludes", []):
        if needle in reply:
            failures.append(f"turn {index} reply has {needle!r}")
    calls = actual.get("calls", [])
    returns = actual.get("returns", [])
    expected = spec.get("calls", [])
    if len(calls) < len(expected):
        failures.append(f"turn {index} expected {len(expected)} tool calls, got {len(calls)}")
    for offset, spec_call in enumerate(expected):
        if offset >= len(calls):
            break
        failures.extend(_call(index, offset, spec_call, calls[offset], returns))
    return failures


def _call(
    index: int,
    offset: int,
    spec_call: dict[str, Any],
    actual: dict[str, Any],
    returns: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    if actual.get("tool") != spec_call["tool"]:
        failures.append(f"turn {index} tool {offset} is {actual.get('tool')}")
        return failures
    if not _args_match(spec_call.get("args", {}), actual.get("args")):
        failures.append(f"turn {index} tool {offset} args {actual.get('args')}")
    blob = "\n".join(str(item.get("content", "")) for item in returns)
    for needle in spec_call.get("contains", []):
        if needle not in blob:
            failures.append(f"turn {index} tool text missing {needle!r}")
    for needle in spec_call.get("excludes", []):
        if needle in blob:
            failures.append(f"turn {index} tool text has {needle!r}")
    return failures


def _args_match(expected: dict[str, Any], actual: object) -> bool:
    parsed = _parse_args(actual)
    return all(parsed.get(key) == value for key, value in expected.items())


def _parse_args(actual: object) -> dict[str, Any]:
    if isinstance(actual, dict):
        return actual
    if isinstance(actual, str):
        try:
            loaded = json.loads(actual)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
    return {}

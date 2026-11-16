"""The example writer renders a transcript header and stops on a provider error."""

import asyncio
from datetime import date

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.function import FunctionModel

from examples.generate import (
    EXIT_NO_KEY,
    SCRIPTS,
    GenerationStopped,
    _script,
    main,
    render_transcript,
)
from music_store_agent.agent import build_agent
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps

DAY = date(2026, 3, 23)


def test_render_transcript_keeps_the_header() -> None:
    text = render_transcript("sample", "stub", DAY, "abc", ["User: oi"])
    assert "Model: stub" in text
    assert f"Reference date: {DAY.isoformat()}" in text
    assert "Commit: abc" in text
    assert "User: oi" in text


def test_generate_needs_a_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main() == EXIT_NO_KEY


def _unavailable(_messages, _info):
    raise ModelHTTPError(503, "gemini")


def test_a_provider_error_stops_the_script(tmp_path) -> None:
    deps = make_deps(
        load_database(),
        today=DAY,
        handoff_path=tmp_path / "handoffs.jsonl",
    )
    agent = build_agent(FunctionModel(_unavailable))
    with pytest.raises(GenerationStopped):
        asyncio.run(_script(agent, deps, SCRIPTS[0], ("stub", DAY, "abc")))

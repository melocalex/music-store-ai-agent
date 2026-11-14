"""The example writer renders a transcript and refuses to invent one."""

from datetime import date

from examples.generate import main, render_transcript


def test_render_transcript_keeps_the_header() -> None:
    text = render_transcript("sample", "stub", date(2026, 3, 23), "abc", ["User: oi"])
    assert "Model: stub" in text
    assert "Commit: abc" in text
    assert "User: oi" in text


def test_generate_refuses_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main() == 2

"""The committed report is the renderer output."""

from music_store_agent.quality import REPORT_PATH, render


def test_report_matches_the_generator() -> None:
    assert REPORT_PATH.read_text(encoding="utf-8") == render()
    text = render()
    assert "customers 11 and 43" in text
    assert "bruno.martins" not in text
    assert "| unit |" in text or "| unit" in text
    for eval_id in ("stored-total", "coming-soon", "gd20-code", "black-friday", "late-order"):
        assert eval_id in text

"""The terminal chat explains a missing key or a bad setting in one line."""

from music_store_agent.cli import EXIT_BAD_SETTING, EXIT_NO_KEY, NO_KEY_MESSAGE, main
from music_store_agent.constants import MODEL_ENV


def test_no_key_prints_one_line_with_the_stub_hint(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main(["--once", "oi"]) == EXIT_NO_KEY
    err = capsys.readouterr().err
    assert err.strip() == NO_KEY_MESSAGE
    assert "--stub" in err
    assert "Traceback" not in err


def test_a_bad_model_id_prints_one_line(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder-not-a-key")
    monkeypatch.setenv(MODEL_ENV, "google-gla:gemini-3.5-flash")
    assert main(["--once", "oi"]) == EXIT_BAD_SETTING
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1
    assert MODEL_ENV in err


def test_the_stub_needs_no_key(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)  # the daily counter is written under ./var
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main(["--stub", "--once", "oi"]) == 0
    assert "Olá" in capsys.readouterr().out

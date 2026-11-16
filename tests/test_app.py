"""The hosted page keeps the question and always ends the turn with a reply."""

import os
import threading
import time
from datetime import date

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from streamlit.testing.v1 import AppTest

from music_store_agent import jobs
from music_store_agent.agent import build_agent
from music_store_agent.constants import PROVIDER_ERROR_MESSAGE, TURN_ERROR_MESSAGE
from music_store_agent.db import load_database
from music_store_agent.deps import make_deps

APP = os.path.join(os.path.dirname(__file__), os.pardir, "app.py")


def _reply(text: str) -> ModelResponse:
    call = ToolCallPart("final_result", {"message": text, "quotes": []})
    return ModelResponse(parts=[call])


def _page(tmp_path, respond) -> AppTest:
    os.environ["GOOGLE_API_KEY"] = "test-key-not-real"
    page = AppTest.from_file(APP, default_timeout=30).run()
    page.session_state["agent"] = build_agent(FunctionModel(respond))
    page.session_state["deps"] = make_deps(
        load_database(),
        today=date(2026, 3, 23),
        handoff_path=tmp_path / "handoffs.jsonl",
    )
    return page


def _texts(page: AppTest) -> list[str]:
    return [message.markdown[0].value for message in page.chat_message if message.markdown]


def _settle(page: AppTest) -> AppTest:
    """Rerun the page the way the fragment's poll does, until the pending turn is shown."""
    for _ in range(100):
        page.run()
        if page.session_state["job"] is None:
            return page
        time.sleep(0.05)
    raise AssertionError("the turn never ended")


def test_question_stays_visible_while_the_answer_is_pending(tmp_path) -> None:
    release = threading.Event()

    def respond(_messages, _info):
        release.wait(10)
        return _reply("Temos três violões.")

    page = _page(tmp_path, respond)
    page.chat_input[0].set_value("Quais violões vocês têm?").run()
    assert page.session_state["chat"][0] == {"role": "user", "text": "Quais violões vocês têm?"}
    for _ in range(3):  # a reconnect reruns the script while the model is still working
        page.run()
        assert "Quais violões vocês têm?" in _texts(page)
        assert page.session_state["job"] is not None
    release.set()
    _settle(page)
    assert _texts(page)[-1] == "Temos três violões."
    assert not page.exception


def test_a_model_crash_still_gets_a_reply(tmp_path) -> None:
    def respond(_messages, _info):
        raise RuntimeError("boom")

    page = _page(tmp_path, respond)
    page.chat_input[0].set_value("Quais violões vocês têm?").run()
    _settle(page)
    texts = _texts(page)
    assert texts[0] == "Quais violões vocês têm?"
    assert texts[-1] == TURN_ERROR_MESSAGE
    assert not page.exception


def test_a_worker_that_never_answers_ends_with_a_message(tmp_path, monkeypatch) -> None:
    release = threading.Event()

    def respond(_messages, _info):
        release.wait(10)
        return ModelResponse(parts=[TextPart("tarde demais")])

    monkeypatch.setattr(jobs, "JOB_DEADLINE_SECONDS", 0.2)
    page = _page(tmp_path, respond)
    page.chat_input[0].set_value("oi").run()
    time.sleep(0.4)
    _settle(page)
    release.set()
    assert _texts(page)[0] == "oi"
    assert _texts(page)[-1] == PROVIDER_ERROR_MESSAGE


def test_the_input_is_locked_while_a_turn_runs(tmp_path) -> None:
    release = threading.Event()

    def respond(_messages, _info):
        release.wait(10)
        return _reply("ok")

    page = _page(tmp_path, respond)
    page.chat_input[0].set_value("primeira").run()
    assert page.chat_input[0].disabled
    release.set()
    _settle(page)
    assert not page.chat_input[0].disabled


@pytest.fixture(autouse=True)
def _no_leftover_key():
    saved = os.environ.get("GOOGLE_API_KEY")
    yield
    if saved is None:
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        os.environ["GOOGLE_API_KEY"] = saved

"""The scorer can fail, the stub runner agrees with the file, and a stopped run can resume."""

import argparse
import asyncio
import copy
import time
from datetime import date
from pathlib import Path

import yaml
from pydantic_ai.exceptions import ModelHTTPError, ModelUnavailableError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import evals.run as run_module
import music_store_agent.run as app_run
from evals import stamp
from evals.run import _case, _one_pass, _report, main
from evals.score import score_case
from evals.stamp import reference_day
from music_store_agent.clock import pinned_day
from music_store_agent.db import last_order_date, load_database
from music_store_agent.failover import model_chain
from music_store_agent.quality import render

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evals" / "scenarios.yaml"


def _cases() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))


def _by_id(case_id: str) -> dict:
    return copy.deepcopy(next(case for case in _cases() if case["id"] == case_id))


def test_stub_runner_passes_every_case(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(run_module, "RESULTS_DIR", tmp_path)
    assert main(["--stub", "--runs", "1"]) == 0
    total = len(_cases())
    assert f"Pass rate: {total}/{total}" in capsys.readouterr().out
    assert (tmp_path / "stub.md").exists()


def test_a_stub_reply_with_another_products_price_fails() -> None:
    case = _by_id("c40-price")
    case["turns"][0]["stub"]["reply"] = "O Yamaha C40 custa R$ 849,00."
    result = asyncio.run(_case(case, stub=True, model=None))
    assert not result.passed
    assert any("fell back" in failure for failure in result.failures)
    assert result.firings >= 1


def test_a_wrong_tool_argument_fails() -> None:
    case = _by_id("c40-price")
    case["turns"][0]["stub"]["calls"] = [{"tool": "get_product", "args": {"query": "C70"}}]
    result = asyncio.run(_case(case, stub=True, model=None))
    assert not result.passed
    assert any("no get_product call" in failure for failure in result.failures)


def test_a_differently_worded_reply_passes_the_same_facts() -> None:
    case = _by_id("c40-price")
    transcript = [
        {
            "reply": "Claro! O violão Yamaha C40 está saindo por R$ 599,90 à vista no cartão.",
            "calls": [{"tool": "get_product", "args": {"query": "Yamaha C40"}}],
            "returns": [{"tool": "get_product", "content": "amount=599.90 amount=569.91"}],
        }
    ]
    assert score_case(case, transcript) == []
    transcript[0]["reply"] = "O C40 custa R$ 849,00."
    assert score_case(case, transcript)


def _unavailable(_messages, _info):
    raise ModelHTTPError(503, "gemini")


def test_a_provider_failure_stops_the_run_and_names_the_resume_point() -> None:
    cases = _cases()[:2]
    result = asyncio.run(_one_pass(cases, stub=False, model=FunctionModel(_unavailable)))
    assert result.stopped is not None
    assert result.stopped.case_id == cases[0]["id"]
    args = argparse.Namespace(stub=False, model=None, runs=1)
    report = _report([result], args)
    assert f"Resume with --from {cases[0]['id']}" in report


def _outage(_messages, _info):
    """A 503 the way the Gemini adapter raises it, with its category."""
    raise ModelHTTPError.for_category(ModelUnavailableError, status_code=503, model_name="gemini")


def test_both_models_down_stops_the_run_instead_of_crashing_it() -> None:
    cases = _cases()[:2]
    chain = model_chain(FunctionModel(_outage), FunctionModel(_outage))
    result = asyncio.run(_one_pass(cases, stub=False, model=chain))
    assert result.stopped is not None
    assert result.stopped.case_id == cases[0]["id"]


def test_a_turn_past_its_budget_stops_the_run_instead_of_hanging(monkeypatch) -> None:
    hang = 5.0

    async def stalls(_messages, _info):
        await asyncio.sleep(hang)
        raise AssertionError("the turn budget should have stopped this request")

    monkeypatch.setattr(app_run, "TURN_TIMEOUT_SECONDS", 0.2)
    cases = _cases()[:2]
    started = time.monotonic()
    result = asyncio.run(_one_pass(cases, stub=False, model=FunctionModel(stalls)))
    assert time.monotonic() - started < hang / 5
    assert result.stopped is not None
    assert result.stopped.case_id == cases[0]["id"]
    assert result.stopped.reason == "RunTimedOut"
    args = argparse.Namespace(stub=False, model=None, runs=1)
    assert f"Resume with --from {cases[0]['id']}" in _report([result], args)


def test_a_rate_limit_is_retried(monkeypatch) -> None:
    monkeypatch.setattr(run_module, "BACKOFF_SECONDS", (0,))
    calls = {"count": 0}

    def flaky(_messages, _info):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ModelHTTPError(429, "gemini", {"error": "RESOURCE_EXHAUSTED"})
        args = {"message": "Pergunta anotada.", "quotes": []}
        return ModelResponse(parts=[ToolCallPart("final_result", args)])

    case = {"id": "retry", "turns": [{"prompt": "oi", "expect": {}}]}
    result = asyncio.run(_case(case, stub=False, model=FunctionModel(flaky)))
    assert result.passed
    assert calls["count"] == 2


def test_case_ids_are_unique_and_the_report_points_at_them() -> None:
    ids = [case["id"] for case in _cases()]
    assert len(ids) == len(set(ids))
    for line in render().splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not line.startswith("|") or len(cells) < 3 or cells[-1] in {"Eval id", "---"}:
            continue
        assert cells[-1] == "unit" or cells[-1] in ids, cells[-1]


def test_the_reference_day_comes_from_the_data_and_the_report_is_stamped(monkeypatch) -> None:
    conn = load_database()
    assert reference_day() == pinned_day(last_order_date(conn))
    report = _report([], argparse.Namespace(stub=True, model=None, runs=1))
    assert f"Commit: {stamp.git_commit()}." in report
    assert f"Reference date: {reference_day().isoformat()}." in report
    assert "Written at: " in report
    monkeypatch.setattr(stamp, "last_order_date", lambda _conn: date(2027, 1, 10))
    stamp.reference_day.cache_clear()
    try:
        assert reference_day() == date(2027, 1, 11)
    finally:
        monkeypatch.undo()
        stamp.reference_day.cache_clear()
    assert reference_day() == pinned_day(last_order_date(conn))


def test_the_report_names_the_models_that_answered_and_the_tail_latency() -> None:
    fast = run_module.CaseRun(
        "a", True, [], [1000.0, 2000.0], [2, 2], 0, 0, 2, ["openrouter:x/y"] * 4
    )
    slow = run_module.CaseRun("b", True, [], [9000.0], [2], 0, 0, 1, ["openrouter:x/y", "google:g"])
    args = argparse.Namespace(stub=False, model=None, runs=1)
    report = _report([run_module.Pass([fast, slow])], args)
    assert (
        "Answered by: openrouter:x/y 5, google:g 1. Responses from a fallback model: 1 of 6."
        in report
    )
    assert "P50 2000 ms, P95 8300 ms, max 9000 ms." in report
    assert "Mode: live, chain " in report
    assert "google:gemini-3.8-flash." not in report.split("\n")[2]


def test_a_live_run_needs_one_of_the_two_keys(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["--runs", "1"]) == run_module.EXIT_NO_KEY
    assert "OPENROUTER_API_KEY" in capsys.readouterr().out


def test_the_live_report_file_is_named_after_the_first_model_of_the_chain(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder-not-a-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/some-model")
    args = argparse.Namespace(stub=False, model=None, runs=1)
    assert run_module._slug(args) == "openrouter-vendor-some-model"


def test_a_product_id_counts_as_the_same_product_as_its_code() -> None:
    case = _by_id("c40-installments")
    first = case["turns"][0]
    ran = {"tool": "quote_offer", "args": {"query": "81", "payment": "credit", "installments": 10}}
    text = "10x não é permitido. Máximo: 6x. amount=100.00 amount=99.98"
    reply = "Em 10x não dá. O máximo é 6x: R$ 100,00 e 99,98."
    transcript = [{"reply": reply, "calls": [ran], "returns": [{"tool": "x", "content": text}]}]
    assert score_case({"turns": [{"expect": first["expect"]}]}, transcript) == []
    other = {**ran, "args": {**ran["args"], "query": "82"}}
    transcript[0]["calls"] = [other]
    assert score_case({"turns": [{"expect": first["expect"]}]}, transcript)
    transcript[0]["calls"] = [{**ran, "args": {**ran["args"], "installments": 6}}]
    assert score_case({"turns": [{"expect": first["expect"]}]}, transcript)


def test_any_of_tools_needs_one_of_them_and_names_all_when_none_ran() -> None:
    expect = {"tools": [{"any_of": [{"tool": "consult_policy"}, {"tool": "search_catalog"}]}]}
    case = {"turns": [{"expect": expect}]}
    reply = {"reply": "Não temos.", "returns": []}
    assert score_case(case, [{**reply, "calls": [{"tool": "search_catalog", "args": {}}]}]) == []
    failures = score_case(case, [{**reply, "calls": [{"tool": "check_hours", "args": {}}]}])
    assert failures and "consult_policy" in failures[0] and "search_catalog" in failures[0]


def test_the_english_scenario_still_requires_an_english_reply() -> None:
    case = _by_id("english-c40")
    expect = case["turns"][0]["expect"]
    call = {"tool": "get_product", "args": {"query": "C40"}}
    returned = [{"tool": "get_product", "content": "amount=599.90"}]
    portuguese = "O Yamaha C40 custa R$ 599,90 e está disponível."
    english = "The Yamaha C40 is R$ 599,90 and in stock."
    for reply, passes in ((portuguese, False), (english, True)):
        transcript = [{"reply": reply, "calls": [call], "returns": returned}]
        assert (score_case({"turns": [{"expect": expect}]}, transcript) == []) is passes

"""The scorer can fail, the stub runner agrees with the file, and a stopped run can resume."""

import argparse
import asyncio
import copy
from pathlib import Path

import yaml
from pydantic_ai.exceptions import ModelHTTPError, ModelUnavailableError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import evals.run as run_module
from evals.run import _case, _one_pass, _report, main
from evals.score import score_case
from music_store_agent.agent import model_chain
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

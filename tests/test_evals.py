"""Scenario scoring stays deterministic, and the stub runner agrees with the file."""

from pathlib import Path

import yaml

import evals.run as run_module
from evals.run import main
from evals.score import score_case
from music_store_agent.quality import render

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evals" / "scenarios.yaml"


def test_score_rejects_a_missing_phrase() -> None:
    case = {"turns": [{"reply_contains": ["R$ 10,00"], "reply_excludes": ["@"], "calls": []}]}
    failures = score_case(case, [{"reply": "sem valor", "calls": [], "returns": []}])
    assert failures


def test_score_accepts_a_grounded_reply() -> None:
    case = {
        "turns": [
            {
                "reply_contains": ["R$ 599,90"],
                "reply_excludes": ["R$ 10,00"],
                "calls": [
                    {"tool": "get_product", "args": {"query": "C40"}, "contains": ["599.90"]}
                ],
            }
        ]
    }
    transcript = [
        {
            "reply": "R$ 599,90",
            "calls": [{"tool": "get_product", "args": {"query": "C40"}}],
            "returns": [{"tool": "get_product", "content": "amount=599.90"}],
        }
    ]
    assert score_case(case, transcript) == []


def test_stub_runner_passes(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(run_module, "RESULTS_DIR", tmp_path)
    assert main(["--stub", "--runs", "1"]) == 0
    assert (tmp_path / "stub.md").exists()
    captured = capsys.readouterr()
    assert "Pass rate: 25/25" in captured.out


def test_report_ids_exist_in_the_scenarios() -> None:
    cases = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    ids = {case["id"] for case in cases}
    assert len(ids) == 25
    for line in render().splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3 or cells[-1] in {"Eval id", "---"}:
            continue
        eval_id = cells[-1]
        assert eval_id == "unit" or eval_id in ids

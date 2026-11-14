"""The committed report is the renderer output, and its findings come from the data."""

import re

from music_store_agent.quality import REPORT_PATH, render

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}")


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith(("| Finding", "| ---")):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_report_matches_the_generator() -> None:
    assert REPORT_PATH.read_text(encoding="utf-8") == render()


def test_every_row_has_a_finding_a_decision_and_an_eval_id() -> None:
    rows = _rows(render())
    assert rows
    assert all(len(row) == 3 and all(row) for row in rows)


def test_campaign_bands_use_the_campaign_constants() -> None:
    text = render()
    band_row = next(line for line in text.splitlines() if "campaign band" in line)
    assert "1 Black Friday 10%" in band_row
    assert "7 Black Friday" not in band_row
    assert "17 Aniversário da Loja 30%" in band_row


def test_history_rows_are_computed() -> None:
    text = render()
    assert "plus the R$ 35,00 freight: none" in text
    assert "order 8 (shipped" in text
    assert "order 18 credit_12x parcel 38.32, below today's floor" in text
    assert "Customers sharing an email: 11 and 43" in text


def test_report_holds_no_contact_details() -> None:
    assert EMAIL.search(render()) is None

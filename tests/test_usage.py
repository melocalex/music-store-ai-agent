"""The daily counter stays exact when several sessions write at once."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from music_store_agent.constants import DAILY_TURN_CAP
from music_store_agent.usage import reserve

DAY = date(2026, 11, 14)


def test_parallel_reservations_never_pass_the_cap(tmp_path) -> None:
    path = tmp_path / "turns.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        attempts = range(DAILY_TURN_CAP + 20)
        granted = list(pool.map(lambda _: reserve(path, DAY, DAILY_TURN_CAP), attempts))
    assert sum(granted) == DAILY_TURN_CAP
    assert json.loads(path.read_text(encoding="utf-8"))["count"] == DAILY_TURN_CAP
    assert list(tmp_path.iterdir()) == [path]


def test_a_new_day_starts_from_zero(tmp_path) -> None:
    path = tmp_path / "turns.json"
    assert reserve(path, DAY, 1)
    assert not reserve(path, DAY, 1)
    assert reserve(path, date(2026, 11, 15), 1)

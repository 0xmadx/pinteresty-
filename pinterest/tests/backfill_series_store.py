"""Populate the series store from cache files already on disk.

Every related_/prefix_/metrics_ response ever cached carries series we paid for once and
then dropped. This replays them into the store so the saving starts from the existing
corpus rather than from the next crawl.

    .venv/Scripts/python.exe pinterest/tests/backfill_series_store.py
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.series_store import SeriesStore

CACHE = Path(__file__).resolve().parents[1] / "data" / "cache"


def run(end_date="2026-07-27", country="US"):
    store = SeriesStore()
    added = {"related": 0, "prefix": 0, "metrics": 0}

    for path in sorted(CACHE.glob("*.json")):
        name = path.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if name.startswith("related_"):
            added["related"] += store.harvest(data, "related", country, end_date)
        elif name.startswith("prefix_"):
            added["prefix"] += store.harvest(data, "prefix", country, end_date)
        elif name.startswith("metrics_"):
            # Only full-year responses are stored; a 13-point 90-day response cannot serve
            # anything wider and would block the exact series from landing later.
            if data and len(data[0].get("counts", [])) >= 53:
                added["metrics"] += store.harvest_metrics(data, country, end_date)

    print(f"backfilled: {added}")
    print(f"store: {store.stats()}")
    return store


if __name__ == "__main__":
    run()

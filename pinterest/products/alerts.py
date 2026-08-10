"""8. Momentum alerting — what changed since last week.

A single discovery table is a leaderboard; two of them are a monitoring product. This
module diffs consecutive weeks out of `history.db` and emits typed events, which is the
form a feed, a digest email or a webhook actually consumes.

Why the archive is the input rather than a live call: the interesting events are all
`entered` / `exited` / `climbed`, and none of them exist in a single response. Measured
across six consecutive US weeks, 426 distinct terms held only 600 table slots — a term
lasts about 1.4 weeks on the growing table. Almost everything IS an event, which is exactly
why you want it filtered rather than dumped.

Thresholds live in RULES so a caller can tighten them without editing logic. The defaults
are set to keep a week's output readable rather than exhaustive.

    .venv/Scripts/python.exe pinterest/products/alerts.py --refresh
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.products.history import HistoryDB, backfill

RULES = {
    "entered_top": 20,        # entering the top N is an event; entering at #48 is noise
    "climb": 15,              # rank improvement worth reporting
    "fall": 20,               # rank loss worth reporting
    "seasonality_cross": 0.82,  # the Seasonal preset's own measured floor
    # Spikes are graded against the week's own table, not a fixed number. A fixed 200%
    # threshold fired on 41 of 50 rows of the growing table — unsurprisingly, since growth
    # is that preset's selection criterion, which makes an absolute rule tautological
    # there and far too quiet on the volume-sorted presets. The quantile self-calibrates.
    "mom_quantile": 0.9,
    "mom_floor": 1.0,         # never call a <100% move a spike, whatever the table looks like
}

SEVERITY = {"entered": 3, "spike": 3, "climbed": 2, "seasonality_cross": 2,
            "fell": 1, "exited": 1}


def diff(previous, current, rules=None):
    """Two archived tables -> a list of events, most severe first.

    `previous`/`current` are rows as `HistoryDB.table()` returns them. Rank is 0-based and
    lower is better, so a negative delta is a climb.
    """
    rules = {**RULES, **(rules or {})}
    prev = {r["term"]: r for r in previous}
    curr = {r["term"]: r for r in current}
    events = []
    spike_at = _spike_threshold(current, rules)

    for term, row in curr.items():
        was = prev.get(term)
        if not was:
            if row["rank"] < rules["entered_top"]:
                events.append(_event("entered", row, detail=f"new at #{row['rank'] + 1}"))
        else:
            move = row["rank"] - was["rank"]
            if move <= -rules["climb"]:
                events.append(_event("climbed", row,
                                     detail=f"#{was['rank'] + 1} -> #{row['rank'] + 1}"))
            elif move >= rules["fall"]:
                events.append(_event("fell", row,
                                     detail=f"#{was['rank'] + 1} -> #{row['rank'] + 1}"))
            # A crossing, not a level: reporting "above 0.82" every week is not an alert.
            if (was["seasonality"] or 0) < rules["seasonality_cross"] <= (row["seasonality"] or 0):
                events.append(_event("seasonality_cross", row,
                                     detail=f"{was['seasonality'] or 0:.3f} -> "
                                            f"{row['seasonality']:.3f}"))
        if spike_at is not None and (row["mom"] or 0) >= spike_at:
            events.append(_event("spike", row, detail=f"MoM {row['mom']:+.0%}"))

    for term, row in prev.items():
        if term not in curr and row["rank"] < rules["entered_top"]:
            events.append(_event("exited", row, detail=f"was #{row['rank'] + 1}"))

    return sorted(events, key=lambda e: (-SEVERITY[e["kind"]], e["rank"]))


def _spike_threshold(rows, rules):
    """Where this week's spike bar sits: the requested quantile of the table's own MoM
    values, floored. None when the table has no usable MoM at all (the 10,000%+ sentinel is
    already clamped to NULL upstream, so a table of capped rows legitimately yields none).
    """
    moms = sorted(r["mom"] for r in rows if r["mom"] is not None)
    if not moms:
        return None
    idx = min(len(moms) - 1, int(rules["mom_quantile"] * len(moms)))
    return max(moms[idx], rules["mom_floor"])


def _event(kind, row, detail):
    return {"kind": kind, "term": row["term"], "week": row["week"], "preset": row["preset"],
            "rank": row["rank"], "seasonality": row["seasonality"], "mom": row["mom"],
            "severity": SEVERITY[kind], "detail": detail}


def latest_diff(db, country="US", preset="growing", rules=None):
    """Diff the two most recent archived weeks. Returns [] when only one week is stored —
    an empty feed, not an error: nothing has changed that we can prove."""
    weeks = db.weeks(country, preset)
    if len(weeks) < 2:
        return []
    return diff(db.table(weeks[-2], country, preset),
                db.table(weeks[-1], country, preset), rules)


def timeline(db, country="US", preset="growing", rules=None):
    """Every consecutive pair in the archive — the backtest of the alert rules.

    Worth running before wiring an alert to anything that notifies a human: it shows how
    many events a given threshold would have produced per week over real history.
    """
    weeks = db.weeks(country, preset)
    out = []
    for a, b in zip(weeks, weeks[1:]):
        out.append({"week": b,
                    "events": diff(db.table(a, country, preset),
                                   db.table(b, country, preset), rules)})
    return out


def watchlist(db, terms, country="US", preset="growing"):
    """Rank history for specific terms — the "tell me about these ten things" case, which
    is a different product from "tell me what moved"."""
    return {t: db.rank_history(t, country, preset) for t in terms}


def report(country="US", preset="growing", refresh=False, weeks=6):
    db = HistoryDB()
    if refresh:
        with PinterestTrendsAPI() as api:
            backfill(api, weeks, country, presets=(preset,), db=db)
        print()

    stored = db.weeks(country, preset)
    if len(stored) < 2:
        print(f"Only {len(stored)} week(s) archived — run with --refresh first.")
        return []

    print(f"=== {preset} / {country}: {stored[-2]} -> {stored[-1]} ===")
    events = latest_diff(db, country, preset)
    for e in events:
        print(f"  [{e['kind']:17}] {e['term'][:38]:40} {e['detail']}")
    print(f"\n  {len(events)} events from {len(stored)} archived weeks")

    print("\n=== backtest: events per week under the current rules ===")
    for step in timeline(db, country, preset):
        kinds = {}
        for e in step["events"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"  {step['week']}  {len(step['events']):>3} events  "
              f"{', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}")
    return events


if __name__ == "__main__":
    args = sys.argv[1:]
    report(preset=next((a for a in args if not a.startswith("-")), "growing"),
           refresh="--refresh" in args)

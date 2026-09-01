"""Time — the append-only readings, and whether past predictions came true.

Two things nothing could reach until now, and they are the same thing at two
scales: what a number DID, rather than what it is.

WHY THIS MATTERS MORE THAN A SNAPSHOT
-------------------------------------
Every `*_observations` table has `collected_at` in its primary key and is never
overwritten (Rule 5). That design exists precisely so these questions can be
asked — "supply grew 40% while volume held" is actionable in a way "supply is
381,511" is not — and until now the whole series was invisible to an agent, which
made the append-only discipline something the system paid for and nobody spent.

**Value here compounds only with time.** A daily delta is the difference between
two readings a day apart and cannot be backfilled; a day the scheduler did not
run is gone. So an empty history is "we have not been watching long enough", not
"nothing happened" — and every operation here says which.

THE LEARNING LOOP LIVES IN A DIFFERENT DATABASE
-----------------------------------------------
Launches, ranks and outcomes are in `GraphDB` (`etsy/data/graph/graph.db`), while
keyword and shop readings are in `MarketDatabase`. The existing `learn_status`
tool reads only the latter, so the actual prediction-vs-outcome join — the one
query the LEARN loop exists to answer — had no consumer at all.

⚠️ **`control_ratio` is the gate, not a statistic.** Below ~0.1 (B-04),
calibration is measuring the model against its own preferences: if every launch
was something the model liked, "the model was right" is circular. `None` means
nothing has launched, which is not the same claim as "no controls were run".
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import HistoryOp
from mcp_server._plumbing import _fail, _guarded, _ok, mcp

_NEEDS_SUBJECT = {"keyword", "trend", "shop", "listing", "rank"}

_OP_DOC = (
    "keyword: every demand reading for a term, oldest first. "
    "trend: Pinterest trend readings, matched across the Etsy/Pinterest wording gap. "
    "shop: a competitor's counter over time — the only MEASURED sales number here. "
    "listing/rank: one listing's readings and its rank curve. "
    "launches: what has been listed, with its prediction. "
    "outcomes: did those predictions come true — the LEARN join. "
    "calibration: prediction vs outcome, and whether it can be trusted yet. "
    "All local DB reads: free, offline, no session."
)


@mcp.tool()
@_guarded
def history(
    operation: Annotated[HistoryOp, Field(description=_OP_DOC)],
    subject: str | None = None,
    country: str = "US",
) -> dict:
    """Readings over time, and whether past predictions held. Free, offline, DB-only."""
    if operation in _NEEDS_SUBJECT and not subject:
        return _fail(f"operation '{operation}' needs `subject`",
                     fix="A keyword, shop name or listing id depending on the "
                         "operation.")

    from core.database import MarketDatabase
    db = MarketDatabase()

    if operation == "keyword":
        rows = db.get_keyword_history(subject) or []
        return _ok({
            "operation": operation, "term": subject,
            "readings": rows, "count": len(rows),
            "first": rows[0].get("collected_at") if rows else None,
            "last": rows[-1].get("collected_at") if rows else None,
            "basis": "measured" if rows else "unmeasured",
            "note": _series_note(len(rows), "demand readings"),
        })

    if operation == "trend":
        row = db.find_trend(subject, country=country)
        name = (row or {}).get("trend_name")
        rows = db.get_trend_history(name, country=country) if name else []
        return _ok({
            "operation": operation, "term": subject, "matched_trend": name,
            "readings": rows, "count": len(rows),
            "basis": "measured" if rows else "unmeasured",
            "note": "Matched across the wording gap — Pinterest writes editorial "
                    "phrases where Etsy has product keywords. A NEAR match is "
                    "refused rather than returned: importing 'cat collar' momentum "
                    "for 'dog collar' would be a wrong number wearing a right label."
                    if name else
                    "No Pinterest trend matches this term. Absent, not flat (N-02).",
        })

    if operation == "shop":
        rows = db.get_shop_history(subject) or []
        rate = db.latest_shop_rate(subject)
        latest = rows[-1] if rows else {}
        return _ok({
            "operation": operation, "shop": subject,
            "readings": rows, "count": len(rows),
            "sales_per_day": {"value": rate,
                              "basis": "measured" if rate is not None else "unmeasured"},
            "upper_bound": latest.get("sales_per_day_upper"),
            "counter_resolution": latest.get("counter_resolution"),
            "delta_available": len(rows) > 1,
            "basis": "measured" if len(rows) > 1 else "insufficient",
            "note": "⚠️ Etsy's counter is QUANTISED at scale — a shop showing "
                    "'25,100' steps by 100, so an unmoved counter means 'sold less "
                    "than the counter can show', never zero. A delta needs TWO "
                    "readings a day apart and cannot be backfilled.",
        })

    if operation == "listing":
        rows = db.get_listing_history(subject) or []
        return _ok({"operation": operation, "listing_id": subject,
                    "readings": rows, "count": len(rows),
                    "basis": "measured" if rows else "unmeasured",
                    "note": _series_note(len(rows), "listing readings")})

    from core.graph_db import GraphDB
    graph = GraphDB()

    if operation == "rank":
        rows = graph.get_rank_history(subject) or []
        return _ok({
            "operation": operation, "listing_id": subject,
            "observations": rows, "count": len(rows),
            "basis": "measured" if rows else "unmeasured",
            "note": "A NULL rank means checked-and-not-found; NO ROW means never "
                    "checked. Different facts, and only the first is evidence.",
        })

    if operation == "launches":
        rows = graph.get_launches() or []
        total = graph.launch_count()
        ratio = graph.control_ratio()
        return _ok({
            "operation": operation, "launches": rows, "count": total,
            "controls": graph.launch_count(controls_only=True),
            "control_ratio": {"value": ratio,
                              "basis": "measured" if ratio is not None else "unmeasured"},
            "basis": "measured" if total else "unmeasured",
            "note": _launch_note(total, ratio),
        })

    if operation == "outcomes":
        rows = graph.prediction_vs_outcome() or []
        return _ok({
            "operation": operation, "rows": rows, "count": len(rows),
            "basis": "measured" if rows else "unmeasured",
            "note": "`latest_rank: null` is ambiguous ALONE — read `observations` "
                    "beside it: 0 means never checked, >0 means checked and not "
                    "found. An untracked listing is not a failed one.",
        })

    if operation == "calibration":
        rows = graph.prediction_vs_outcome() or []
        total = graph.launch_count()
        ratio = graph.control_ratio()
        measured = [r for r in rows if r.get("observations")]
        blockers = []
        if total < 10:
            blockers.append(f"only {total} launches recorded; calibration needs ~10")
        if ratio is None:
            blockers.append("no launches, so the control ratio is unmeasured")
        elif ratio < 0.1:
            blockers.append(
                f"control ratio {ratio:.2f} is below the ~0.1 floor (B-04) — "
                f"calibrating on launches the model already liked measures the "
                f"model against its own preferences")
        return _ok({
            "operation": operation, "launches": total,
            "with_observations": len(measured),
            "control_ratio": ratio, "rows": rows,
            "can_calibrate": not blockers,
            "blockers": blockers,
            "basis": "measured" if measured else "unmeasured",
            "note": "This REFUSES rather than producing a confident model of noise. "
                    "Nothing here can be backfilled — the loop closes only when real "
                    "listings go up, including deliberately low-scored controls.",
        })

    return _fail(f"unknown operation: {operation}")


def _series_note(n, what):
    if n == 0:
        return f"No {what} stored. That is 'never measured', not zero (N-02)."
    if n == 1:
        return (f"One reading only — a delta needs two, a day apart, and cannot be "
                f"backfilled. Direction is unknown rather than flat.")
    return f"{n} {what}; deltas are readable across them."


def _launch_note(total, ratio):
    if not total:
        return ("NOTHING HAS LAUNCHED. This is the binding constraint on the whole "
                "system: every verdict it produces is currently unfalsifiable, and "
                "no amount of further measurement changes that. The loop closes "
                "only when a real listing goes up.")
    if ratio is not None and ratio < 0.1:
        return (f"Control ratio {ratio:.2f} is below B-04's ~0.1 floor. Without "
                f"deliberately low-scored controls, 'the model was right' is "
                f"circular — it only ever tried what it liked.")
    return f"{total} launches recorded, control ratio {ratio:.2f}."

"""When a verdict changes, which input moved?

A verdict today is a snapshot with no memory. The operator sees 🔴 and cannot
tell whether it has been 🔴 for a month, flipped this morning, or flips every
other day — and those call for three different actions. This records each verdict
with the inputs that produced it, so a flip can be explained rather than merely
noticed.

WHY THE INPUTS AND NOT JUST THE VERDICT
---------------------------------------
"It changed from 🟡 to 🔴" is not actionable. "It changed because supply grew 40%
while volume held" is. Storing only the outcome throws away the only part that
tells the operator what to do, and the inputs are already in hand at the moment
the verdict is computed — recovering them later means re-querying a market that
has since moved, which is not the same data.

WHAT IT REFUSES TO DO
---------------------
It does not attribute causally. `explain()` reports which inputs moved and by how
much, ranked by relative change; it never says one CAUSED the flip. Several
inputs usually move at once and this module has no way to isolate them — a
confident "supply caused this" would be a plausible wrong number about a
plausible wrong number.

An input that was measured before and is unmeasured now is reported as
`became_unmeasured`, never as a fall to zero (N-02). That distinction matters
most here: a scraper that broke overnight looks exactly like a market that
collapsed, and only this flag separates them.
"""
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "market_intelligence.db"

# Below this relative move an input is treated as noise rather than a change.
# Etsy's own counts drift ~0.1% between identical calls (filter_trust.COUNT_JITTER),
# so a threshold at zero would report every reading as a change.
MATERIAL_CHANGE = 0.02

BECAME_UNMEASURED = "became_unmeasured"
BECAME_MEASURED = "became_measured"


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verdict_observations (
                subject      TEXT NOT NULL,      -- keyword, listing id, whatever was judged
                collected_at TEXT NOT NULL,
                verdict      TEXT NOT NULL,      -- 'go' | 'no_go' | 'watch' | any label
                inputs_json  TEXT NOT NULL,      -- the numbers that produced it
                basis        TEXT,               -- provenance of the verdict as a whole
                note         TEXT,
                PRIMARY KEY (subject, collected_at)
            )
        """)
        conn.commit()


def record(subject, verdict, inputs, basis=None, note=None, collected_at=None,
           db_path=DB_PATH):
    """Append one verdict with the inputs behind it. Never overwrites (D-04)."""
    ensure_schema(db_path)
    now = collected_at or _utcnow()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO verdict_observations
                (subject, collected_at, verdict, inputs_json, basis, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (subject, now, verdict, json.dumps(inputs, default=str), basis, note))
        conn.commit()
    return {"subject": subject, "collected_at": now, "verdict": verdict}


def history(subject, db_path=DB_PATH, limit=None):
    """Every verdict for a subject, oldest first."""
    ensure_schema(db_path)
    sql = ("SELECT * FROM verdict_observations WHERE subject = ? "
           "ORDER BY collected_at ASC")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, (subject,))]
    for r in rows:
        r["inputs"] = json.loads(r.pop("inputs_json"))
    return rows[-limit:] if limit else rows


def diff_inputs(before, after, threshold=MATERIAL_CHANGE):
    """Which inputs moved between two readings, ranked by relative change.

    Returns [{key, before, after, change, relative, kind}]. `kind` is one of
    `moved`, `became_unmeasured`, `became_measured`, or `changed` for non-numeric
    values. Inputs that moved less than `threshold` are omitted as noise.
    """
    out = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue

        if old is not None and new is None:
            # A scraper that broke looks exactly like a market that collapsed.
            out.append({"key": key, "before": old, "after": None, "change": None,
                        "relative": None, "kind": BECAME_UNMEASURED})
            continue
        if old is None and new is not None:
            out.append({"key": key, "before": None, "after": new, "change": None,
                        "relative": None, "kind": BECAME_MEASURED})
            continue

        if isinstance(old, (int, float)) and isinstance(new, (int, float)) \
                and not isinstance(old, bool) and not isinstance(new, bool):
            change = new - old
            relative = (change / abs(old)) if old else None
            if relative is not None and abs(relative) < threshold:
                continue
            out.append({"key": key, "before": old, "after": new, "change": change,
                        "relative": relative, "kind": "moved"})
        else:
            out.append({"key": key, "before": old, "after": new, "change": None,
                        "relative": None, "kind": "changed"})

    # Biggest relative move first; unmeasured transitions rank above numeric moves
    # because a lost measurement is the more urgent thing to look at.
    def rank(item):
        if item["kind"] in (BECAME_UNMEASURED, BECAME_MEASURED):
            return (0, 0.0)
        return (1, -abs(item["relative"] or 0.0))
    return sorted(out, key=rank)


def explain(subject, db_path=DB_PATH, threshold=MATERIAL_CHANGE):
    """What happened to this subject's verdict, and what moved underneath it."""
    rows = history(subject, db_path)
    if not rows:
        return {"subject": subject, "readings": 0, "flipped": None,
                "note": "no verdict has ever been recorded for this subject"}
    if len(rows) == 1:
        return {"subject": subject, "readings": 1, "flipped": None,
                "current": rows[0]["verdict"],
                "note": "only one reading — a change needs two, and history "
                        "cannot be backfilled"}

    previous, current = rows[-2], rows[-1]
    changes = diff_inputs(previous["inputs"], current["inputs"], threshold)
    return {
        "subject": subject,
        "readings": len(rows),
        "from": previous["verdict"], "to": current["verdict"],
        "flipped": previous["verdict"] != current["verdict"],
        "since": previous["collected_at"], "at": current["collected_at"],
        "changes": changes,
        "verdict_sequence": [r["verdict"] for r in rows],
    }


def read(state):
    """Plain-language reading of explain()."""
    if not state.get("readings"):
        return [state.get("note", "nothing recorded")]
    if state["readings"] == 1:
        return [f"{state['subject']}: {state['current']} — {state['note']}"]

    out = []
    if state["flipped"]:
        out.append(f"{state['subject']} flipped {state['from']} -> {state['to']} "
                   f"between {state['since'][:16]} and {state['at'][:16]}.")
    else:
        out.append(f"{state['subject']} held at {state['to']} across "
                   f"{state['readings']} readings.")

    # A verdict that alternates is a different problem from one that moved once,
    # and the operator should not have to spot that by eye.
    seq = state["verdict_sequence"]
    flips = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    if flips >= 3:
        out.append(f"It has flipped {flips} times in {len(seq)} readings — this is "
                   f"oscillating, not trending. Treat any single reading as noise.")

    if not state["changes"]:
        out.append("No input moved more than the noise threshold. If the verdict "
                   "changed anyway, the rule changed, not the market.")
        return out

    for c in state["changes"][:5]:
        if c["kind"] == BECAME_UNMEASURED:
            out.append(f"  {c['key']}: was {c['before']}, now UNMEASURED. A broken "
                       f"scraper looks identical to a collapsed market — check the "
                       f"source before reading this as a decline.")
        elif c["kind"] == BECAME_MEASURED:
            out.append(f"  {c['key']}: newly measured at {c['after']} (was unknown, "
                       f"not zero).")
        elif c["kind"] == "moved":
            direction = "up" if c["change"] > 0 else "down"
            rel = f" ({c['relative']:+.0%})" if c["relative"] is not None else ""
            out.append(f"  {c['key']}: {c['before']} -> {c['after']}, {direction}{rel}")
        else:
            out.append(f"  {c['key']}: {c['before']} -> {c['after']}")

    out.append("These moved together; none of them is identified as the cause.")
    return out

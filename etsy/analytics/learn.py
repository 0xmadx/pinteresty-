"""Did the system's predictions come true? (M-3, D-12)

The loop is: predict -> launch -> measure -> compare. Everything upstream of this
module is prediction. This is the only place the system is allowed to be told it
was wrong, which makes it the most important module and the emptiest one.

WHAT IT REFUSES TO DO
---------------------
It does not tune anything. D-12 sets the floor at 10 launches before any
auto-tuning, and below that this reports and stops. Calibrating a scorer on three
launches produces a confident model of noise, which is worse than no model,
because it looks like evidence.

It does not score rank as if it were money. A listing can hold rank 3 and sell
nothing. Rank is reported next to sales, never as a substitute — when both are
present they can disagree, and the disagreement is the useful signal.

It does not fill in a missing outcome as zero. A launch with no outcome reading
is `unmeasured` and is excluded from every rate below, rather than counted as a
failure (N-02). Excluding it shrinks the sample honestly; counting it as zero
would manufacture a pessimism the data does not support.

    python -m etsy.analytics.learn
    python -m etsy.analytics.learn --record 1370681297 --sales 4 --revenue 71.60
"""
import argparse

from core.graph_db import GraphDB

# D-12. Below this, report only — no tuning, no "the model is working".
MIN_LAUNCHES_TO_CALIBRATE = 10
# A launch scoring above this was a system pick; below it, a control (B-04).
# Controls exist so the loop can be wrong in a visible way.
PICK_SCORE = 0.5


def _split(rows):
    """Separate launches that have been measured from those that have not."""
    measured = [r for r in rows if r.get("outcome_readings")]
    unmeasured = [r for r in rows if not r.get("outcome_readings")]
    return measured, unmeasured


def calibration(rows):
    """How well predicted score tracked actual sales. None until there is a basis.

    Returns None — not a zero, not a default — whenever the question cannot be
    answered: too few launches, no outcomes recorded, or no variation to correlate
    against. Each of those is a different reason, reported in `blocked_by`.
    """
    measured, unmeasured = _split(rows)
    scored = [r for r in measured
              if r.get("predicted_score") is not None and r.get("latest_sales") is not None]

    if len(rows) < MIN_LAUNCHES_TO_CALIBRATE:
        return {"ready": False, "blocked_by": "launches",
                "have": len(rows), "need": MIN_LAUNCHES_TO_CALIBRATE,
                "note": f"{len(rows)} launch(es) recorded; D-12 requires "
                        f"{MIN_LAUNCHES_TO_CALIBRATE} before any tuning."}
    if not scored:
        return {"ready": False, "blocked_by": "outcomes",
                "have": len(measured), "need": 1,
                "note": f"{len(unmeasured)} launch(es) have no outcome reading. "
                        f"Record one: python -m etsy.analytics.learn --record ID --sales N"}

    picks = [r for r in scored if r["predicted_score"] >= PICK_SCORE]
    controls = [r for r in scored if r["predicted_score"] < PICK_SCORE]
    if not controls:
        # Without controls the loop can only ever confirm its own picks (B-04).
        return {"ready": False, "blocked_by": "controls",
                "have": 0, "need": 1,
                "note": "every launch was a system pick. With no deliberately "
                        "low-scored control there is nothing to compare against, so "
                        "a high hit rate would prove only that we launched what we "
                        "liked."}

    def mean_sales(rs):
        return sum(r["latest_sales"] for r in rs) / len(rs) if rs else None

    return {"ready": True, "blocked_by": None,
            "launches_scored": len(scored),
            "picks": len(picks), "controls": len(controls),
            "mean_sales_picks": mean_sales(picks),
            "mean_sales_controls": mean_sales(controls),
            "separation": (mean_sales(picks) - mean_sales(controls))
                          if picks and controls else None}


def report(db=None):
    """The LEARN state as data. `read()` turns it into sentences."""
    db = db or GraphDB()
    rows = db.prediction_vs_outcome()
    measured, unmeasured = _split(rows)
    return {"launches": len(rows), "measured": len(measured),
            "unmeasured": len(unmeasured), "rows": rows,
            "calibration": calibration(rows)}


def read(state):
    """Plain-language LEARN status."""
    out = []
    n = state["launches"]
    if not n:
        out.append("No launches recorded. The LEARN loop cannot start until a real "
                   "listing is tied to the prediction that produced it: "
                   "python -m etsy.analytics.launch --seed TERM --listing-id ID")
        return out

    out.append(f"{n} launch(es) recorded, {state['measured']} with an outcome reading.")
    if state["unmeasured"]:
        out.append(f"{state['unmeasured']} launch(es) have never been measured. They "
                   f"are EXCLUDED from every rate below, not counted as failures.")

    cal = state["calibration"]
    if not cal.get("ready"):
        out.append(cal["note"])
    else:
        sep = cal["separation"]
        out.append(f"Picks averaged {cal['mean_sales_picks']:.1f} sales against "
                   f"{cal['mean_sales_controls']:.1f} for controls "
                   f"({cal['picks']} vs {cal['controls']} launches).")
        if sep is not None and sep <= 0:
            out.append("The controls did as well or better. On this evidence the "
                       "scorer is not picking winners — that is a finding, not a bug.")

    for r in state["rows"]:
        bits = [f"  {r['listing_id']} ({r['term_id']})"]
        bits.append(f"predicted {r['predicted_score']:.2f}"
                    if r.get("predicted_score") is not None else "predicted -")
        bits.append(f"rank {r['latest_rank']}" if r.get("latest_rank") is not None
                    else ("unranked" if r.get("observations") else "rank unchecked"))
        bits.append(f"{r['latest_sales']} sales" if r.get("latest_sales") is not None
                    else "sales unmeasured")
        if r.get("is_control"):
            bits.append("[control]")
        out.append(" | ".join(bits))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="learn")
    parser.add_argument("--record", metavar="LISTING_ID",
                        help="record an outcome reading for a launched listing")
    parser.add_argument("--sales", type=int)
    parser.add_argument("--revenue", type=float)
    parser.add_argument("--views", type=int)
    parser.add_argument("--favorites", type=int)
    parser.add_argument("--note")
    args = parser.parse_args(argv)

    db = GraphDB()
    if args.record:
        try:
            res = db.record_launch_outcome(args.record, sales=args.sales,
                                           revenue=args.revenue, views=args.views,
                                           favorites=args.favorites, note=args.note)
        except ValueError as e:
            print(f"[-] {e}")
            return 1
        print(f"[+] outcome recorded for {res['listing_id']} at {res['collected_at']}")

    for line in read(report(db)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

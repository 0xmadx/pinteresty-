"""The TIME loop: a date joined to demand. Offline, temp database.

This is the join the whole product is named for, and it was broken in a way no
unit test could have caught — `trends_bridge` computed all 13 moments, then wrote
a takeoff date only when a FEATURED TOPIC happened to share a moment's name.
Measured live: 86 topics, 13 moments, ZERO overlap. Every moment was discarded and
`takeoff_timestamp` was NULL in all 84 stored rows, so the calendar had nothing to
render and had never rendered.

The tests here therefore assert on the JOIN, not on the arithmetic (which
test_calendar already covers): that a dated moment survives storage, that demand is
attached to it, and that the failure modes report themselves rather than looking
like an empty calendar.

    .venv/Scripts/python.exe -m etsy.engines.test_calendar_engine
"""
import os
import tempfile
from datetime import datetime, timezone

from core.database import MarketDatabase
from etsy.analytics import calendar as cal
from etsy.engines import calendar_engine as ce

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def seed(path):
    db = MarketDatabase(db_path=path)
    db.record_trend(trend_name="christmas", source="pinterest_moments", country="US",
                    takeoff_timestamp="2026-10-28", peak_date="2026-12-09",
                    peak_length_days=28, phase="approaching", takeoff_basis="measured")
    db.record_trend(trend_name="halloween", source="pinterest_moments", country="US",
                    takeoff_timestamp="2026-08-04", peak_date="2026-10-20",
                    peak_length_days=28, phase="rising", takeoff_basis="measured")
    # A featured topic, which is NOT a moment and must never reach the calendar.
    db.record_trend(trend_name="Starbucks Drink Orders",
                    source="pinterest_featured_topics", country="US",
                    takeoff_basis="absent")
    db.record_keyword("christmas ornament", volume=25477, competition=1405731,
                      cvr=0.0003, cvr_source="measured",
                      price_low=7.2, price_high=8.8)
    db.record_keyword("christmas stocking", volume=40000, competition=50000,
                      cvr=0.001, cvr_source="measured",
                      price_low=32.0, price_high=41.0)
    return db


def main():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cal.db")
    seed(path)

    # --- moments survive storage, topics do not become moments ---------------------
    print()
    moments = ce.latest_moments(path)
    names = sorted(m["moment"] for m in moments)
    check("dated moments are read back", names == ["christmas", "halloween"], names)
    check("a featured topic is NOT mistaken for a moment",
          "Starbucks Drink Orders" not in names, names)
    check("takeoff converts to the shape launch_plan expects",
          all(isinstance(m["takeoff_ms"], int) for m in moments), moments)
    check("the peak survives — it is what separates late from missed",
          all(m["peak_ms"] for m in moments), moments)
    check("and the phase survives", moments[0]["phase"] in ("approaching", "rising"))

    # --- the join: a date with demand attached --------------------------------------
    print()
    # `profile=` is REQUIRED for a profit verdict now. Without it the calendar
    # withholds one, because profit.verdict defaults every cost to ZERO and would
    # answer "is this profitable for a product that costs nothing to make?" — always
    # yes. Measured: halloween badge reel read +85.5% go=True with no profile and
    # -9.1% go=False against the operator's real "Felt decor" costs.
    rows = ce.build(db_path=path, profile="Digital printable",
                    terms=["christmas ornament", "christmas stocking"],
                    lead_weeks=6, now=NOW)
    by_moment = {r["moment"]: r for r in rows}
    check("christmas is on the calendar", "christmas" in by_moment, list(by_moment))
    xmas = by_moment["christmas"]
    check("list_by is takeoff minus the lead time",
          xmas["list_by"] == "2026-09-16", xmas["list_by"])
    check("both matching terms are joined to it",
          len(xmas["evidence"]) == 2, xmas["evidence"])

    # --- ranked by winnability, NOT by volume (D-31) ---------------------------------
    print()
    lead_term = xmas["evidence"][0]["term"]
    check("the WINNABLE term leads, not the higher-volume one",
          lead_term == "christmas stocking", lead_term)
    ratios = [e["demand_per_listing"] for e in xmas["evidence"]]
    check("ordering is by demand-per-listing, descending",
          ratios == sorted(ratios, reverse=True), ratios)
    orn = next(e for e in xmas["evidence"] if e["term"] == "christmas ornament")
    check("a 25k-search term with 1.4M listings is called a WALL",
          orn["is_wall"] is True, orn)
    # A digital product genuinely has no COGS, so this profile clears at $7.20 —
    # but it clears because a REAL profile said so, not because nothing was costed.
    check("with a real profile the margin gate is answered, not assumed",
          orn["profitable"] is True and "Digital printable" in orn["profit_basis"], orn)
    check("so the moment is actionable via the winnable, profitable term",
          xmas["actionable"] is True)

    # The regression this pins: no profile must mean NO VERDICT, never a
    # flattering one. The old code returned profitable=True here.
    unpriced = ce.build(db_path=path, terms=["christmas ornament", "christmas stocking"],
                        lead_weeks=6, now=NOW)
    u_xmas = next(r for r in unpriced if r["moment"] == "christmas")
    u_orn = next(e for e in u_xmas["evidence"] if e["term"] == "christmas ornament")
    check("WITHOUT a profile the profit verdict is WITHHELD, not defaulted to go",
          u_orn["profitable"] is None, u_orn)
    check("and it says why, naming the cogs=0 trap",
          "cogs=0" in u_orn["profit_basis"], u_orn["profit_basis"])
    check("an unpriced moment is therefore NOT actionable",
          u_xmas["actionable"] is False, u_xmas["actionable"])
    check("but it is still RANKABLE — winnability is a separate question from money",
          u_xmas["rankable"] is True, u_xmas.get("rankable"))

    # --- unmeasured is not zero -------------------------------------------------------
    print()
    rows = ce.build(db_path=path, terms=["christmas ornament", "christmas garland"],
                    lead_weeks=6, now=NOW)
    xmas = next(r for r in rows if r["moment"] == "christmas")
    never = next(e for e in xmas["evidence"] if e["term"] == "christmas garland")
    check("a term never measured reports UNMEASURED, not zero demand",
          never["basis"] == "unmeasured", never)
    check("it carries no volume figure at all",
          "volume" not in never, never)
    # A wall term plus an unmeasured one is NOT an opportunity. The wall is measured
    # and unrankable; the other is simply unknown. Neither supports acting, and
    # summing them into "actionable" would be the optimistic reading of two
    # different kinds of no.
    check("a wall plus an unmeasured term is not actionable",
          xmas["actionable"] is False, xmas["actionable"])

    only_unmeasured = ce.build(db_path=path, terms=["christmas garland"],
                               lead_weeks=6, now=NOW)
    x2 = next(r for r in only_unmeasured if r["moment"] == "christmas")
    check("a moment backed ONLY by unmeasured terms is not actionable",
          x2["actionable"] is False, x2["actionable"])

    # --- a dated moment with nothing to sell is still shown ---------------------------
    print()
    rows = ce.build(db_path=path, terms=["felt garland"], lead_weeks=6, now=NOW)
    check("moments with no matching term still appear",
          {r["moment"] for r in rows} >= {"christmas"}, [r["moment"] for r in rows])
    check("hiding them would answer 'no opportunity' when the truth is 'nothing aimed at it'",
          next(r for r in rows if r["moment"] == "christmas")["evidence"] == [])

    # --- lead time is a read-time question, not a stored property ---------------------
    print()
    long_lead = ce.build(db_path=path, terms=[], lead_weeks=12, now=NOW)
    xmas12 = next(r for r in long_lead if r["moment"] == "christmas")
    check("a longer lead time moves the deadline earlier",
          xmas12["list_by"] == "2026-08-05", xmas12["list_by"])
    check("and can flip a moment from 'list by' to 'list now'",
          xmas12["state"] == cal.LIST_NOW, xmas12["state"])

    # --- an empty database is a clear answer, not a crash -----------------------------
    print()
    empty = os.path.join(tmp, "empty.db")
    MarketDatabase(db_path=empty)
    check("no moments yields an empty calendar, not an error",
          ce.build(db_path=empty, terms=["christmas ornament"], now=NOW) == [])

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())

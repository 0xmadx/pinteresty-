"""Pinterest -> Etsy handoff: writes trend aesthetics into market_intelligence.db.

This is the missing half of a contract that was specified but never implemented.
`_old_etsy_master_architecture.md:119` says:

    "Pinterest's Demographics, Dominant Colors, and Takeoff Timestamps are saved by the
     Pinterest Agent directly into the `trends` table in the Etsy market_intelligence.db"

The Etsy side of that contract already existed — `core/database.py` exposed `get_trend`
and no setter, and `master_arbitrage.py:242` has been reading it and receiving None since
the day it was written. The two halves of this repo are deliberately *not* coupled by
imports; they meet at this table. Nobody built the writer, so the table held 0 rows while
Pinterest held 954, and the three-source fusion the product is premised on never happened.

This module is that writer. It is the only place `pinterest/` touches
`market_intelligence.db`, which keeps the agent separation intact.

Provenance, because this feeds a decision system whose failure mode is a plausible wrong
number rather than an error:

    dominant_color      measured  — counted from real pin colours, quantised (moodboard.palette)
    demographic         measured  — Pinterest's own age/gender distributions
    takeoff_timestamp   measured  — Pinterest's takeoff_ms for the moment
    list_by             derived   — takeoff minus lead_weeks; OUR arithmetic, not Pinterest's
    velocity            derived   — local_math.velocity is our momentum measure, explicitly
                                    NOT a reconstruction of the API's growth_rates
    growth_mom          measured  — the API's own pct_growth_mom

Every write is an append. Re-running tomorrow adds a row and leaves today's intact, which
is what makes a backtest possible later (DECISION_LOG.md D-04).

Usage:
    python -m pinterest.pipelines.trends_bridge --country US
    python -m pinterest.pipelines.trends_bridge --dry-run
"""
import argparse
import sys
from datetime import datetime, timezone

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.local_math import launch_plan
from pinterest.products.moodboard import all_boards
from pinterest.products import audience
from core.database import MarketDatabase

# Matches the Etsy playbook's "list 6-8 weeks before the ramp"; 6 is the documented
# default (local_math.launch_plan) and the low end is the safe one for physical goods.
LEAD_WEEKS = 6


def _topic_rows(api, country):
    """Every featured topic across every interest, as (name, colour, growth, velocity)."""
    rows = []
    for interest, topics in (all_boards(api, country=country, with_editorial=True) or {}).items():
        for t in topics:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            palette = t.get("palette") or []
            top = palette[0] if palette else {}
            rows.append({
                "trend_name": name,
                "interest": interest,
                "dominant_color": top.get("hex"),
                "color_share": top.get("share"),
                "growth_mom": t.get("growth_mom"),
                "velocity": t.get("velocity"),
            })
    return rows


def _moment_index(api, country, lead_weeks=LEAD_WEEKS, now=None):
    """Moment name (lowercased) -> launch plan, so topics can be matched against timing.

    Moments and featured topics are different Pinterest surfaces with no shared id, so the
    join is by name. Exact-match only: a fuzzy match here would silently attach the wrong
    launch date to a trend, which is exactly the class of error this system exists to avoid.
    """
    out = {}
    for m in api.moments_calendar(country=country) or []:
        plan = launch_plan(m, lead_weeks=lead_weeks, now=now)
        if plan and plan.get("moment"):
            out[plan["moment"].strip().lower()] = plan
    return out


def _demographics(api, terms, country):
    """term (lowercased) -> compact demographic summary. Batched; one call per chunk."""
    out = {}
    for i in range(0, len(terms), 5):
        chunk = terms[i:i + 5]
        try:
            for row in audience.profile(api, chunk, country=country) or []:
                term = (row.get("term") or "").strip().lower()
                if term:
                    out[term] = {
                        "dominant_age": row.get("dominant_age"),
                        "mean_age": row.get("mean_age"),
                        "female_share": row.get("female_share"),
                        "male_share": row.get("male_share"),
                        "under_35": row.get("under_35"),
                        "over_55": row.get("over_55"),
                    }
        except Exception as exc:
            # One bad chunk must not cost the whole run, but it must be visible — a silent
            # skip here would look identical to "this trend has no demographic data".
            print(f"  [!] demographics failed for {chunk}: {exc}", file=sys.stderr)
    return out


def run(country="US", lead_weeks=LEAD_WEEKS, dry_run=False, now=None):
    """Collect one observation per trend and append it to market_intelligence.db."""
    collected_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    print(f"[BRIDGE] Pinterest -> market_intelligence.db  country={country}  at={collected_at}")

    api = PinterestTrendsAPI()
    try:
        topics = _topic_rows(api, country)
        print(f"  [+] {len(topics)} featured topics")

        moments = _moment_index(api, country, lead_weeks, now)
        print(f"  [+] {len(moments)} moments with a takeoff timestamp")

        demos = _demographics(api, [t["trend_name"] for t in topics], country)
        print(f"  [+] {len(demos)} demographic profiles")
    finally:
        api.close()

    db = None if dry_run else MarketDatabase()
    written = 0

    for t in topics:
        key = t["trend_name"].strip().lower()
        plan = moments.get(key)
        demo = demos.get(key)

        fields = dict(
            trend_name=t["trend_name"],
            source="pinterest_featured_topics",
            country=country,
            collected_at=collected_at,
            dominant_color=t["dominant_color"],
            color_share=t["color_share"],
            color_basis="measured" if t["dominant_color"] else "absent",
            demographic=demo,
            demographic_basis="measured" if demo else "absent",
            takeoff_timestamp=plan["takeoff"] if plan else None,
            list_by=plan["list_by"] if plan else None,
            # takeoff is Pinterest's; list_by is our subtraction from it. When there is no
            # matching moment we record "absent" rather than guessing a date.
            takeoff_basis="measured" if plan else "absent",
            growth_mom=t["growth_mom"],
            velocity=t["velocity"],
            velocity_basis="derived" if t["velocity"] is not None else "absent",
        )

        if dry_run:
            print(f"    {t['trend_name'][:38]:38}  {t['dominant_color'] or '-':8}"
                  f"  takeoff={fields['takeoff_timestamp'] or '-':10}"
                  f"  demo={'y' if demo else 'n'}")
        else:
            db.record_trend(**fields)
        written += 1

    # MOMENTS ARE WRITTEN IN THEIR OWN RIGHT, not merely as enrichment of a topic.
    #
    # The loop above only records a takeoff date when a FEATURED TOPIC happens to
    # share a moment's name. Measured live 2026-08-19: 86 topics, 13 moments, and
    # the overlap is ZERO — topics are things like "Senior Spirit Jeans and Pants"
    # while moments are "christmas", "halloween". So every moment was computed in
    # full and then discarded, and `takeoff_timestamp` was NULL in all 84 stored
    # rows.
    #
    # That is the entire basis of the calendar. `christmas` was sitting in that
    # discarded set with list_by 2026-09-16 and 3.9 weeks left — the exact row this
    # product exists to show.
    #
    # A moment is a different KIND of observation from a topic: it carries dates and
    # no colour or velocity, so it gets its own `source` rather than being forced
    # into the topic shape. Nothing here is derived to fill the gaps — a moment has
    # no dominant colour and that stays absent.
    for key, plan in sorted(moments.items()):
        fields = dict(
            trend_name=plan["moment"],
            source="pinterest_moments",
            country=country,
            collected_at=collected_at,
            takeoff_timestamp=plan.get("takeoff"),
            list_by=plan.get("list_by"),
            takeoff_basis="measured",
            # The peak decides LATE vs MISSED, which is the calendar's most
            # valuable call: a deadline that passed while the peak is still ahead
            # is a live chance, not a lost one. Storing takeoff alone discarded it.
            peak_date=plan.get("peak"),
            peak_length_days=plan.get("peak_length_days"),
            phase=plan.get("phase"),
            # A moment carries no colour, demographic or velocity. Absent, not zero.
            color_basis="absent",
            demographic_basis="absent",
            velocity_basis="absent",
        )
        if dry_run:
            print(f"    [moment] {plan['moment'][:24]:24} takeoff={plan.get('takeoff')}"
                  f"  list_by={plan.get('list_by')}  phase={plan.get('phase')}")
        else:
            db.record_trend(**fields)
        written += 1

    verb = "would write" if dry_run else "wrote"
    print(f"[BRIDGE] {verb} {written} trend observations at {collected_at} "
          f"({len(topics)} topics + {len(moments)} moments)")
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description="Append Pinterest trend data to the Etsy database.")
    p.add_argument("--country", default="US")
    p.add_argument("--lead-weeks", type=int, default=LEAD_WEEKS)
    p.add_argument("--dry-run", action="store_true", help="print rows, write nothing")
    args = p.parse_args(argv)
    run(country=args.country, lead_weeks=args.lead_weeks, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

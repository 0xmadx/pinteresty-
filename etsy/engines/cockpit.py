"""The Cockpit — one candidate, examined. Three sources, then a verdict.

    .venv/Scripts/python.exe -m etsy.engines.cockpit "christmas ornament"

The calendar says *what and when*. This is where the operator decides whether to
actually make it, and it is the screen the whole three-source design exists for.

THREE CARDS BEFORE ONE VERDICT (B-05)
-------------------------------------
Pinterest answers *when*, Etsy Private answers *how much demand*, Etsy Public
answers *how much competition*. Each gets its own reading and its own confidence
**before** anything combined appears, and when they disagree the combined line
says so rather than averaging the disagreement away.

That matters because the sources fail differently. Pinterest can be confident
about timing for a term nobody searches; Etsy Private can report healthy volume
for a term with two million listings. A single blended score hides exactly the
case the operator most needs to see.

READS THE DATABASE, NEVER THE NETWORK
-------------------------------------
No live calls. The UI contract is that a user action never waits on a provider,
and the deeper reason is that a decision screen should render the same numbers
twice in a row. Everything here was measured by the scheduler; if a reading is
old, that is shown rather than silently refreshed.

WHAT IT REFUSES
---------------
**A change measured against a degraded baseline is not a change.** `ceramic
planter pot` reads 4,776 → 589 searches, an 88% collapse — and the earlier
reading has `cvr_source=default` and no price, i.e. a reading that barely
succeeded. Comparing against it produces a dramatic number about our own
instrument. The comparison is refused and says why.

**Two readings minutes apart are not a trend.** A term swept five times in one
evening has five rows and no history. The baseline must be far enough back to
mean something (`MIN_TREND_DAYS`), or there is no trend to report.
"""
import argparse
import sqlite3

from etsy.analytics import calendar as cal
from etsy.analytics import profit

DB_PATH = "market_intelligence.db"

# Below this, a term cannot realistically be ranked into.
WALL_RATIO = 0.20
# Two readings closer together than this describe the same moment, not a trend.
MIN_TREND_DAYS = 1.0
# Relative move below this is noise — Etsy's own counts drift.
MATERIAL_CHANGE = 0.05


def _rows(db_path, keyword):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM keyword_observations WHERE keyword = ? "
            "ORDER BY collected_at ASC", (keyword,))]


def _days_between(a, b):
    from datetime import datetime
    try:
        return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()) / 86400
    except (ValueError, TypeError):
        return None


def _trend(rows):
    """Change since the most recent reading far enough back to count.

    Walks BACKWARDS from the latest for the first reading that is both old enough
    and not degraded. Returning None here is common and correct — most terms have
    one usable reading.
    """
    if len(rows) < 2:
        return {"basis": "unmeasured",
                "note": "one reading; a change needs two and cannot be backfilled"}

    latest = rows[-1]
    for prior in reversed(rows[:-1]):
        gap = _days_between(prior["collected_at"], latest["collected_at"])
        if gap is None or gap < MIN_TREND_DAYS:
            continue
        # A reading that fell back to the default CVR barely succeeded. Differencing
        # against it measures our instrument, not the market.
        if prior.get("cvr_source") == "default":
            return {"basis": "refused",
                    "days": round(gap, 1),
                    "note": (f"the only reading {round(gap, 1)} days back fell back to "
                             f"a default CVR — comparing against it would report a "
                             f"change in our own measurement as a change in the market")}
        old, new = prior.get("search_volume"), latest.get("search_volume")
        if not old or new is None:
            continue
        rel = (new - old) / old
        return {"basis": "measured", "days": round(gap, 1),
                "from": old, "to": new,
                "change": round(rel, 4),
                "material": abs(rel) >= MATERIAL_CHANGE}
    return {"basis": "unmeasured",
            "note": f"no earlier reading at least {MIN_TREND_DAYS:g} day(s) back — "
                    f"several readings on one evening are one reading"}


def _competition(db_path, keyword):
    """Page-one saturation shape, from the stored public-SERP reading.

    Returns only the dimensions whose interval is decisive — a share that cannot be
    placed against a threshold is measured but withheld, the same rule
    card_saturation applies. When the sample is thin (it usually is) and more
    ranked ids exist, that is surfaced as the concrete next step rather than a
    vague "low confidence".
    """
    from core.database import MarketDatabase
    row = MarketDatabase(db_path).latest_keyword_competition(keyword)
    if not row or not row.get("saturation"):
        return {"basis": "unmeasured",
                "note": "no page-one competition reading yet — the competition "
                        "sweep fills this"}

    decisive, withheld = [], 0
    for label, m in row["saturation"].items():
        dim, _, val = label.partition("|")
        if m.get("can_discriminate"):
            decisive.append({"dimension": dim, "value": val,
                             "share": m.get("share"),
                             "low": m.get("low"), "high": m.get("high")})
        elif m.get("sample"):
            withheld += 1

    upgrade = None
    ranked, sample = row.get("ranked_ids_count") or 0, row.get("organic_sample") or 0
    if withheld and ranked > sample + 4:
        upgrade = (f"{withheld} dimension(s) could not be called from {sample} "
                   f"listings; {ranked} ranked listings are available. A deeper "
                   f"sample would likely decide them.")

    return {"basis": "measured", "measured_at": row.get("collected_at"),
            "organic_sample": sample, "ranked_ids": ranked,
            "decisive": decisive, "withheld": withheld, "upgrade": upgrade}


def _timing(db_path, keyword, lead_weeks, now):
    """Pinterest's answer: is this term attached to a dated moment?"""
    from etsy.engines.calendar_engine import latest_moments
    moments = latest_moments(db_path)
    rows = cal.build(moments, terms=[keyword], lead_weeks=lead_weeks, now=now)
    for row in rows:
        if keyword in (row.get("terms") or []):
            return {"basis": "measured", "moment": row["moment"],
                    "state": row["state"], "list_by": row["list_by"],
                    "peak": row.get("peak"), "is_late": row.get("is_late"),
                    "reason": row["reason"]}
    return {"basis": "unmeasured",
            "note": "no dated Pinterest moment contains this term — untimed, which "
                    "is not the same as badly timed"}


def build(keyword, db_path=DB_PATH, product_type=profit.PERSONALIZED,
          lead_weeks=6, now=None):
    """Everything known about one candidate, with the three sources kept apart."""
    rows = _rows(db_path, keyword)
    latest = rows[-1] if rows else None

    timing = _timing(db_path, keyword, lead_weeks, now)

    if not latest:
        demand = {"basis": "unmeasured",
                  "note": "never measured. Add it and sweep: "
                          f'settings_store term add "{keyword}"'}
        supply = dict(demand)
        verdict = None
    else:
        volume = latest.get("search_volume")
        supply_n = latest.get("competition")
        cvr = latest.get("query_cvr")
        price = latest.get("median_price_low")
        ratio = (volume / supply_n) if (volume and supply_n) else None

        demand = {"basis": "measured", "measured_at": latest["collected_at"],
                  "volume": volume, "cvr": cvr,
                  "cvr_basis": latest.get("cvr_source"),
                  "price_low": price, "price_high": latest.get("median_price_high"),
                  "readings": len(rows), "trend": _trend(rows)}
        supply = {"basis": "measured", "measured_at": latest["collected_at"],
                  "listings": supply_n,
                  "demand_per_listing": round(ratio, 4) if ratio else None,
                  "is_wall": (ratio is not None and ratio < WALL_RATIO),
                  "competition": _competition(db_path, keyword)}
        verdict = profit.verdict(price=price, product_type=product_type) if price else None

    return {"keyword": keyword, "product_type": product_type,
            "timing": timing, "demand": demand, "supply": supply,
            "profit": verdict,
            "combined": _combine(timing, demand, supply, verdict)}


def _combine(timing, demand, supply, verdict):
    """The one verdict — and, more importantly, where the sources disagree.

    Disagreement is the output, not a problem to resolve. A term Pinterest times
    perfectly and Etsy says is unrankable is not a middling opportunity; it is two
    clear and opposite readings, and averaging them produces a number describing
    neither.
    """
    conflicts, blockers = [], []

    timed = timing.get("basis") == "measured"
    wall = supply.get("is_wall")
    measured = demand.get("basis") == "measured"

    if timed and wall:
        conflicts.append(
            f"Pinterest times this well (list by {timing['list_by']}) "
            f"but Etsy says you cannot rank here "
            f"({supply['demand_per_listing']:.3f} demand per listing). Two clear "
            f"readings pointing opposite ways — the timing is real and unreachable.")
    if timed and not measured:
        conflicts.append("Pinterest has a date for this and Etsy has never measured "
                         "it. The timing is not evidence of demand.")

    if wall:
        blockers.append("supply overwhelms demand — you cannot rank")
    if verdict and not verdict["go"]:
        blockers.append("; ".join(verdict["reasons"][:2]))
    if measured and demand.get("cvr_basis") == "default":
        blockers.append("CVR is a DEFAULT, not measured — the conversion side is a guess")
    if not measured:
        blockers.append("no demand measurement at all")

    if blockers:
        call = "no"
    elif not timed:
        call = "yes, but untimed"
    else:
        call = "yes"

    return {"call": call, "blockers": blockers, "conflicts": conflicts,
            "basis": "provisional — fees and costs are defaults until settings are "
                     "confirmed"}


def read(state):
    """Plain-language cockpit. Sources first, verdict last — deliberately."""
    out = [f"CANDIDATE: {state['keyword']}  ({state['product_type']})", ""]

    t = state["timing"]
    out.append("  PINTEREST — when")
    if t["basis"] == "measured":
        late = " (LATE)" if t.get("is_late") else ""
        out.append(f"    {t['moment']}{late} · list by {t['list_by']} · "
                   f"peak {t.get('peak') or '—'}")
        out.append(f"    {t['reason']}")
    else:
        out.append(f"    {t['note']}")

    d = state["demand"]
    out.append("")
    out.append("  ETSY PRIVATE — demand")
    if d["basis"] == "measured":
        cvr_note = "measured" if d["cvr_basis"] == "measured" else "DEFAULT — a guess"
        out.append(f"    {d['volume']:,} searches/mo · CVR {d['cvr']:.5f} ({cvr_note})")
        band = (f"${d['price_low']}–{d['price_high']}" if d["price_low"] else "no price returned")
        out.append(f"    median band {band} · {d['readings']} reading(s)")
        tr = d["trend"]
        if tr["basis"] == "measured":
            arrow = "up" if tr["change"] > 0 else "down"
            note = "" if tr["material"] else "  (within noise)"
            out.append(f"    volume {arrow} {abs(tr['change']):.0%} over {tr['days']} "
                       f"days ({tr['from']:,} → {tr['to']:,}){note}")
        else:
            out.append(f"    trend: {tr['note']}")
    else:
        out.append(f"    {d['note']}")

    s = state["supply"]
    out.append("")
    out.append("  ETSY PUBLIC — competition")
    if s["basis"] == "measured":
        wall = "  <- WALL, you cannot rank here" if s["is_wall"] else ""
        out.append(f"    {s['listings']:,} listings · "
                   f"{s['demand_per_listing']:.3f} demand per listing{wall}")
        comp = s.get("competition") or {}
        for d in comp.get("decisive", []):
            out.append(f"      {d['dimension']}={d['value']}: {d['share']:.0%} of "
                       f"page one ({d['low']:.0%}–{d['high']:.0%})")
        if comp.get("upgrade"):
            out.append(f"      note: {comp['upgrade']}")
    else:
        out.append(f"    {s['note']}")

    c = state["combined"]
    out.append("")
    for conflict in c["conflicts"]:
        out.append(f"  ! SOURCES DISAGREE: {conflict}")
    if c["conflicts"]:
        out.append("")
    out.append(f"  VERDICT: {c['call'].upper()}")
    for b in c["blockers"]:
        out.append(f"    - {b}")
    out.append(f"    ({c['basis']})")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cockpit")
    parser.add_argument("keyword")
    parser.add_argument("--type", default=profit.PERSONALIZED,
                        choices=list(profit.PRODUCT_TYPES))
    parser.add_argument("--lead-weeks", type=int, default=6)
    args = parser.parse_args(argv)

    print()
    for line in read(build(args.keyword, product_type=args.type,
                           lead_weeks=args.lead_weeks)):
        print(line)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

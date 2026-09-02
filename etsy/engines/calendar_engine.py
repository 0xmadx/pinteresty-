"""The calendar — the front door, and the thing this product is named for.

    .venv/Scripts/python.exe -m etsy.engines.calendar_engine

A date on its own is not a decision. "Christmas: list by 16 September" is a fact
about Pinterest; whether the operator should act on it depends on demand, supply
and whether the money works — all of which this system already measures separately
and has never joined to a date.

So this engine joins the three:

    Pinterest moment  ->  takeoff date  ->  list_by = takeoff - lead_weeks
    watched terms     ->  which of them belong to that moment
    keyword history   ->  volume, supply, demand-per-listing, price band
    profit gate       ->  does the money work at the measured price

and reports 🔴 list now / 🟡 list by / ⚪ watching, with the evidence attached.

WHAT IT REFUSES TO DO
---------------------
**It never invents a date.** A moment with no takeoff timestamp is dropped by
`calendar.build`, not defaulted to "soon".

**It never invents demand.** A term with no keyword observation is reported
`unmeasured`, never zero — the difference between "nobody wants this" and "we have
not looked" is the difference between skipping a good niche and chasing a dead one.

**A dated moment with no matching term is still shown**, marked as having nothing
to sell into it. Hiding it would quietly answer "is there an opportunity here?"
with "no", when the honest answer is "we have not pointed anything at it".

**It does not rank by search volume.** Demand-per-listing decides which term inside
a moment leads, because a term with 2M listings is a wall however large its volume
(D-31).

WHY THE DATES COME FROM THE DATABASE
------------------------------------
Not from a live Pinterest call. The calendar must render when Pinterest is
unreachable, and the takeoff dates move slowly — they are a weekly reading, not a
per-request one. `trends_bridge` writes them; this reads the latest.
"""
import argparse
import sqlite3
from datetime import datetime, timezone

from etsy.analytics import calendar as cal
from etsy.analytics import profit

DB_PATH = "market_intelligence.db"

# Below this, a term cannot realistically be ranked into: supply overwhelms demand.
# Exposed as a ratio and never folded into a score, so "you cannot rank here" stays
# checkable (D-31).
WALL_RATIO = 0.20


def _to_ms(iso_date):
    """ISO date -> epoch milliseconds, or None."""
    if not iso_date:
        return None
    try:
        return int(datetime.fromisoformat(iso_date)
                   .replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def latest_moments(db_path=DB_PATH, country="US"):
    """The most recent reading of every dated Pinterest moment.

    Converted back to the epoch-millisecond shape `local_math.launch_plan` expects,
    rather than reimplementing its arithmetic here. The dates would round-trip
    either way, but two copies of "list_by = takeoff - lead_weeks" would eventually
    disagree, and the one the operator reads would not be the one the tests cover.

    `list_by` is deliberately NOT read from the database even though it is stored
    there: it depends on the operator's lead time, which is a question asked at read
    time (`--lead-weeks`), not a property of the moment.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT trend_name, takeoff_timestamp, peak_date, peak_length_days, phase,
                   MAX(collected_at) AS collected_at
              FROM trend_observations
             WHERE source = 'pinterest_moments'
               AND country = ?
               AND takeoff_timestamp IS NOT NULL
             GROUP BY trend_name
        """, (country,)).fetchall()

    return [{"moment": r["trend_name"],
             "phase": r["phase"],
             "takeoff_ms": _to_ms(r["takeoff_timestamp"]),
             "peak_ms": _to_ms(r["peak_date"]),
             "peak_length_days": r["peak_length_days"]}
            for r in rows]


def latest_keyword(term, db_path=DB_PATH):
    """The most recent measurement of one term, or None if never measured."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT * FROM keyword_observations WHERE keyword = ?
             ORDER BY collected_at DESC LIMIT 1
        """, (term,)).fetchone()
    return dict(row) if row else None


def term_evidence(term, product_type=profit.PERSONALIZED, db_path=DB_PATH,
                  profile=None):
    """What is known about one term, with the basis of every number attached.

    ⚠️ `profile` is the operator's NAMED cost profile, and without one this
    function was answering a question nobody asked. `profit.verdict(price=...,
    product_type=...)` defaults every cost to ZERO, so it was asking *"is this
    price profitable for a product that costs nothing to make?"* — to which the
    answer is always yes.

    Measured 2026-09-01 on `halloween badge reel` at its $9.00 band price:

        no profile (cogs=0)   margin +85.5%   go=True    <- what the calendar showed
        "Felt decor"          margin  -9.1%   go=False
        "Custom sign"         margin -256%    go=False

    The profiles have existed in `config/settings.json` since 2026-08-15 and
    `settings_store.verdict_kwargs()` was written to feed exactly this call. The
    calendar simply never called it, and `settings_store.add_profile` REFUSES a
    personalized profile with zero labour_minutes (`:173`) — so the guard against
    this existed at the write end while the read end walked past it.

    With no profile the verdict is now withheld entirely rather than defaulted:
    `profitable` is None and `profit_basis` says why. An unanswerable question gets
    no answer (N-02) — it does not get an optimistic one.
    """
    obs = latest_keyword(term, db_path)
    if not obs:
        return {"term": term, "basis": "unmeasured",
                "note": "never measured — run the keyword sweep before trusting "
                        "any judgement about this term"}

    volume = obs.get("search_volume")
    supply = obs.get("competition")
    ratio = (volume / supply) if (volume and supply) else None
    price = obs.get("median_price_low")

    # D-46: prefer what the listings that ACTUALLY RANK charge. The band's low end
    # includes every dead listing that never surfaces, so pricing a margin floor
    # against it understates by a lot — measured on `halloween badge reel`, $9.00
    # band-low gives -9.1% against the operator's real costs while the $14.12
    # page-one median gives +17.5%. Same term, opposite side of break-even.
    page_one = obs.get("page_one_median_price")
    page_one_n = obs.get("page_one_n")
    price_used, price_used_basis = price, "band low (market-wide, conservative)"
    if page_one:
        price_used = page_one
        price_used_basis = f"page-one median of {page_one_n or '?'} ranking listings (D-46)"

    verdict, profit_basis = None, "no measured price"
    price = price_used
    if price and profile:
        # The LOW end of the band: clearing there clears across it. Using the high
        # end would flatter every candidate.
        from core.settings_store import load
        try:
            verdict = profit.verdict(price=price, **load().verdict_kwargs(profile))
            profit_basis = f"derived from the '{profile}' cost profile"
        except (KeyError, ValueError) as e:
            profit_basis = f"profile '{profile}' unusable: {e}"
    elif price:
        profit_basis = ("NOT JUDGED — no cost profile given, and a verdict with "
                        "cogs=0 would say every price is profitable. Pass "
                        "profile=<name> from config/settings.json product_profiles.")

    return {
        "term": term, "basis": "measured",
        "measured_at": obs.get("collected_at"),
        "volume": volume, "supply": supply,
        "demand_per_listing": round(ratio, 4) if ratio else None,
        "is_wall": (ratio is not None and ratio < WALL_RATIO),
        "cvr": obs.get("query_cvr"), "cvr_basis": obs.get("cvr_source"),
        "price_low": obs.get("median_price_low"),
        "price_high": obs.get("median_price_high"),
        "price_used": price_used, "price_used_basis": price_used_basis,
        "page_one_median_price": page_one, "page_one_n": page_one_n,
        "profitable": verdict["go"] if verdict else None,
        "margin": verdict["margin"] if verdict else None,
        "profit_basis": profit_basis,
    }


def build(db_path=DB_PATH, country="US", lead_weeks=6, terms=None,
          product_type=profit.PERSONALIZED, now=None, include_passed=False,
          profile=None):
    """The calendar, with Etsy evidence attached to every term on it."""
    from core.settings_store import load

    terms = terms if terms is not None else load().terms()
    moments = latest_moments(db_path, country)
    rows = cal.build(moments, terms=terms, lead_weeks=lead_weeks, now=now,
                     include_passed=include_passed)

    for row in rows:
        evidence = [term_evidence(t, product_type, db_path, profile=profile)
                    for t in row.get("terms", [])]
        # Best first, by demand-per-listing — NOT by volume. Unmeasured terms sort
        # last because they cannot be compared, not because they are worst.
        evidence.sort(key=lambda e: -(e.get("demand_per_listing") or -1))
        row["evidence"] = evidence
        # `actionable` now requires the money to work too. Without a profile the
        # profit verdict is None, so a row can be RANKABLE but not actionable — and
        # the reason is on the row rather than implied by its absence.
        row["actionable"] = any(e.get("basis") == "measured" and not e.get("is_wall")
                                and e.get("profitable") is True
                                for e in evidence)
        row["rankable"] = any(e.get("basis") == "measured" and not e.get("is_wall")
                              for e in evidence)
    return rows


def render(rows):
    """The terminal stand-in for the home screen."""
    icon = {cal.LIST_NOW: "[!]", cal.LIST_BY: "[>]", cal.WATCHING: "[ ]",
            cal.UNTIMED: "[?]", cal.PASSED: "[x]"}
    out = []
    for row in rows:
        late = "  ** LATE **" if row.get("is_late") else ""
        out.append(f"{icon[row['state']]} {row['moment'].upper():<18} "
                   f"list by {row['list_by']}   peak {row['peak']}{late}")
        out.append(f"      {row['reason']}")

        if not row["evidence"]:
            out.append("      no watched term belongs to this moment — dated, but "
                       "nothing to sell into it")
            out.append("")
            continue

        for e in row["evidence"]:
            if e["basis"] == "unmeasured":
                out.append(f"      - {e['term']:<24} UNMEASURED — {e['note']}")
                continue
            ratio = e["demand_per_listing"]
            wall = "  <- WALL, you cannot rank here" if e["is_wall"] else ""
            money = ("profitable" if e["profitable"]
                     else "fails the margin floor" if e["profitable"] is False
                     else "no measured price")
            out.append(f"      - {e['term']:<24} {e['volume']:>7,} searches / "
                       f"{e['supply']:>8,} listings = {ratio:.3f}{wall}")
            out.append(f"        ${e['price_low']}-{e['price_high']} band, {money} "
                       f"({e['profit_basis']})")
        out.append("")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="calendar_engine")
    parser.add_argument("--country", default="US")
    parser.add_argument("--lead-weeks", type=int, default=6,
                        help="weeks before takeoff you need to be listed")
    parser.add_argument("--type", default=profit.PERSONALIZED,
                        choices=list(profit.PRODUCT_TYPES))
    parser.add_argument("--include-passed", action="store_true")
    args = parser.parse_args(argv)

    rows = build(country=args.country, lead_weeks=args.lead_weeks,
                 product_type=args.type, include_passed=args.include_passed)

    if not rows:
        print("Nothing on the calendar.")
        print("  Dated moments come from the Pinterest bridge:")
        print("    python -m pinterest.pipelines.trends_bridge")
        return 0

    print(f"\nCALENDAR — {args.country}, listing {args.lead_weeks} weeks before takeoff, "
          f"{args.type} product\n")
    print(render(rows))

    actionable = [r for r in rows if r["actionable"]]
    print(f"{len(rows)} dated moment(s); {len(actionable)} with a measured, "
          f"non-wall term behind them.")
    if not actionable:
        print("Every dated moment is either unmatched or backed only by wall terms. "
              "That is a real answer: the dates are right and nothing you watch fits "
              "them. Add terms with: settings_store term add \"christmas ornament\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

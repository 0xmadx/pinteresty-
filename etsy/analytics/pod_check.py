"""Can print-on-demand make this term profitably? One answer, from three readings.

Written after doing this by hand twice with throwaway scripts. The workflow is
short and it produced the most decision-relevant number of that session, so it
belongs in the codebase rather than in a scratch file.

THE FINDING THAT MAKES THIS WORTH A MODULE (D-46)
--------------------------------------------------
`results-data` reports a `search_term_median_price` band, and it is NOT what the
listings on page one charge. Measured live on `personalized baby blanket`:

    API median band          $11.70 - $14.30
    page one, actually       $11.65 min | $25.43 MEDIAN | $70.21 max  (n=20)

Both are probably right and measuring different populations — the band looks
market-wide across all 104,368 listings, while page one is the ~20 that rank. The
listings that win charge about **twice** the market median.

That gap decides POD viability, because the margin floor is applied to a price:

    at $11.70 (API band)      max COGS + shipping = $5.21   -> POD near-impossible
    at $25.43 (page one)      max COGS + shipping = $12.82  -> POD plausible

Anchoring to the API band alone rejects terms POD could actually serve. The
competitor cards needed to compute the real figure arrive **free** in the same
response (20 of them), so this costs no extra call.

WHAT THIS CANNOT TELL YOU
-------------------------
**The actual COGS.** Printify's catalog exposes no price on a variant — only a
built product object has one, and the Premium discount cannot be read at all. So
this never returns "profitable"; it returns a **ceiling** and hands the sourcing
question back to the operator, which is the honest shape (D-27: no LLM, and no
module, invents a cost).
"""
from etsy.analytics import profit
from etsy.analytics.pod_costing import affordable_cogs

# Etsy's fastest delivery bracket. Printify handling alone is typically 10 days, so
# this bracket is structurally closed to POD — worth stating rather than rediscovering.
FAST_BRACKET_DAYS = 7


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return None
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def page_one_prices(cards):
    """What the listings that actually RANK charge — not the market-wide band.

    `cards` are the parsed competitor listings that ride along with every
    results-data call (`data["listings"]`), already normalised by
    `normalise_listing_card`, so `price` is a float and needs no re-parsing here.
    """
    prices = sorted(c["price"] for c in (cards or []) if c.get("price"))
    if not prices:
        # Absent is not zero (N-02): no readable price is unknown, and returning 0
        # would compute a COGS ceiling of "impossible" for a term nobody priced.
        return {"basis": "unmeasured", "n": 0,
                "detail": "no readable price on any competitor card"}
    # Rounded to the cent: prices are cents-denominated, and an even-n median
    # otherwise carries binary-float noise ($25.189999999999998) that means nothing
    # and leaks into every downstream ceiling and display.
    median = round(_median(prices), 2)
    return {"basis": "measured", "n": len(prices),
            "min": prices[0], "median": median, "max": prices[-1],
            "detail": f"{len(prices)} ranking listings: ${prices[0]:.2f} to "
                      f"${prices[-1]:.2f}, median ${median:.2f}"}


def price_reality(data):
    """The API's market-wide band beside page one's actual prices. Never merged.

    Two populations, reported separately with the ratio between them, because
    collapsing them into one "price" is exactly what makes a viable POD term look
    impossible. `ratio` above ~1 means the winners charge a premium over the
    market median — the usual case, and the whole point of measuring it.
    """
    band_low, band_high = data.get("price_low"), data.get("price_high")
    page = page_one_prices(data.get("listings"))

    out = {"band_low": band_low, "band_high": band_high, "page_one": page}
    if page["basis"] != "measured" or not band_high:
        out["ratio"] = None
        out["note"] = ("only one price population is measured — cannot compare "
                       "the market band with page one")
        return out

    band_mid = (band_low + band_high) / 2 if band_low else band_high
    out["ratio"] = round(page["median"] / band_mid, 2) if band_mid else None
    if out["ratio"] and out["ratio"] >= 1.3:
        out["note"] = (f"the listings that RANK charge {out['ratio']}x the market "
                       f"median band — price the ceiling off page one, not the band")
    else:
        out["note"] = "page one prices in line with the market band"
    return out


def ceilings(reality, product_type=profit.PHYSICAL, labor_minutes=2.0,
             shipping_cost=0.0, shipping_charged=0.0, config=None):
    """The most a unit may cost to make, at each price worth considering.

    Returns one entry per price point, each `None` where even a free product
    misses the margin floor — which says the price cannot carry Etsy's fees at
    all, and is a real answer about the price rather than about the supplier.
    """
    points = []
    page = reality.get("page_one") or {}
    if reality.get("band_low"):
        points.append(("market band low", reality["band_low"]))
    if page.get("basis") == "measured":
        points.append(("page-one min", page["min"]))
        points.append(("page-one MEDIAN", page["median"]))
        points.append(("page-one max", page["max"]))

    out = []
    for label, price in points:
        out.append({
            "label": label, "price": price,
            "max_cogs": affordable_cogs(price, product_type,
                                        shipping_cost=shipping_cost,
                                        shipping_charged=shipping_charged,
                                        labor_minutes=labor_minutes, config=config),
        })
    return out


def lead_time_verdict(options):
    """Can any Printify option reach Etsy's fast bracket? Usually no, and that is fine.

    `options` are `PodOption`s from `pod_costing.find_options`. Handling time is one
    of the few things Printify's API DOES expose, and it is often the deciding
    number: a 10-day handling floor closes the 7-day bracket outright, so a POD
    listing competes on everything except speed.
    """
    known = [o for o in (options or []) if o.handling_days is not None]
    if not known:
        return {"basis": "unmeasured",
                "detail": "no handling time returned for any option"}
    best = min(known, key=lambda o: o.handling_days)
    fast = [o for o in known if o.can_ship_fast]
    return {
        "basis": "measured",
        "fastest_handling_days": best.handling_days,
        "fastest_option": f"{best.blueprint_title} / {best.provider_title}",
        "lead_days": best.lead_days,
        "can_reach_fast_bracket": bool(fast),
        "detail": (
            f"fastest handling {best.handling_days} days "
            f"({best.blueprint_title} / {best.provider_title}), door-to-door "
            f"{best.lead_days[0]}-{best.lead_days[1]} days — "
            + ("can reach Etsy's 7-day bracket"
               if fast else
               f"Etsy's {FAST_BRACKET_DAYS}-day bracket is closed to this; you "
               f"compete on everything except speed")),
    }


def check(term, data, options=None, product_type=profit.PHYSICAL,
          labor_minutes=2.0, shipping_cost=0.0, config=None):
    """The whole POD question for one term. Returns a ceiling, never a 'profitable'.

    `data` is parsed results-data; `options` are PodOptions (may be None when
    Printify was not consulted or is unreachable).
    """
    reality = price_reality(data)
    return {
        "term": term,
        "demand": {"volume": data.get("volume"), "supply": data.get("supply"),
                   "cvr": data.get("cvr"), "wow_change": data.get("wow_change")},
        "price_reality": reality,
        "ceilings": ceilings(reality, product_type, labor_minutes,
                             shipping_cost, config=config),
        "lead_time": lead_time_verdict(options),
        # Said once, plainly, so no caller mistakes a ceiling for a verdict.
        "cogs_basis": "unavailable_from_printify_catalog",
        "next_step": ("price this in the Printify UI and compare against the "
                      "page-one MEDIAN ceiling above — the catalog API has no "
                      "variant price, so the system cannot close this itself"),
    }


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(
        prog="pod_check", description="Can print-on-demand serve this term profitably?")
    parser.add_argument("term")
    parser.add_argument("--product-type", default=profit.PHYSICAL)
    parser.add_argument("--labor-minutes", type=float, default=2.0,
                        help="operator time per unit; POD is usually just ordering")
    parser.add_argument("--no-printify", action="store_true",
                        help="skip the Printify lookup (demand + ceilings only)")
    args = parser.parse_args(argv)

    # The mirror this project reads goes stale on its own and a stale copy 401s
    # mid-run rather than failing cleanly (see CLAUDE.md). require() syncs first.
    from core.preflight import require
    require("etsy_private")

    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data

    data = parse_results_data(EtsyPrivateAPI().get_results_data(args.term))
    if not data or not data.get("volume"):
        print(f"No demand reading for {args.term!r} — Etsy returned no volume. "
              f"That is unmeasured, not zero.")
        return 1

    options = None
    if not args.no_printify:
        try:
            from etsy.analytics.pod_costing import find_options
            from etsy.api.printify.client import PrintifyClient
            options = find_options(PrintifyClient(), args.term, limit=6)
        except Exception as e:
            # Printify is additive here: the price ceiling is computed from Etsy
            # data alone, so a Printify failure costs the lead-time reading only.
            print(f"[printify unavailable: {type(e).__name__}: {e}]\n")

    print(render(check(args.term, data, options=options,
                       product_type=args.product_type,
                       labor_minutes=args.labor_minutes)))
    return 0


def render(result):
    """Terminal view. Ceiling first, because that is the number to act on."""
    d, r = result["demand"], result["price_reality"]
    out = [f"POD CHECK: {result['term']}", ""]

    vol, sup = d.get("volume"), d.get("supply")
    if vol and sup:
        out.append(f"  demand   {vol:,}/mo vs {sup:,} listings "
                   f"({vol / sup:.2f} per listing)")
    wow = d.get("wow_change")
    if wow is not None:
        out.append(f"  this week {wow:+.1f}% (Etsy week-over-week)")

    out.append("")
    out.append("  PRICE")
    if r.get("band_low"):
        out.append(f"    market band   ${r['band_low']:.2f} - ${r['band_high']:.2f}")
    page = r.get("page_one") or {}
    if page.get("basis") == "measured":
        out.append(f"    page one      ${page['min']:.2f} | MEDIAN "
                   f"${page['median']:.2f} | ${page['max']:.2f}  (n={page['n']})")
    out.append(f"    -> {r.get('note')}")

    out.append("")
    out.append("  MAX COGS + SHIPPING (to clear the margin floor)")
    for c in result["ceilings"]:
        cap = f"${c['max_cogs']:.2f}" if c["max_cogs"] is not None else \
            "IMPOSSIBLE — price cannot carry Etsy's fees"
        mark = "  <-- price here" if c["label"] == "page-one MEDIAN" else ""
        out.append(f"    ${c['price']:>7.2f}  {c['label']:<16} {cap}{mark}")

    lt = result["lead_time"]
    out.append("")
    out.append("  LEAD TIME")
    out.append(f"    {lt.get('detail')}")

    out.append("")
    out.append(f"  COGS: {result['cogs_basis']}")
    out.append(f"  NEXT: {result['next_step']}")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())

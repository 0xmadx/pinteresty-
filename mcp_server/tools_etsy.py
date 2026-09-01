"""The two Etsy tiers, raw — demand truth and competition truth, kept apart.

`etsy_private` authenticates as the operator's OWN seller account. `etsy_public`
uses a replaceable buyer session. **They are separate tools on purpose**, because
D-29 is the rule that costs the most to break: a burned buyer session costs a
re-login, a burned seller account costs the business. Two names make the tier
visible at the call site instead of buried in a parameter.

Never pass a competitor's `shop_id` into a private call — the `{shop_id}` in a
private URL is *who we are*, not who we are asking about.

WHAT THE PRIVATE TIER UNIQUELY KNOWS
------------------------------------
Real search volume, real CVR, the 12-month seasonal curve, and Etsy's own
keyword expansion. Nothing public answers any of those at any price. It is also
the tier to spend LAST — discover cheap, qualify public, measure private.

`daily_stats` is the one to notice: a **day-by-day** volume series with a rolling
average that rides free on every `results_data` call and was parsed by nothing
until now (D-51). For a calendar-first product, a daily curve is a sharper
instrument than the monthly one — and it costs nothing extra.
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import EtsyPrivateOp, EtsyPublicOp
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp

_PRIVATE_DOC = (
    "results_data: volume, supply, CVR, price band + 20 competitor cards in ONE call. "
    "daily_stats: the DAILY volume curve riding free on that same call. "
    "chart_series: the 12-month seasonal curve (pass comma-separated terms to compare). "
    "similar_keywords: Etsy's own LLM expansion, ~120-165 terms each already sized. "
    "trending: rising terms for a category id, no quota cost. "
    "⚠️ EVERY operation spends the operator's own SELLER account (D-29) — spend it "
    "last, on candidates that already survived free discovery."
)

_PUBLIC_DOC = (
    "search: the SERP — total supply, ranked ids, ~12 cards. "
    "listing: one listing's 13 tags + breadcrumb + product type, 30-day cache, the "
    "cheapest call here. shop_metrics/shop_listings: a competitor shop, tracked or "
    "not. All use a replaceable buyer session — unlimited, no seller-account risk."
)


@mcp.tool()
@_guarded
def etsy_private(
    operation: Annotated[EtsyPrivateOp, Field(description=_PRIVATE_DOC)],
    term: str | None = None,
    days: int = 365,
    taxonomy_id: int = 199,
) -> dict:
    """Demand truth — real volume, CVR and seasonality. SPENDS THE SELLER ACCOUNT (D-29)."""
    if operation != "trending" and not term:
        return _fail(f"operation '{operation}' needs `term`",
                     fix="Pass the keyword to measure.")

    blocked = _preflight(("etsy_private",))
    if blocked:
        return blocked

    from etsy.api.private.api import (MAX_CHART_TERMS, EtsyPrivateAPI, SessionDown,
                                      chart_coverage, parse_chart_series,
                                      parse_results_data, parse_term_summaries)
    api = EtsyPrivateAPI()
    try:
        if operation in ("results_data", "daily_stats"):
            raw = api.get_results_data(term)
            if not raw:
                return _fail("the private API returned nothing for this term",
                             fix="Check the seller session: python -m core.vault_status")
            if operation == "daily_stats":
                return _daily_stats(term, raw)
            d = parse_results_data(raw)
            return _ok({
                "operation": operation, "term": term,
                "volume": {"value": d.get("volume"), "basis": "measured"},
                "supply": {"value": d.get("supply"), "basis": "measured"},
                "query_cvr": {"value": d.get("cvr"), "basis": "measured",
                              "note": "NO KNOWN UNITS — compare between terms only, "
                                      "never multiply by volume to get orders (D-43)"},
                "price_band": {"low": d.get("price_low"), "high": d.get("price_high"),
                               "basis": "measured"},
                "wow_change": {"value": d.get("wow_change"),
                               "direction": d.get("wow_direction"), "basis": "measured"},
                "competitors": d.get("listings"),
                "competitor_count": len(d.get("listings") or []),
                "note": "The 20 competitor cards are FREE in this response — do not "
                        "scrape the public SERP to rebuild what you already have.",
            })

        if operation == "chart_series":
            terms = [t.strip() for t in term.split(",") if t.strip()]
            raw = api.get_chart_series(terms, days=days)
            curves = parse_chart_series(raw)
            # Etsy answers only 3 terms per request; the client chunks and merges, so
            # `terms` above is genuinely what was asked. Until 2026-09-01 it was not:
            # the note here told the agent that a missing term meant Etsy could not
            # size it, when 8 of 11 had simply never been requested. Coverage now
            # carries the distinction instead of prose asserting one reading.
            coverage = chart_coverage(raw)
            return _ok({
                "operation": operation, "terms": terms, "days": days,
                "summaries": parse_term_summaries(raw),
                "curves": curves, "returned": len(curves),
                "coverage": coverage,
                "requests_spent": -(-len(terms) // MAX_CHART_TERMS),
                "basis": coverage.get("basis", "measured"),
                "note": "⚠️ The LAST bucket is the current month counted SO FAR — "
                        "judging on it manufactures a collapse (D-45). "
                        "For a missing term read `coverage`, never `returned` alone: "
                        "`omitted` is Etsy declining to size it (UNMEASURED, N-02), "
                        "while `failed_chunks > 0` means it may simply never have been "
                        "fetched. Those are different claims and only the first is a "
                        "fact about the market.",
            })

        if operation == "similar_keywords":
            # iterations capped like the crawl: the CLI's 10 is for a human who
            # chose to wait, and each round is a fresh enqueue+poll.
            edges = api.get_similar_keywords(term, iterations=3) or []
            return _ok({
                "operation": operation, "seed": term,
                "edges": edges, "count": len(edges),
                "basis": "measured — every edge carries its own volume and supply "
                         "inline, so the whole neighbourhood is sized in one call",
                "note": "The tree has CYCLES (felt banner lists felt garland back); "
                        "dedupe if you walk it. iterations capped at 3 here vs the "
                        "CLI's 10 — fewer distinct LLM edges, ~3.5x cheaper.",
            })

        if operation == "trending":
            data = api.get_trending_terms(taxonomy_id=taxonomy_id)
            return _ok({
                "operation": operation, "taxonomy_id": taxonomy_id,
                "trending": data, "basis": "etsy_curated",
                "note": "⚠️ These are Etsy's PICKS, not the top of the market (B-01). "
                        "Only 7 of 15 probed taxonomy ids return anything: "
                        "1, 66, 199, 323, 891, 1429, 1633. No quota cost.",
            })
    except SessionDown as e:
        return _fail(f"SessionDown: {e}",
                     fix="The SELLER session is stale or absent. Open Chrome with "
                         "the extension on a Shop Manager tab, then check: "
                         "python -m core.vault_status")
    return _fail(f"unknown operation: {operation}")


def _daily_stats(term, raw):
    """The daily curve that rides free on results_data and nothing parsed (D-51)."""
    block = (raw or {}).get("daily_stats") or {}
    rows = block.get("stats") or []
    if not rows:
        return _ok({"operation": "daily_stats", "term": term, "points": [],
                    "basis": "unmeasured",
                    "note": "Etsy returned no daily block for this term."})
    vals = [r.get("search_volume") for r in rows if r.get("search_volume") is not None]
    peak = max(rows, key=lambda r: r.get("search_volume") or -1)
    return _ok({
        "operation": "daily_stats", "term": term,
        "points": [{"date": r.get("date"), "volume": r.get("search_volume"),
                    "rolling_7d": r.get("wow_rolling_average")} for r in rows],
        "days": len(rows),
        "peak": {"date": peak.get("date"), "volume": peak.get("search_volume")},
        "range": {"min": min(vals), "max": max(vals)} if vals else None,
        "basis": "measured",
        "note": "DAILY resolution — sharper than chart_series' monthly curve, and it "
                "rides free on the same results_data call. Covers roughly the "
                "trailing three weeks, so it answers 'is this moving NOW', not "
                "'when does it peak annually' (D-51).",
    })


@mcp.tool()
@_guarded
def etsy_public(
    operation: Annotated[EtsyPublicOp, Field(description=_PUBLIC_DOC)],
    term: str | None = None,
    listing_id: str | None = None,
    shop: str | None = None,
    page: int = 1,
) -> dict:
    """Competition truth — who ranks, what they tag. Buyer session: unlimited, safe."""
    need = {"search": term, "listing": listing_id,
            "shop_metrics": shop, "shop_listings": shop}.get(operation)
    if not need:
        arg = {"search": "term", "listing": "listing_id"}.get(operation, "shop")
        return _fail(f"operation '{operation}' needs `{arg}`")

    blocked = _preflight(("etsy",))
    if blocked:
        return blocked

    from etsy.api.public.api import EtsyPublicAPI
    api = EtsyPublicAPI()

    if operation == "search":
        data = api.get_public_search(term) or {}
        cards = data.get("cards") or []
        organic = [c for c in cards if not c.get("is_ad")]
        return _ok({
            "operation": operation, "term": term,
            "total_results": {"value": data.get("total_results"),
                              "basis": "measured (ESTIMATE — drifts ~0.1% between "
                                       "identical calls; never test for equality)"},
            "cards": cards, "cards_returned": len(cards),
            "organic_cards": len(organic),
            "ranked_listing_ids": data.get("organic_listing_ids"),
            "total_pages": data.get("total_pages"),
            "note": "⚠️ Only ~12 of the page's slots render server-side and about "
                    "half are ADS — do not divide by results_per_page. Page 2+ is "
                    "never requested by this system, so rank beyond page one is "
                    "unknown rather than absent.",
        })

    if operation == "listing":
        data = api.get_listing_data(listing_id) or {}
        return _ok({
            "operation": operation, "listing_id": listing_id,
            "tags": data.get("tags"), "breadcrumb": data.get("breadcrumb"),
            "product_type": data.get("product_type"),
            "basis": "measured", "cache": "30 days — the cheapest call here",
            "note": "The 13 tags are what this listing actually ranks on. "
                    "product_type decides which margin floor applies (D-22); it is "
                    "read from HTML markers, so a blocked page yields None rather "
                    "than 'physical'.",
        })

    from core.shop_scraper import ShopScraper
    scraper = ShopScraper()
    if operation == "shop_metrics":
        m = scraper.get_shop_metrics(shop) or {}
        return _ok({
            "operation": operation, "shop": shop, "metrics": m,
            "basis": "measured",
            "note": "⚠️ Etsy's sales counter is QUANTISED at scale — a shop showing "
                    "'25,100' steps by 100, so a zero delta between readings means "
                    "'moved less than the counter can show', never 'sold nothing'.",
        })

    listings = scraper.get_shop_listings(shop, page=page) or []
    return _ok({
        "operation": operation, "shop": shop, "page": page,
        "listings": listings, "count": len(listings), "basis": "measured",
    })

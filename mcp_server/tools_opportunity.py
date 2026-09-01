"""Is there room here? Demand, supply, saturation, sourcing.

Split out of the single 699-line `server.py` (D-53). Registration happens
on import — `server.py` imports this module for that side effect alone.
Every tool here follows the same contract: `@mcp.tool()` outermost,
`@_guarded` innermost, `_preflight` first if it touches the network, and
`_ok`/`_fail` with a per-field `basis` on the way out.
"""
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp


@mcp.tool()
@_guarded
def analyze_keyword(keyword: str) -> dict:
    """Is there room in this niche? Demand, supply, and the ratio between them.

    Returns demand-per-listing as the headline, NOT search volume. A term with
    310,467 searches and 2,160,627 listings (0.14 demand/listing) is a wall; one
    with 69,874 searches and 25,031 listings (2.79) is an opportunity. Ranking by
    volume inverts that and is the single most common way this analysis goes wrong.
    """
    blocked = _preflight(("etsy", "etsy_private"))
    if blocked:
        return blocked

    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.api.public.api import EtsyPublicAPI

    data = parse_results_data(EtsyPrivateAPI().get_results_data(keyword))
    if not data:
        return _fail("the private API returned nothing for this keyword",
                     fix="Check the etsy_private session: python -m core.vault_status")

    # FLAT keys. parse_results_data owns the wire shape precisely so callers do
    # not index raw API keys; indexing a stats block it never returns is the same
    # mistake one layer up.
    volume = data.get("volume")
    supply = data.get("supply")
    public = EtsyPublicAPI().get_public_search(keyword) or {}
    public_supply = public.get("total_results")

    ratio = (volume / supply) if (volume and supply) else None
    return _ok({
        "keyword": keyword,
        "search_volume": {"value": volume, "basis": "measured" if volume else "unmeasured"},
        "supply_private": {"value": supply, "basis": "measured" if supply else "unmeasured"},
        "supply_public": {"value": public_supply,
                          "basis": "measured (ESTIMATE — drifts ~0.1% between "
                                   "identical calls)" if public_supply else "unmeasured"},
        "demand_per_listing": {"value": round(ratio, 4) if ratio else None,
                               "basis": "derived" if ratio else "unmeasured",
                               "note": "THE headline number. Above ~1.0 is worth a "
                                       "look; below ~0.2 you cannot rank."},
        "query_cvr": {"value": data.get("cvr"),
                      "basis": "measured" if data.get("cvr") is not None else "unmeasured",
                      "bucket": data.get("cvr_bucket")},
        "median_price": {"low": data.get("price_low"), "high": data.get("price_high"),
                         "basis": "measured"},
        "wow_change": {"value": data.get("wow_change"),
                       "direction": data.get("wow_direction"),
                       "basis": "measured", "note": "Etsy's own week-over-week %"},
        "competitors_returned": len(data.get("listings") or []),
    })


@mcp.tool()
@_guarded
def sourcing_profile(keyword: str, sample: int = 12) -> dict:
    """Where do sellers in this niche ship from, and how fast?

    Origin comes from SAMPLING listings, not from Etsy's ships-from filter — that
    filter returns a broader result set than the search it filters and its counts
    are not shares of anything (see sourcing.LOCATION_QUERY_IS_NOT_A_FILTER). The
    sample describes what a buyer sees first, which is the competitive question.

    Lead time comes from the delivery_days brackets, which ARE sound: monotonic,
    cumulative, verified on the wire.
    """
    blocked = _preflight(("etsy",))
    if blocked:
        return blocked

    from etsy.analytics import sourcing
    from etsy.api.public.api import EtsyPublicAPI
    api = EtsyPublicAPI()

    profile = sourcing.fetch_profile(api, keyword, countries=())
    bands = sourcing.delivery_distribution(profile)
    origins = sourcing.sample_origins(api, keyword, sample_size=sample)

    return _ok({
        "keyword": keyword,
        "total_supply": {"value": profile.total_supply, "basis": "measured"},
        "delivery_bands": [{"band": b, "share": v, "basis": "measured"} for b, v in bands],
        "median_delivery_band": sourcing.median_band(profile),
        "origins": {"distribution": origins["origins"],
                    "sampled": origins["sampled"], "resolved": origins["resolved"],
                    "unknown": origins["unknown"],
                    "basis": "measured, SAMPLE — " + origins["basis"]},
        "sampled_lead_days": origins["lead_days"],
        "findings": sourcing.read(profile),
    })


@mcp.tool()
@_guarded
def cheap_competitors(keyword: str, n: int = 5) -> dict:
    """Why are the cheapest listings cheap? Origin of the price-floor sellers.

    Asks the question where it matters — the cheap tail sets the floor, not the
    market mean. A foreign-sounding shop name is not evidence: one shop called
    "TurkishTowelWeaving" ships from New Jersey.
    """
    blocked = _preflight(("etsy",))
    if blocked:
        return blocked
    from etsy.analytics import sourcing
    from etsy.api.public.api import EtsyPublicAPI
    api = EtsyPublicAPI()
    rows = sourcing.explain_cheap_listings(api, keyword, n=n)
    return _ok({"keyword": keyword, "listings": rows,
                "findings": sourcing.read_cheap_listings(rows),
                "basis": "measured per listing; listings with no declared origin "
                         "are excluded, never assumed domestic"})


@mcp.tool()
@_guarded
def deep_dive_keyword(seed: str, product_type: str = "physical", max_depth: int = 1,
                      max_nodes: int = 5, cogs: float = 0.0, shipping_cost: float = 0.0,
                      labor_minutes: float = 0.0) -> dict:
    """Deep dive: crawl a seed, profit-gate it, then arbitrage every winner across
    format/quality/occasion/feature/colour/sourcing. SLOW — dozens of requests and
    several minutes; run `analyze_keyword` or `discover` first. ⚠️ Leaving cogs at 0
    on a physical/personalized seed makes the gate flatter EVERY candidate, so
    everything clears and you get false WINNERS (not false gaps). An empty result
    is returned as an error, meaning "nothing here", not a failure."""
    blocked = _preflight(("etsy", "etsy_private"))
    if blocked:
        return blocked

    from etsy.engines.master_arbitrage import HybridArbitrageEngine

    product_profile = {"product_type": product_type, "cogs": cogs,
                       "shipping_cost": shipping_cost, "labor_minutes": labor_minutes}
    engine = HybridArbitrageEngine(seed_keyword=seed, max_depth=max_depth,
                                   max_nodes=max_nodes, product_type=product_type,
                                   product_profile=product_profile)
    report = engine.run()
    if not report:
        return _fail(
            "nothing cleared the BFS crawl or the profit gate for this seed",
            fix="try a different seed, a different product_type, or pass real "
                "cogs/shipping_cost/labor_minutes if this is a physical or "
                "personalized product and they were left at 0")
    return _ok(report)


@mcp.tool()
@_guarded
def filter_trust_report() -> dict:
    """Which Etsy SERP filters can be believed — and which silently lie.

    Read this before trusting any saturation percentage. 9 of 12 audited filters
    do not return a subset of the market they claim to filter: min_rating=5 returns
    4.8-rated listings, colour brackets sum to 562% of supply, and the ships-from
    filter returns more listings than exist.
    """
    from etsy.analytics import filter_trust
    reg = filter_trust.load()
    return _ok({
        "filters": [{"name": n, "status": v.status, "usable": v.usable,
                     "stale": v.stale, "note": v.note}
                    for n, v in sorted(reg.items())],
        "trusted": sorted(n for n, v in reg.items() if v.usable and not v.stale),
        "note": "Only `trusted` filters may produce a gap verdict. find_gaps "
                "returns `untrusted_source` for the rest rather than a percentage.",
    })

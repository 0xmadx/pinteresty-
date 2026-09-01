"""What should I list, and when? The question-shaped front doors.

Split out of the single 699-line `server.py` (D-53). Registration happens
on import — `server.py` imports this module for that side effect alone.
Every tool here follows the same contract: `@mcp.tool()` outermost,
`@_guarded` innermost, `_preflight` first if it touches the network, and
`_ok`/`_fail` with a per-field `basis` on the way out.
"""
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp


@mcp.tool()
@_guarded
def calendar(lead_weeks: int = 6, product_type: str = "personalized",
             country: str = "US") -> dict:
    """What to list and by when — Pinterest takeoff dates joined to Etsy demand, each
    moment carrying a list-by deadline and its watched terms. ⚠️ Read `is_wall`: a term
    can clear the margin gate and still be unrankable (christmas ornament — 25,477
    searches against 1,405,731 listings). Rank by demand_per_listing, never volume.
    `state` untimed = deadline passed with no measured peak, so late cannot be told
    from missed — report unknown, never opportunity."""
    from etsy.engines import calendar_engine
    rows = calendar_engine.build(country=country, lead_weeks=lead_weeks,
                                 product_type=product_type)
    return _ok({
        "lead_weeks": lead_weeks,
        "moments": [{
            "moment": r["moment"], "state": r["state"], "list_by": r["list_by"],
            "peak": r.get("peak"), "is_late": r.get("is_late"),
            "reason": r["reason"], "actionable": r["actionable"],
            "terms": r["evidence"],
        } for r in rows],
        "basis": "measured (Pinterest takeoff dates + Etsy keyword observations); "
                 "profit verdicts follow the settings basis — see settings_summary",
        "note": "A moment with no terms is dated but has nothing aimed at it — that "
                "is 'we have not looked', not 'no opportunity'.",
    })


@mcp.tool()
@_guarded
def cockpit(keyword: str, product_type: str = "personalized",
            lead_weeks: int = 6) -> dict:
    """Everything known about ONE candidate, three sources kept APART: timing
    (Pinterest), demand (Etsy Private), supply (Etsy Public). `combined.conflicts` is
    the field that matters — good timing plus unrankable supply is two opposite
    readings, not a middling score. DB-only, no live calls. A `trend` basis of
    `refused` means the comparison would have measured our own instrument."""
    from etsy.engines import cockpit as ck
    state = ck.build(keyword, product_type=product_type, lead_weeks=lead_weeks)
    from core.settings_store import load
    prov = "provisional (settings not confirmed)" if load().basis()["basis"] != "operator" else "derived (settings confirmed)"
    return _ok({"candidate": state, "findings": ck.read(state),
                "basis": f"measured where stated; profit verdict is {prov}"})


@mcp.tool()
@_guarded
def discover(limit: int = 40) -> dict:
    """The ranked candidate POOL — terms the operator never typed, expanded from
    watched seeds and ranked by demand-per-listing, NOT volume (D-31). Only
    `winnable`/`contested` are worth a look; a `wall` is supply swamping demand
    however big its traffic. Where to LOOK, not what to make — cockpit checks each.
    Reads the stored sweep, so it is empty until that job runs."""
    # Through app_data — the one read layer every view is supposed to share
    # (D-41). This used to query MarketDatabase directly, its own second
    # implementation of "what counts as discovered" that could silently drift
    # from what the web UI shows for the exact same pool.
    from etsy.ui.app_data import build_discovered
    pool = build_discovered(limit=2000)
    good = [r for r in pool if r.get("verdict") in ("winnable", "contested")]
    return _ok({
        "worth_a_look": good[:limit],
        "total_discovered": len(pool),
        "walls_folded": len(pool) - len(good),
        "basis": "measured (LLM keyword edges carry their own volume and supply); "
                 "ranked by demand-per-listing, never by volume",
        "note": "verdict winnable/contested is a coarse label, not a score. A wall "
                "is not a bad term, it is an unrankable one for a shop with no "
                "authority.",
    })


@mcp.tool()
@_guarded
def tracked_market() -> dict:
    """The competitor shop window: tracked shops and their listings that match a
    watched term, ranked by review velocity.

    Two numbers to read carefully. `sales_per_day` is a BOUND — Etsy's counter is
    quantised, so "fewer than 21/day" is honest and "0/day" is not. Review velocity
    is a FLOOR — reviews undercount sales, so a listing gaining reviews sells at
    least that fast. Both tracked shops are stars (B-01): this shows what winners
    do, not what works.
    """
    from etsy.ui.app_data import gather_shops
    data = gather_shops()
    return _ok({
        "shops": [{
            "shop": d["shop"],
            "lifetime_sales": (d["latest"] or {}).get("total_sales"),
            "sales_per_day_bound": d["rate_bound"],
            "matched_listings": [{
                "title": m.get("title"), "matches": m.get("matched_term"),
                "review_velocity_floor": (m.get("velocity") or {}).get("velocity"),
                "velocity_basis": (m.get("velocity") or {}).get("basis"),
            } for m in d["matched"]],
        } for d in data],
        "basis": "measured; sales-per-day is a bound, review velocity a floor",
        "warning": "all tracked shops are star sellers — survivor bias (B-01)",
    })


# `compare` lives in etsy/analytics/compare.py, NOT here. It was written in this
# file first and that was the wrong layer: ~290 lines of gate sequencing inside a
# protocol adapter, importable only through the MCP plumbing. The web app on the
# roadmap would have had to import from `mcp_server` — a protocol adapter is not a
# library — or reimplement the gates and give the system two gate orders that drift.
# D-41 already names one read layer for exactly this reason.
#
# What stays here is the tool envelope: the schema, the preflight, and the
# `_ok`/`_fail` framing. Every other surface calls `compare_terms()` directly.
from etsy.analytics.compare import MAX_COMPARE_CHEAP, MAX_COMPARE_FULL  # noqa: E402
from etsy.analytics.compare import compare as compare_terms  # noqa: E402


@mcp.tool()
@_guarded
def compare(terms: str, mode: str = "cheap") -> dict:
    """Compare a LIST of keywords you typed, side by side, ranked. The batch door.

    mode=cheap: one chunked chart-series sweep, ~ceil(N/3) requests, adds the
    12-month seasonal curve, NO CVR so the intent gate cannot run.
    mode=full: one results-data call per term, adds CVR, the price band and
    page-one prices, so intent is judged. Spends the seller account per term.

    Sorted by demand-per-listing, never volume (D-31). REFUSES to score when the
    dimensions cannot separate the pool (N-01). Over the per-mode cap it refuses
    rather than trimming.
    """
    out = compare_terms(terms, mode=mode, preflight=_preflight)
    if not out.get("ok"):
        # A preflight block is already a fully-formed _fail payload; pass it through
        # rather than re-wrapping it and losing its `fix`.
        if "error" not in out:
            return out
        return _fail(out["error"], **{k: v for k, v in out.items()
                                      if k not in ("ok", "error")})
    return _ok({k: v for k, v in out.items() if k != "ok"})

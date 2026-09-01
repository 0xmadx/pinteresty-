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


# The batch entry point the surface never had. Every other tool here is singular —
# one term, one moment, one shop — and behind them sits a complete, tested pool
# ranker (`scoring.score_pool`/`explain`) whose only callers were two CLI engines.
# So the agent could reach `can_discriminate`, the guard that REFUSES a ranking,
# without being able to reach the ranking it guards: the surface could say "these
# cannot be compared" and never "here is the comparison".
#
# Caps are per-mode because the modes cost differently per term. Both REFUSE rather
# than clamp (the `keyword_crawl` precedent): a silent clamp leaves the agent
# believing it compared a list it only sampled, which is worse than an error.
MAX_COMPARE_CHEAP = 60   # ceil(60/3) = 20 requests
MAX_COMPARE_FULL = 25    # 1 request per term, irreducibly



def _monthly_volume(curve):
    """A MONTHLY search volume out of the 12-month curve. `(value, basis)`.

    ⚠️ THE UNIT BUG THIS EXISTS TO KILL, caught live 2026-09-01 before it shipped.
    `chart-series-data` at days=365 reports `term_summaries.search_volume` as a
    YEAR of searches, while `avg_total_listings` is a point-in-time count. Dividing
    one by the other is a 12-month numerator over a right-now denominator, and it
    inflated demand-per-listing by ~20x:

        custom guitar strap   42,735 / 13,010 = 3.285  "winnable"   <- WRONG
                               2,089 / 13,400 = 0.156  "wall"       <- results-data

    Every term in an 8-term batch flipped verdict. `winnability`'s own thresholds
    (D-31) are calibrated on the ~30-day volume that `results-data` returns, so the
    ratio must be fed the same unit or the labels mean nothing.

    The fix costs no extra request: the curve's last COMPLETE month is already in
    the response and is a real monthly reading. Verified against results-data on
    four terms — within 2-7% (2,232 vs 2,089 · 3,052 vs 2,989 · 38,295 vs 37,592 ·
    11,538 vs 11,141).

    The final bucket is skipped when the response flags it partial: it is the current
    month counted so far, and using it would understate demand and look like a
    collapse (D-45). Returns None rather than falling back to the annual figure —
    an unmeasured ratio is honest, a 20x-inflated one is not (N-02).
    """
    points = (curve or {}).get("points") or []
    complete = points[:-1] if (curve or {}).get("last_is_partial") else points
    if not complete:
        return None, "unmeasured — no complete month in the curve"
    last = complete[-1]
    return last.get("value"), f"last complete month ({last.get('label')})"


def _compare_cheap(terms):
    """One chunked chart-series sweep: volume, supply, wow and the 12-month curve.

    ~ceil(N/3) requests for the whole batch, and the seasonal curve rides along free
    (D-45). No CVR at any price — this endpoint does not carry it — so the intent
    gate cannot run in this mode, and says so rather than being skipped in silence.
    """
    from etsy.analytics import seasonality as se
    from etsy.api.private.api import (EtsyPrivateAPI, chart_coverage,
                                      parse_chart_series, parse_term_summaries)

    api = EtsyPrivateAPI()
    raw = api.get_chart_series(terms, days=365)
    summaries = {s["keyword"]: s for s in parse_term_summaries(raw) if s.get("keyword")}
    curves = parse_chart_series(raw)

    rows = {}
    for term in terms:
        s = summaries.get(term) or {}
        curve = curves.get(term)
        monthly, vbasis = _monthly_volume(curve)
        rows[term] = {
            # ⚠️ NOT s["volume"]. At days=365 that is a YEAR of searches, while
            # `supply` is a point-in-time listing count — see _monthly_volume.
            "volume": monthly, "volume_basis": vbasis,
            "volume_annual": s.get("volume"),
            "supply": s.get("supply"),
            "cvr": None,                      # not on this endpoint, ever
            "wow_change": s.get("wow_change"),
            "price_low": None, "price_high": None,
            "seasonality": se.profile(curve) if curve else
                           {"verdict": "unmeasured", "basis": "no_curve"},
        }
    return rows, chart_coverage(raw), -(-len(terms) // 3)


def _compare_full(terms):
    """One results-data call per term: adds CVR, the price band and page-one prices.

    The expensive mode, and the only one that can answer "do these searchers buy".
    Cached 7 days, so a repeat within the week costs nothing — which makes the
    request count an UPPER BOUND, never a measurement.
    """
    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data

    api = EtsyPrivateAPI()
    rows, spent = {}, 0
    for term in terms:
        data = parse_results_data(api.get_results_data(term))
        spent += 1
        if not data:
            rows[term] = {"volume": None, "supply": None, "cvr": None,
                          "basis": "fetch_failed"}
            continue
        listings = data.get("listings") or []
        prices = sorted(p for p in (l.get("price") for l in listings) if p)
        rows[term] = {
            "volume": data.get("volume"), "supply": data.get("supply"),
            "cvr": data.get("cvr"), "wow_change": data.get("wow_change"),
            "price_low": data.get("price_low"), "price_high": data.get("price_high"),
            # D-46: the band is market-wide and includes every listing that never
            # ranks; the median of the 20 that DO rank is a different, higher number
            # and is the one a margin floor should be priced against.
            "page_one_median_price": prices[len(prices) // 2] if prices else None,
            "competitors_returned": len(listings),
        }
    return rows, None, spent


@mcp.tool()
@_guarded
def compare(terms: str, mode: str = "cheap") -> dict:
    """Compare a LIST of keywords you typed, side by side, ranked. The batch door.

    mode=cheap: one chunked chart-series sweep, ~ceil(N/3) requests, adds the
    12-month seasonal curve, NO CVR so the intent gate cannot run.
    mode=full: one results-data call per term, adds CVR, the price band and
    page-one prices, so intent is judged. Spends the seller account per term.

    Sorted by demand-per-listing, never volume (D-31). REFUSES to score when the
    dimensions cannot separate the pool (N-01). Both floors reported, never worked
    around. Over the per-mode cap it refuses rather than trimming.
    """
    from etsy.analytics.discover import (MIN_POOL_FOR_INTENT, confirm_intent,
                                         reference_median, winnability)
    from etsy.analytics.scoring import (MIN_POOL_SIZE, PoolTooSmall,
                                        can_discriminate, explain, score_pool)

    if mode not in ("cheap", "full"):
        return _fail(f"mode '{mode}' is not one of cheap/full")

    # dict.fromkeys dedupes while preserving the order the operator typed, which is
    # the order they will read the table in.
    wanted = list(dict.fromkeys(t.strip() for t in (terms or "").split(",") if t.strip()))
    if len(wanted) < 2:
        return _fail("`terms` needs at least 2 comma-separated keywords",
                     fix="A comparison of one term is a lookup — use `cockpit`.")

    cap = MAX_COMPARE_CHEAP if mode == "cheap" else MAX_COMPARE_FULL
    if len(wanted) > cap:
        return _fail(
            f"{len(wanted)} terms exceeds the {mode}-mode ceiling of {cap}",
            fix=f"This authenticates as the operator's own Etsy SELLER account "
                f"(D-29), which cannot be replaced. Split the list, or use "
                f"mode=cheap (ceiling {MAX_COMPARE_CHEAP}). The 7- and 30-day "
                f"caches make an overlapping second batch nearly free. Refusing "
                f"rather than trimming on purpose: a silent cut would leave you "
                f"comparing a list you only partly measured.")

    blocked = _preflight(("etsy_private",))
    if blocked:
        return blocked

    fetched, coverage, spent = (_compare_cheap(wanted) if mode == "cheap"
                                else _compare_full(wanted))

    # --- the gates, in order, each able only to reject -----------------------------
    measured = [d for d in fetched.values() if d.get("volume")]
    # Count CVRs the way `reference_median` counts them — TRUTHY, not just non-None.
    # Etsy returns query_cvr as exactly 0 for some terms (see confirm_intent), and
    # counting those made the payload contradict itself: `terms_with_cvr: 8` beside a
    # null median that had refused because only 6 were usable. Two definitions of
    # "has a CVR" in one response is how a reader stops trusting the floors.
    cvrs = [d["cvr"] for d in fetched.values() if d.get("cvr")]
    zero_cvrs = [d for d in fetched.values()
                 if d.get("cvr") is not None and not d.get("cvr")]
    # reference_median refuses below MIN_POOL_FOR_INTENT rather than comparing
    # against noise — the same discipline as PoolTooSmall.
    pool_median = reference_median([], extra_cvrs=cvrs) if mode == "full" else None

    rows = []
    for term in wanted:
        d = fetched.get(term) or {}
        win = winnability(d)
        row = {
            "term": term,
            "volume": d.get("volume"), "supply": d.get("supply"),
            "demand_per_listing": win.get("demand_per_listing"),
            "winnability": win.get("verdict"), "why": win.get("reason"),
            "basis": win.get("basis"),
            "wow_change": d.get("wow_change"),
            "price_low": d.get("price_low"), "price_high": d.get("price_high"),
            # Stated, not assumed. Both modes must feed winnability a ~30-day
            # volume; the day this silently became annual, every verdict flipped.
            "volume_basis": d.get("volume_basis", "results-data (~30 days)"),
        }
        if mode == "full":
            row["page_one_median_price"] = d.get("page_one_median_price")
            intent = confirm_intent(d, pool_median)
            row["cvr"] = intent.get("cvr")
            row["intent"] = intent.get("verdict")
            row["cvr_vs_pool"] = intent.get("cvr_vs_pool")
            row["intent_detail"] = intent.get("reason") or intent.get("detail")
        else:
            row["intent"] = "not_checked"
            row["seasonality"] = d.get("seasonality")
            row["volume_annual"] = d.get("volume_annual")

        # The headline is the WORSE of the gates, never an average — averaging lets
        # a huge market hide a closed door.
        if row["basis"] != "measured":
            row["verdict"] = "unmeasured"
        elif row["winnability"] == "wall":
            row["verdict"] = "wall"
        elif row.get("intent") == "weak":
            row["verdict"] = "searched_not_bought"
        else:
            row["verdict"] = row["winnability"]
        rows.append(row)

    # Sort by the ratio, not by any composite. A term nobody could size sorts last
    # because it cannot be compared, not because it is worst (N-02).
    rows.sort(key=lambda r: (r["demand_per_listing"] is None,
                             -(r["demand_per_listing"] or 0)))

    # --- may this pool be ranked at all? -------------------------------------------
    pool = [{"key": r["term"], "demand": r["volume"], "supply": r["supply"],
             **({"intent": r["cvr"]} if r.get("cvr") is not None else {})}
            for r in rows if r["volume"] and r["supply"]]
    rankable, ranked = None, None
    if len(pool) >= MIN_POOL_SIZE:
        v = can_discriminate(pool)
        rankable = {"ok": v.ok, "reason": v.reason,
                    "dimensions": list(v.dimensions or ()), "spread": v.spread}
        if v.ok:
            try:
                scored = score_pool(pool, pool_id=f"compare:{len(pool)}")
                ranked = [{"term": s.key, "score": round(s.score, 4),
                           "confidence": round(s.confidence, 3),
                           "missing": list(s.missing),
                           "explain": explain(s)} for s in scored]
            except PoolTooSmall as e:
                rankable["reason"] = f"{rankable['reason']} — but {e}"
    else:
        rankable = {"ok": False, "dimensions": [], "spread": None,
                    "reason": f"only {len(pool)} term(s) came back measured; below "
                              f"{MIN_POOL_SIZE} a percentile carries no information"}

    return _ok({
        "mode": mode, "terms": wanted, "rows": rows,
        "ranked": ranked,
        "rankable": rankable,
        "coverage": coverage,
        "spent": {"private_requests_upper_bound": spent,
                  "basis": "bound — results-data caches 7 days and chart-series 30, "
                           "so a repeat costs nothing and the true count may be 0"},
        "floors": {
            "min_pool_to_score": MIN_POOL_SIZE,
            "min_pool_for_intent": MIN_POOL_FOR_INTENT,
            "measured_terms": len(measured),
            "terms_with_usable_cvr": len(cvrs),
            "terms_with_cvr_zero": len(zero_cvrs),
            "cvr_reference_median": pool_median,
            "intent_state": (
                "not_checked — cheap mode carries no CVR at any price; re-run with "
                "mode=full to judge whether these searchers buy"
                if mode == "cheap" else
                f"judged against the median of {len(cvrs)} measured CVRs"
                if pool_median else
                f"NOT judged — only {len(cvrs)} term(s) carry a usable CVR "
                f"(under {MIN_POOL_FOR_INTENT})"
                + (f", and {len(zero_cvrs)} returned exactly 0, which is a reporting "
                   f"floor rather than a measured rate and is excluded" if zero_cvrs
                   else "")
                + ". There is no reference, so the gate refuses rather than ranking "
                  "against noise. Add more terms to the batch to build one."),
        },
        # Every row is a valid drill target, and the drill returns rows of this
        # same shape. That is the loop the operator asked for: compare a list,
        # take any row, get its sub-niches ranked, take any of THOSE, repeat.
        "drill_next": "Any `term` in `rows` can be opened into its SUB-NICHES with "
                      "keyword_crawl(operation='drill', seed=<term>). That returns "
                      "rows in this same shape, each drillable again — including "
                      "the walls, whose children are sometimes not walls.",
        "note": "Sorted by demand-per-listing (D-31), never volume. The headline "
                "`verdict` is the WORSE of the gates, not an average. `ranked` is "
                "null when the dimensions cannot separate the pool — a real answer "
                "(N-01), not a failure. cvr is RELATIVE only: compare it between "
                "these terms, never read it as orders (D-43). "
                "`volume` is a ~30-DAY figure in BOTH modes so the ratio means the "
                "same thing either way — read `volume_basis`. In cheap mode "
                "`volume_annual` is the 12-month total and must NEVER be divided by "
                "`supply`, which is a point-in-time count.",
    })

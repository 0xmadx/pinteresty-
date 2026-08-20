"""MCP surface for this project — one tool per question the operator asks.

    .venv/Scripts/python.exe -m mcp_server.server

Register it with Claude Code / Antigravity / any MCP client (see docs/MCP.md).

DESIGN RULES, in the order they matter
--------------------------------------

**1. Read only.** No tool here lists a product, edits a shop, places an order, or
writes to Etsy or Printify. The token in .env carries products.write and
orders.write; nothing below touches them. An agent that can spend money or
publish on the operator's behalf is a different product with a different risk
profile, and this is not it.

**2. Every number carries its provenance.** Values come back with `basis`
(measured / derived / bound / unmeasured / provisional) attached, because the
consumer is a language model that will otherwise present a bound as a fact. This
is the single most important property of this surface.

**3. Refusals are results.** A tool that cannot answer returns
`{"error": ..., "fix": ...}` and never a plausible zero. `PoolTooSmall`,
`SessionDown`, an untrusted filter and an unconfirmed fee schedule are all
answers, and each names what would resolve it.

**4. The vault is checked before anything live.** An empty session pool does not
fail — it HANGS, in an unbounded sleep loop. A tool call that never returns is
the worst failure mode for an agent, so `preflight` gates every live tool.

**5. One tool per question, not one per module.** `analyze_keyword` answers "is
there room here", which internally touches four modules. An agent should not have
to know this codebase's file layout to use it.
"""
import functools
import json
import os
import traceback

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="etsy-market-intel",
    instructions=(
        "Market intelligence for one Etsy seller, joining Etsy Private (demand), "
        "Etsy Public (supply) and Pinterest (momentum).\n\n"
        "READ THE `basis` FIELD ON EVERY NUMBER AND REPORT IT. `measured` is a "
        "fact; `derived` is computed from facts; `bound` is an upper limit and must "
        "never be restated as a rate; `unmeasured` means nobody looked, which is NOT "
        "zero; `provisional` means the operator has not confirmed the fee/cost inputs "
        "so the verdict may move.\n\n"
        "Rank opportunities by demand-per-listing, never by search volume — a term "
        "with 2M listings is a wall, not an opportunity.\n\n"
        "Every tool is read-only. Nothing here can list a product or spend money; if "
        "asked to, say so and hand the step back to the operator."
    ),
)


# --- plumbing ---------------------------------------------------------------------------

def _ok(payload, **meta):
    return {"ok": True, **meta, **payload}


def _fail(error, fix=None, **meta):
    """A refusal is a result. It always says what would resolve it."""
    return {"ok": False, "error": str(error), "fix": fix, **meta}


def _guarded(fn):
    """Turn any exception into a structured refusal rather than a protocol error.

    functools.wraps is load-bearing, not tidiness. MCP builds each tool's input
    schema by inspecting the callable's signature, and a bare `*a, **kw` wrapper
    publishes a schema demanding two required arguments called `a` and `kw`. Every
    tool then registers cleanly and fails on every actual call — which an
    in-process `list_tools()` check cannot see, and only a real stdio round trip
    catches. `wraps` sets __wrapped__, which inspect.signature follows back to the
    true parameters.
    """
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            return _fail(f"{type(e).__name__}: {e}",
                         fix="See traceback in `detail`; most failures here are a "
                             "stale session vault or a missing config value.",
                         detail=traceback.format_exc()[-1200:])
    return wrapper


def _preflight(platforms=("etsy",)):
    """Refuse fast when the session pool is empty. It HANGS otherwise, not fails.

    Uses vault_status.scan(), which never blocks. RedisCookieVault.get_valid_account()
    is the wrong call here: it sleeps in an unbounded loop waiting for the Chrome
    extension, which from an agent's side is a tool that simply never returns.
    """
    from core import vault_status as vs
    try:
        report = vs.scan(tuple(platforms))
    except Exception as e:
        return _fail(f"cannot reach the session vault: {e}",
                     fix="Is the Docker Redis container running? Note that two Redis "
                         "servers share port 6379 on this machine (D-30) — `localhost` "
                         "reaches a stale native one. Check: python -m core.vault_status")
    missing = [p for p in platforms if not report.get(p, {}).get("usable")]
    if missing:
        return _fail(
            f"no valid sessions for: {', '.join(missing)}",
            fix="Open Chrome with the extension signed in to Etsy/Pinterest so it "
                "re-posts cookies to the Go cookie server, then retry. Check with: "
                "python -m core.vault_status. An empty pool makes live calls hang, "
                "so this refuses up front instead.")
    return None


# --- health -------------------------------------------------------------------------------

@mcp.tool()
@_guarded
def vault_status() -> dict:
    """Can this system make live calls right now? Check FIRST, before any live tool.

    An empty session pool does not raise — it sleeps forever waiting for the Chrome
    extension. Every live tool here gates on this, but calling it first turns a
    mysterious refusal into a clear one.
    """
    from core import vault_status as vs
    try:
        report = vs.scan()
    except Exception as e:
        return _fail(f"cannot reach the session vault: {e}",
                     fix="Is the Docker Redis container running? Two Redis servers "
                         "share port 6379 here (D-30); `localhost` reaches a stale "
                         "native one. Check: python -m core.vault_status")
    per_platform = {p: {"usable": len(r["usable"]), "known": len(r["profiles"])}
                    for p, r in report.items()}
    return _ok({"sessions": per_platform,
                "ready": bool(per_platform.get("etsy", {}).get("usable")),
                "note": "etsy = public scraping. etsy_private = the operator's OWN "
                        "seller account; never used to ask about a competitor. "
                        "usable < known means profiles are present but stale or "
                        "signed out."})


@mcp.tool()
@_guarded
def run_health(limit: int = 10) -> dict:
    """Did the scheduled jobs actually run? Job status, last success, and staleness.

    The system's value compounds only if the clock keeps running. This is where a
    silently dead scheduler becomes visible.
    """
    from core.scheduler import Scheduler, default_jobs
    sched = Scheduler(default_jobs())
    jobs = []
    for job in sched.jobs.values():
        last = sched.last_success(job.name)
        jobs.append({"job": job.name, "every_hours": job.every_hours,
                     "last_success": last.isoformat() if last else None,
                     "due_now": job in sched.due(),
                     "basis": "measured" if last else "unmeasured",
                     "description": job.description})
    return _ok({"jobs": jobs,
                "note": "last_success=None means this reading has NEVER been taken. "
                        "History cannot be backfilled."})


# --- opportunity ----------------------------------------------------------------------------

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


# --- economics --------------------------------------------------------------------------------

@mcp.tool()
@_guarded
def profit_verdict(price: float, product_type: str, cogs: float = 0.0,
                   shipping_cost: float = 0.0, shipping_charged: float = 0.0,
                   labor_minutes: float = 0.0,
                   demand_units_per_week: int = 0) -> dict:
    """Go / no-go on one unit, with the reason it failed.

    Two independent ways to fail, and the second is the one sellers miss: MARGIN
    (the unit does not clear its type's floor) and CAPACITY (the margin is fine but
    the operator physically cannot make enough per week). `product_type` is one of
    digital / physical / personalized and decides which floor applies.
    """
    from etsy.analytics import profit
    from core.settings_store import load
    settings = load()

    v = profit.verdict(price, product_type, demand_units_per_week=demand_units_per_week,
                       cogs=cogs, shipping_cost=shipping_cost,
                       shipping_charged=shipping_charged, labor_minutes=labor_minutes)
    confirmed = bool(getattr(settings, "confirmed", None))
    return _ok({
        "verdict": v,
        "basis": "derived" if confirmed else "provisional",
        "provisional_reason": None if confirmed else
            "the operator has not confirmed the fee schedule / COGS / hourly rate in "
            "config/settings.json, so every figure here may move. Confirm with: "
            "python -m core.settings_store confirm",
    })


@mcp.tool()
@_guarded
def price_and_cost_ladder(product_type: str, prices: list[float] = None,
                          shipping_cost: float = 0.0,
                          labor_minutes: float = 0.0) -> dict:
    """At each price, the most a unit may cost to make and still clear the floor.

    Turns a rejection into a negotiation. When a market pays $16.60 and the answer
    is "impossible at any supplier price", that is a fact about the market, not
    about the supplier — and this is where it becomes visible.
    """
    from etsy.analytics import pod_costing
    prices = prices or [10.0, 16.0, 25.0, 35.0, 50.0, 75.0]
    ladder = pod_costing.cogs_ladder(prices, product_type,
                                     shipping_cost=shipping_cost,
                                     labor_minutes=labor_minutes)
    return _ok({
        "product_type": product_type,
        "ladder": [{"price": p,
                    "max_cogs": c,
                    "possible": c is not None,
                    "basis": "derived"} for p, c in ladder],
        "note": "max_cogs=null means NO supplier price clears the floor at that "
                "price — fees plus labour already exceed it.",
    })


@mcp.tool()
@_guarded
def pod_quote(term: str, market: str = "US", limit: int = 6) -> dict:
    """What would Printify charge to make this, and could it ship fast enough?

    PRODUCTION COST IS NOT AVAILABLE from Printify's catalog — there is no price on
    a catalog variant, and the Premium discount cannot be read. `cogs` comes back
    null and must be confirmed by the operator from the Printify UI. Shipping cost
    and handling time ARE available, and handling is usually the deciding number:
    a 10-day handling floor closes Etsy's 7-day delivery bracket outright.
    """
    from etsy.analytics import pod_costing
    from etsy.api.printify.client import PrintifyClient, PrintifyError
    try:
        client = PrintifyClient()
    except PrintifyError as e:
        return _fail(e, fix="Set PRINTIFY_API_TOKEN in .env")

    options = pod_costing.find_options(client, term, market=market, limit=limit)
    return _ok({
        "term": term,
        "options": [{"blueprint_id": o.blueprint_id, "blueprint": o.blueprint_title,
                     "provider_id": o.provider_id, "provider": o.provider_title,
                     "variants": o.variants,
                     "shipping_first_item": o.ship_first_item,
                     "shipping_additional": o.ship_additional,
                     "handling_days": o.handling_days,
                     "lead_days": o.lead_days,
                     "can_ship_fast": o.can_ship_fast,
                     "cogs": None,
                     "notes": list(o.notes),
                     "basis": "measured (shipping, handling); cogs UNMEASURED — "
                              "not exposed by the catalog API"}
                    for o in options],
        "note": "cogs is null for every option by design. Do not estimate it; ask "
                "the operator to read it from Printify.",
    })


# --- learning ------------------------------------------------------------------------------------

@mcp.tool()
@_guarded
def learn_status() -> dict:
    """Did the system's past predictions come true?

    Reports and refuses to tune. Below 10 launches, or with no deliberately
    low-scored control, it says why calibration is blocked rather than producing a
    confident model of noise.
    """
    from etsy.analytics import learn
    state = learn.report()
    return _ok({"launches": state["launches"], "measured": state["measured"],
                "unmeasured": state["unmeasured"],
                "calibration": state["calibration"],
                "findings": learn.read(state),
                "basis": "measured" if state["measured"] else "unmeasured"})


@mcp.tool()
@_guarded
def tracked_shops() -> dict:
    """Which competitor shops are being tracked, and what the daily delta shows.

    A shop delta is the only MEASURED sales number this system has — it is the
    difference between two counters, so it needs two readings a day apart and
    cannot be backfilled.
    """
    from core.database import MarketDatabase
    from core.settings_store import load
    db = MarketDatabase()
    shops = load().shop_names()
    out = []
    for shop in shops:
        history = db.get_shop_history(shop)
        rate = db.latest_shop_rate(shop)
        latest = history[-1] if history else None
        out.append({
            "shop": shop,
            "readings": len(history),
            "first_seen": history[0]["collected_at"] if history else None,
            "last_seen": latest["collected_at"] if latest else None,
            "total_sales": latest.get("total_sales") if latest else None,
            "sales_per_day": {
                "value": rate,
                # None is the honest answer, and it is NOT 0.0 — a shop with one
                # reading, or one whose counter is too coarse to resolve the window,
                # has an unknown rate rather than a rate of zero.
                "basis": "measured" if rate is not None else "unmeasured"},
            "sales_per_day_upper_bound": {
                "value": latest.get("sales_per_day_upper") if latest else None,
                "informative": MarketDatabase.bound_is_informative(
                    (latest or {}).get("window_days")),
                "basis": "bound",
                "note": "Etsy's counter is quantised at scale. When it does not move, "
                        "this is the MOST the shop can have sold per day — never "
                        "restate it as a rate."},
            "counter_resolution": latest.get("counter_resolution") if latest else None,
            "reading_basis": latest.get("basis") if latest else None,
            "delta_available": len(history) > 1,
            "basis": "measured" if len(history) > 1 else
                     "insufficient — a delta is the difference between two readings "
                     "and cannot be backfilled"})
    return _ok({"shops": out,
                "warning": "Tracking only high-performing shops teaches what winners "
                           "do, not what works (B-01). Include a shop in the low "
                           "hundreds of sales so failures are visible too."})


# --- settings ----------------------------------------------------------------------------------

@mcp.tool()
@_guarded
def settings_summary() -> dict:
    """The operator's fee schedule, cost assumptions and margin floors.

    `confirmed` is the field that matters: while it is empty, EVERY profit verdict
    this system produces is provisional, because the fee and cost inputs are
    defaults rather than the operator's real numbers.
    """
    path = os.path.join("config", "settings.json")
    if not os.path.exists(path):
        return _fail("config/settings.json is missing",
                     fix="python -m core.settings_store init")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    confirmed = raw.get("confirmed") or []
    return _ok({"settings": raw, "confirmed": confirmed,
                "all_verdicts_provisional": not confirmed,
                "note": "Nothing confirmed means every margin and capacity figure "
                        "rests on defaults, not on this operator's real costs."})


@mcp.tool()
@_guarded
def verdict_history(subject: str) -> dict:
    """Has this verdict changed, and which inputs moved underneath it?

    "It changed from watch to list-now" is not actionable; "supply grew 40% while
    volume held" is. Reports what moved and by how much, ranked by relative change,
    and explicitly does NOT attribute cause — several inputs usually move together
    and nothing here can isolate them.

    An input that was measured before and is unmeasured now comes back as
    `became_unmeasured`, never as a fall to zero: a scraper that broke overnight
    looks exactly like a market that collapsed.
    """
    from etsy.analytics import verdict_log
    state = verdict_log.explain(subject)
    return _ok({"state": state, "findings": verdict_log.read(state),
                "basis": "measured" if state.get("readings") else "unmeasured"})


@mcp.tool()
@_guarded
def calendar(lead_weeks: int = 6, product_type: str = "personalized",
             country: str = "US") -> dict:
    """What should be listed, and by when? The front door.

    Joins Pinterest takeoff dates to Etsy demand: each dated moment gets a list-by
    deadline (takeoff minus `lead_weeks`) and the watched terms that belong to it,
    each with volume, supply and demand-per-listing.

    Read `is_wall` before recommending anything. A term can clear the margin gate
    and still be unrankable — "christmas ornament" is 25,477 searches against
    1,405,731 listings, profitable and impossible. Rank by demand_per_listing,
    never by volume.

    `state` is list_now / list_by / watching / untimed / passed. `untimed` means the
    deadline has passed and no peak was measured, so late cannot be told from
    missed — report it as unknown, never as an opportunity.
    """
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
                 "profit verdicts are provisional until settings are confirmed",
        "note": "A moment with no terms is dated but has nothing aimed at it — that "
                "is 'we have not looked', not 'no opportunity'.",
    })


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

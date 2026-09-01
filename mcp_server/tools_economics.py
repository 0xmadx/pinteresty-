"""Does it pay? Margin, capacity, and what a unit may cost to make.

Split out of the single 699-line `server.py` (D-53). Registration happens
on import — `server.py` imports this module for that side effect alone.
Every tool here follows the same contract: `@mcp.tool()` outermost,
`@_guarded` innermost, `_preflight` first if it touches the network, and
`_ok`/`_fail` with a per-field `basis` on the way out.
"""
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp


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
    # settings.basis() is the accessor; there is no `.confirmed` attribute, and a
    # getattr for one returns None forever — reporting every verdict provisional
    # even after the operator confirms the inputs.
    confirmed = settings.basis()["basis"] == "operator"
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

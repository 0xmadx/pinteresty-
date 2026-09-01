"""Did it work? Outcomes, competitor movement, and verdict drift.

Split out of the single 699-line `server.py` (D-53). Registration happens
on import — `server.py` imports this module for that side effect alone.
Every tool here follows the same contract: `@mcp.tool()` outermost,
`@_guarded` innermost, `_preflight` first if it touches the network, and
`_ok`/`_fail` with a per-field `basis` on the way out.
"""
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp


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

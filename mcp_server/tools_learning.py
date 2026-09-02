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
    """Has this verdict changed, and which inputs moved under it? "Supply grew 40%
    while volume held" is actionable; "watch → list-now" is not. Ranks what moved,
    and does NOT attribute cause — inputs move together and nothing here isolates
    them. An input measured before and unmeasured now returns `became_unmeasured`,
    never a fall to zero: a broken scraper looks exactly like a collapsed market."""
    from etsy.analytics import verdict_log
    state = verdict_log.explain(subject)
    return _ok({"state": state, "findings": verdict_log.read(state),
                "basis": "measured" if state.get("readings") else "unmeasured"})


# ⚠️ THE FIRST WRITE TOOL ON THIS SURFACE. Everything else here reads; this one
# inserts a row into `launches`, and the server instructions were corrected in the
# same commit because they claimed "every tool is read-only" — which stopped being
# true the moment this shipped. A false self-description is exactly the class of
# wrong-but-plausible statement this project exists to prevent.
#
# It is still safe in the sense that matters: it touches nothing outside our own
# SQLite, spends no money, and cannot list a product on Etsy. It records that the
# operator ALREADY did.
#
# Why it had to exist: `learn.py` needs 10 launches, `rank_tracker.py:85` starts
# with `db.get_launches()` and so `rank_check` has returned [] on every scheduled
# run for weeks, and MCP is the only interface (D-52). The one write that unblocks
# the entire DID-IT-WORK half of the goal was CLI-only.
@mcp.tool()
@_guarded
def record_launch(listing_id: str, term: str, predicted_score: float | None = None,
                  predicted_profit: float | None = None,
                  product_type: str | None = None, is_control: bool = False,
                  notes: str | None = None) -> dict:
    """WRITES. Record a listing the operator has ALREADY published, with what we predicted.

    The only write on this surface. It cannot list anything on Etsy or spend money —
    it records a launch that already happened, which is what turns every verdict
    from an untested prediction into something that can be graded.

    is_control=True marks a DELIBERATE mid/low-scored launch. Without controls the
    loop only ever sees the model's own picks: it can measure precision and never
    recall, and can never learn it was wrong to REJECT a niche (B-04). Target ~10%.
    """
    if not listing_id or not str(listing_id).strip():
        return _fail("`listing_id` is required",
                     fix="The numeric id from the Etsy listing URL, e.g. 1864690497.")
    if not term or not term.strip():
        return _fail("`term` is required",
                     fix="The keyword this listing was launched FOR — it is the join "
                         "key to the prediction, so a wrong one is worse than none.")

    from etsy.analytics.launch import record_result
    out = record_result(term.strip(), str(listing_id).strip(),
                        score=predicted_score, profit=predicted_profit,
                        product_type=product_type, is_control=is_control, notes=notes)
    return _ok({"operation": "record_launch", **out,
                "wrote": "graph.db → launches (INSERT OR IGNORE, so re-recording the "
                         "same listing is a no-op rather than a duplicate)"})

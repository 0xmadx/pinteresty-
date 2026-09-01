"""Pinterest research — the composed layer above the raw client.

`pinterest/products/` is 8 standalone modules with their own CLI and 54 live
checks, and it was invisible to an agent until now. This is the half aimed at
the operator's actual problem: *searching large data* and *finding winning
products*, rather than fetching one number.

WHAT THIS WRAPS AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Each module ships a `report()` function. **None of them is wrapped here.** They
construct their own client (hitting the 120-second empty-vault wait directly),
print tables to stdout, and return `None` or duplicate data. The underlying
functions are wrapped instead.

Writers are excluded outright: `history.backfill`, `content_calendar.to_ics`,
`moodboard.to_html`, `alerts.report(refresh=True)`. This surface is read-only.

COST IS DECLARED, BECAUSE SOME OF THIS IS EXPENSIVE
---------------------------------------------------
`expand` at depth 1 is the best value in the whole system — **2 requests, zero
`/metrics/` calls**, because the series ride inside the two expansion responses.
`sweep` across all 24 interests is **24 requests** and, at the client's built-in
0.6s pacing, ~15 seconds of wall clock before Pinterest's own latency. Both
numbers are in the operation description so an agent can choose knowingly.
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import ResearchOp
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp

_NEEDS_SEED = {"expand", "long_tail", "neighbours"}
_NEEDS_CATEGORY = {"merchant_share"}
_LOCAL_ONLY = {"alerts", "history"}          # read history.db, no network

_OP_DOC = (
    "expand: seed -> long-tail + co-searched neighbours. 2 REQUESTS, zero /metrics/ "
    "— the best value here; depth stays 1 (depth 2 costs ~32). "
    "long_tail/neighbours: one half of expand each, 1 request. "
    "sweep: the discovery table across interests — 24 REQUESTS, ~15s; "
    "set interests to narrow it. "
    "audience: age+gender for terms, WITH the batch-relative skew that is the actual "
    "finding. merchant_share: who owns a category's clicks. "
    "demand_table: every category's growth + intent ratio in ONE request. "
    "classify/taxonomy_search: turn free text into category ids. "
    "alerts/history: week-over-week movement from the local archive, no network."
)


def _client():
    """Only after preflight — construction busy-waits 120s on an empty vault."""
    from pinterest.endpoints.api import PinterestTrendsAPI
    return PinterestTrendsAPI(store=False)


@mcp.tool()
@_guarded
def pinterest_research(
    operation: Annotated[ResearchOp, Field(description=_OP_DOC)],
    seed: str | None = None,
    terms: str | None = None,
    region: str = "US",
    preset: str = "growing",
    interests: str | None = None,
    category_id: str | None = None,
    event: str = "OUTBOUND_CLICK",
    limit: int = 100,
    weeks: int = 12,
) -> dict:
    """Composed Pinterest research: expansion, audience skew, merchant share, movement."""
    if operation in _NEEDS_SEED and not seed:
        return _fail(f"operation '{operation}' needs `seed`",
                     fix="Pass seed='halloween nails' — one term to expand from.")
    if operation in _NEEDS_CATEGORY and not category_id:
        return _fail(f"operation '{operation}' needs `category_id`",
                     fix="Get one from pinterest(operation='categories') or "
                         "pinterest_research(operation='classify', terms='...').")
    if operation == "audience" and not terms:
        return _fail("operation 'audience' needs `terms`",
                     fix="Pass a COMMA-SEPARATED LIST, not one term — the skew that "
                         "makes this useful is measured against the batch median, so "
                         "a single term has nothing to be distinctive against.")

    # The archive operations touch no network, so they must not be gated on a
    # Pinterest session the caller does not need.
    if operation not in _LOCAL_ONLY:
        blocked = _preflight(("pinterest",))
        if blocked:
            return blocked

    if operation in _LOCAL_ONLY:
        return _archive(operation, region, preset, weeks, terms)

    api = _client()
    try:
        return _dispatch(api, operation, seed, terms, region, preset,
                         interests, category_id, event, limit)
    finally:
        api.close()


def _archive(operation, region, preset, weeks, terms):
    """alerts + history — local sqlite, no network, no session needed."""
    from pinterest.products import alerts, history

    db = history.HistoryDB()
    archived = db.weeks(country=region, preset=preset)
    common = {"operation": operation, "region": region, "preset": preset,
              "weeks_archived": len(archived)}

    if operation == "history":
        if terms:
            return _ok({**common,
                        "rank_history": {t.strip(): db.rank_history(
                            t.strip(), country=region, preset=preset)
                            for t in terms.split(",") if t.strip()},
                        "basis": "measured — rank over time, a series Pinterest "
                                 "itself cannot return (its /metrics/ gives volume, "
                                 "never rank)"})
        return _ok({**common, "weeks": archived,
                    "longevity": db.longevity(country=region, preset=preset),
                    "stats": db.stats(),
                    "basis": "measured",
                    "note": "longevity separates a real trend from a one-week spike "
                            "— a term holds the growing table ~1.4 weeks on average."})

    events = alerts.latest_diff(db, country=region, preset=preset)
    payload = {**common, "events": events, "count": len(events),
               "basis": "measured (week-over-week movement in the local archive)"}
    if len(archived) < 2:
        # [] here would read as "nothing moved", which is a different claim.
        payload["finding"] = (
            f"Only {len(archived)} week(s) archived — a diff needs two. This is "
            f"'not enough history yet', NOT 'nothing changed'. The archive is "
            f"filled by the scheduler, and cannot be backfilled retroactively "
            f"beyond what Pinterest still serves.")
    return _ok(payload)


def _dispatch(api, operation, seed, terms, region, preset, interests,
              category_id, event, limit):
    from pinterest.products import audience, keyword_research, market_intel

    common = {"operation": operation, "region": region}
    ilist = [i.strip() for i in interests.split(",")] if interests else None
    tlist = [t.strip() for t in terms.split(",") if t.strip()] if terms else []

    if operation == "expand":
        rows = keyword_research.expand(api, seed, country=region, depth=1)
        return _ok({**common, "seed": seed, "terms": rows, "count": len(rows),
                    "requests_spent": 2,
                    "basis": "measured; each term's series rode along free inside "
                             "the two expansion responses — zero /metrics/ calls",
                    "note": "`noisy: true` marks a series whose last 8 weeks never "
                            "exceed 25 on the 0-100 scale — its velocity is an "
                            "artefact of rounding near zero, not a real move."})

    if operation in ("long_tail", "neighbours"):
        rows = (keyword_research.long_tail(api, seed, country=region)
                if operation == "long_tail"
                else keyword_research.neighbours(api, seed, country=region))
        return _ok({**common, "seed": seed, "terms": rows, "count": len(rows),
                    "requests_spent": 1,
                    "basis": "measured; series ride along free"})

    if operation == "sweep":
        rows = keyword_research.sweep(api, preset=preset, interests=ilist,
                                      country=region, limit=min(limit, 100))
        cross = keyword_research.cross_interest(rows)
        return _ok({**common, "preset": preset,
                    "terms": rows, "count": len(rows),
                    "cross_interest": {k: v for k, v in list(cross.items())[:50]},
                    "cross_interest_count": len(cross),
                    "requests_spent": len(ilist) if ilist else 24,
                    "basis": "measured, RELATIVE per response",
                    "note": "cross_interest lists terms ranking in MORE THAN ONE "
                            "interest — invisible from any single table, and usually "
                            "the broadest demand. The limit is a ceiling, not a "
                            "promise: interests differ wildly in how many terms they "
                            "return."})

    if operation == "audience":
        rows = audience.profile(api, tlist, country=region)
        # skew() mutates its input in place and returns it; the mutation IS the
        # enrichment, but copy first so the caller's rows are not surprising.
        enriched = audience.skew([dict(r) for r in rows])
        ages, genders = audience.baseline(rows)
        return _ok({**common, "terms": enriched, "count": len(enriched),
                    "baseline": {"age": ages, "gender": genders},
                    "basis": "measured",
                    "note": "Read `age_skew` and `most_distinctive`, not the raw "
                            "shares. Gender is near-flat across Pinterest (~90% "
                            "female almost everywhere), so AGE carries the signal. "
                            "Shares are rounded server-side and sum to 1.00-1.15 — "
                            "not exact percentages. The baseline is this batch's "
                            "MEDIAN, so skew is relative to what you asked for."})

    if operation == "merchant_share":
        data = market_intel.merchant_share(api, category_id, country=region,
                                           event=event)
        return _ok({**common, "category_id": category_id, "event": event,
                    **(data or {}), "basis": "measured (share of the ranked pins)",
                    "note": "Only OUTBOUND_CLICK returns rows; SAVE and ENGAGEMENT "
                            "come back empty. Merchant names are exact strings — "
                            "match 'Etsy' exactly, never as a prefix."})

    if operation == "demand_table":
        rows = market_intel.demand_table(api, country=region, event=event)
        return _ok({**common, "event": event, "categories": rows,
                    "count": len(rows), "requests_spent": 1,
                    "basis": "measured, RELATIVE",
                    "note": "intent_ratio is click-growth over save-growth from the "
                            "SAME response — the buyer-vs-dreamer signal for free. "
                            "None means saves were flat, i.e. undefined, not "
                            "infinite."})

    if operation in ("classify", "taxonomy_search"):
        tax = market_intel.Taxonomy(api, country=region)
        if operation == "classify":
            hits = tax.classify(terms or seed or "", top=10)
        else:
            hits = [{"category_id": cid, "name": name, "path": tax.path(cid)}
                    for cid, name in tax.search(terms or seed or "")][:25]
        return _ok({**common, "query": terms or seed, "matches": hits,
                    "count": len(hits), "requests_spent": 1,
                    "basis": "derived (name matching over Pinterest's own taxonomy)",
                    "note": "These ids feed pinterest(operation='category_*'). The "
                            "14 level-1 verticals are NOT in the taxonomy map and "
                            "are a 400 if passed as a category_id."})

    return _fail(f"unknown operation: {operation}")

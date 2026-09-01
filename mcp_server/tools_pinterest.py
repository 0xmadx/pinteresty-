"""Pinterest — the audience and timing layer. Zero MCP coverage until now.

Pinterest is ~97 public callables across three layers and was reachable from an
agent only as a side effect of `calendar`/`cockpit` reading rows a scheduler job
had written days earlier. This is the live surface.

One grouped tool rather than fifteen: measured on this SDK, grouping is ~64%
cheaper in published schema, and the saving is not the enum — it is not paying
the ~380-char per-tool envelope fifteen times.

THREE HAZARDS THIS MODULE EXISTS TO CONTAIN
-------------------------------------------
**1. Construction is the dangerous part, not the call.**
`PinterestTrendsAPI.__init__` draws a session, and on an empty vault that is a
bounded **120-second busy-wait** that then raises. `_preflight` must therefore run
BEFORE the constructor, not before the request — which is why every operation
here goes through `_client()`.

**2. `store=True` makes the same call return two different SHAPES.** With the
SeriesStore active, `metrics()` returns wire rows (with `date`, `normalizedCount`,
prediction bounds) or locally-served rows (only `count`) depending on what the
store happens to hold. Constructed with `store=False`, and normalised on the way
out regardless.

**3. Everything prints.** Handled centrally by `_guarded`, which redirects stdout
to stderr — the server speaks JSON-RPC over stdout and a stray print kills the
connection. Do not add a tool here that bypasses `_guarded`.
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import PinterestOp, normalise_series
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp

# Operations that need no `term`/`category_id` — used to give a precise refusal
# instead of a confusing empty result.
_NEEDS_TERM = {"metrics", "related", "prefix", "demographics", "moment_curve"}
_NEEDS_CATEGORY = {"category_metrics", "category_demographics", "top_products",
                   "etsy_competitors"}

_OP_DOC = (
    "top_trends: rising keywords (no term; use preset). "
    "metrics: weekly demand curve for term(s). "
    "related/prefix: expand a term — series ride along FREE, best value here. "
    "demographics: age+gender for term(s). "
    "moments: seasonal takeoff/peak DATES. "
    "moment_curve: a moment's curve — the ONLY sub-weekly series in this API. "
    "categories: the 383-node taxonomy. category_top: trending categories. "
    "category_metrics/category_demographics/top_products/etsy_competitors: need category_id. "
    "featured: 5 curated topics. editorial: written trend stories (US/CA/GB+IE only). "
    "Terms accept a comma-separated list where the endpoint batches."
)


def _client():
    """Construct only AFTER preflight — see hazard 1 in the module docstring."""
    from pinterest.endpoints.api import PinterestTrendsAPI
    # store=False: no SeriesStore writes, and no two-shapes hazard (2).
    return PinterestTrendsAPI(store=False)


def _terms(term):
    return [t.strip() for t in str(term).split(",") if t.strip()]


@mcp.tool()
@_guarded
def pinterest(
    operation: Annotated[PinterestOp, Field(description=_OP_DOC)],
    term: str | None = None,
    region: str = "US",
    preset: str = "growing",
    limit: int = 50,
    days: int = 365,
    category_id: str | None = None,
    event: str = "OUTBOUND_CLICK",
) -> dict:
    """Pinterest audience and timing, live. Everything is 0-100 RELATIVE, never absolute."""
    if operation in _NEEDS_TERM and not term:
        return _fail(f"operation '{operation}' needs `term`",
                     fix="Pass term='mom necklace' (or a comma-separated list "
                         "for the batching operations: metrics, demographics).")
    if operation in _NEEDS_CATEGORY and not category_id:
        return _fail(f"operation '{operation}' needs `category_id`",
                     fix="Get one from operation='categories' (the taxonomy) or "
                         "operation='category_top' (the ranked table).")

    blocked = _preflight(("pinterest",))
    if blocked:
        return blocked

    api = _client()
    try:
        return _dispatch(api, operation, term, region, preset, limit, days,
                         category_id, event)
    finally:
        api.close()


def _dispatch(api, operation, term, region, preset, limit, days, category_id, event):
    common = {"operation": operation, "region": region}

    if operation == "top_trends":
        rows = api.top_trends(preset=preset, country=region, limit=min(limit, 100))
        values = (rows or {}).get("values") or []
        return _ok({
            **common, "preset": preset, "terms": values, "count": len(values),
            "basis": "measured, RELATIVE — searchCount/normalizedCount are scaled to "
                     "100 within this response and are never absolute volume",
            "note": "Only 'growing' and 'seasonal' are velocity-sorted; 'top_monthly' "
                    "and 'top_yearly' are volume-sorted, so row order is NOT momentum "
                    "order there. A *_change of 100.01 is Pinterest's '10,000%+' "
                    "display cap, not a real move.",
        })

    if operation == "metrics":
        rows = api.metrics(_terms(term), days=days, country=region) or []
        return _ok({
            **common, "days": days,
            "series": [{"term": r.get("term"),
                        "growth_rates": r.get("growth_rates") or {},
                        **normalise_series(r.get("counts"))} for r in rows],
            "requested": len(_terms(term)), "returned": len(rows),
            "note": "Pinterest DROPS terms it does not track — requested > returned "
                    "means absent, which is not the same as zero (N-02). "
                    "growth_rates come off the wire and cannot be recomputed from "
                    "the rounded counts.",
        })

    if operation in ("related", "prefix"):
        rows = (api.related_terms(term, country=region) if operation == "related"
                else api.prefix_match(term, country=region)) or []
        return _ok({
            **common, "seed": term,
            "terms": [{"term": r.get("term"),
                       "has_prediction": r.get("hasPrediction"),
                       **normalise_series(r.get("counts"))} for r in rows],
            "count": len(rows),
            "basis": "measured; each term's full series rides along free in this "
                     "one request — no follow-up /metrics/ call needed",
        })

    if operation == "demographics":
        data = api.demographics(_terms(term), country=region) or {}
        dist = data.get("term_distributions") or {}
        return _ok({
            **common, "terms": dist, "count": len(dist),
            "basis": "measured",
            "note": "Shares are rounded server-side, so the seven age bands sum to "
                    "1.00-1.15 rather than exactly 1 — do not present them as exact "
                    "percentages. Gender is near-flat (~90% female) across most "
                    "terms; AGE is where the signal is.",
        })

    if operation == "moments":
        rows = api.moments_calendar(country=region) or []
        dated = [m for m in rows if m.get("takeoff_ms")]
        return _ok({
            **common, "moments": rows, "count": len(rows), "dated": len(dated),
            "basis": "measured where takeoff_ms is present",
            "note": "Date coverage is PER REGION. Single-country codes carry full "
                    "dates; grouped codes (GB+IE, NL+BE+LU, SE+DK+FI+NO) return names "
                    "with every date field null; JP is empty; AU/NL/IE/GB 400. A null "
                    "date is 'this region has no ramp data', not 'no moment'. This is "
                    "also the authoritative vocabulary for moment filters elsewhere.",
        })

    if operation == "moment_curve":
        rows = api.moment_metrics(_terms(term), country=region,
                                  aggregation="weekly", lookback_days=min(days, 730),
                                  predicted_days=91) or []
        return _ok({
            **common, "moments": rows, "count": len(rows),
            "note": "THE ONLY SUB-WEEKLY SERIES IN THIS API (pass daily via the "
                    "client for day resolution). Points are ascending — the wire "
                    "returns them NEWEST-FIRST and they are reversed here. `peaks` is "
                    "forward-looking while most of the curve is history: read the "
                    "DATE from peaks and the HEIGHT from is_forecast points.",
        })

    if operation == "categories":
        cats = api.product_categories(country=region) or {}
        return _ok({
            **common, "categories": cats, "count": len(cats),
            "basis": "measured (Pinterest's own taxonomy)",
            "note": "The 14 level-1 verticals are referenced as parents but are NOT "
                    "entries here — passing one as a category_id is a 400 every time.",
        })

    if operation == "category_top":
        rows = api.top_categories(country=region, event=event) or []
        return _ok({
            **common, "event": event, "categories": rows, "count": len(rows),
            "basis": "measured, RELATIVE within this response",
            "note": "`total` is always 0 — Pinterest withholds absolutes; use "
                    "percent_relative_volume. Category counts differ per event: "
                    "OUTBOUND_CLICK 44, ENGAGEMENT 35, SAVE 18. The click-vs-save "
                    "gap IS the buyer-vs-dreamer signal.",
        })

    if operation == "category_metrics":
        rows = api.category_metrics([category_id], country=region, event=event,
                                    days=min(days, 730)) or []
        return _ok({
            **common, "category_id": category_id, "event": event,
            "series": [{"category": r.get("term"),
                        **normalise_series(r.get("daily_values"))} for r in rows],
            "note": "`daily_values` is a misnomer — the buckets are WEEKLY.",
        })

    if operation == "category_demographics":
        data = api.category_demographics([category_id], country=region,
                                         event=event) or {}
        return _ok({
            **common, "category_id": category_id, "event": event,
            "distributions": data.get("product_category_distributions") or data,
            "basis": "measured",
            "note": "`event` genuinely RE-COMPUTES this, it is not a label swap — the "
                    "people who SAVE a category and those who CLICK THROUGH can be "
                    "different age groups entirely. A demographic quoted without "
                    "naming its event is meaningless. `related_search_trends` rides "
                    "along free in this same call.",
        })

    if operation in ("top_products", "etsy_competitors"):
        rows = (api.etsy_competitors(category_id, country=region, event=event)
                if operation == "etsy_competitors"
                else api.top_products(category_id, country=region, event=event)) or []
        payload = {**common, "category_id": category_id, "event": event,
                   "products": rows, "count": len(rows),
                   "basis": "measured"}
        if operation == "etsy_competitors" and not rows:
            payload["finding"] = (
                "No Etsy sellers rank in this category — that is a RESULT, not "
                "missing data. Measured elsewhere: 0 in Area rugs, Bath mats, "
                "Candles, Cake decorating. Those niches belong to mass retail.")
        if event != "OUTBOUND_CLICK":
            payload["warning"] = "top_products only returns rows on OUTBOUND_CLICK."
        return _ok(payload)

    if operation == "featured":
        data = api.featured_topics(country=region) or {}
        return _ok({
            **common, "topics": data, "basis": "curated by Pinterest, not organic",
            "note": "SAVE-ranked = aspiration, not purchase intent. Pair with "
                    "category_top on OUTBOUND_CLICK to tell dreaming from buying. "
                    "pct_growth_mom is raw — the UI multiplies it by 100. "
                    "US/CA/GB+IE only.",
        })

    if operation == "editorial":
        data = api.editorial_content(country=region) or {}
        return _ok({
            **common, "stories": data,
            "basis": "curated, editorial — NO growth number and NO series",
            "note": "Do not rank on these. The region path segment is IGNORED: one "
                    "request covers US, CA and GB+IE, and the per-region split lives "
                    "inside each story's `keywords` dict.",
        })

    return _fail(f"unknown operation: {operation}")

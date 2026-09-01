"""Shared `Literal` aliases for the grouped tools, and the wire-shape normalisers.

⚠️ **Import these INTO the tool module's namespace** — `from mcp_server._ops import
PinterestOp` — never reference them through a namespace (`_ops.PinterestOp`).
MCP builds a tool's schema with `inspect.signature(fn, eval_str=True)`, which
resolves annotations against the **wrapped function's own module globals**. An
alias the tool module cannot see by bare name raises `InvalidSignature` at
registration.

Why `Literal` and not `Enum`: measured on this SDK, `Literal` publishes as an
inline JSON-schema `enum` (cheapest, no indirection), while an `Enum` subclass
hoists into `$defs` and costs an extra `$ref` for the agent to resolve. And never
`Optional[Literal[...]]` — that collapses the enum into an `anyOf` and buries it
one level down.
"""
from typing import Literal

# --- Pinterest ------------------------------------------------------------------------
PinterestOp = Literal[
    "top_trends",             # the rising-keyword discovery table
    "metrics",                # weekly demand series for up to ~50 terms in one call
    "related",                # co-searched terms, series ride along free
    "prefix",                 # autocomplete children, series ride along free
    "demographics",           # age + gender per term
    "moments",                # the seasonal calendar: takeoff/peak dates per moment
    "moment_curve",           # a moment's CURVE — the only sub-weekly series here
    "categories",             # the 383-node shopping taxonomy
    "category_top",           # ranked trending categories
    "category_metrics",       # a category's demand curve
    "category_demographics",  # who engages with a category
    "top_products",           # the pins driving clicks in a category
    "etsy_competitors",       # ...filtered to Etsy sellers only
    "featured",               # Spotlight: 5 curated topics
    "editorial",              # the written trend stories
]

ResearchOp = Literal[
    "expand",           # seed -> long_tail + neighbours. 2 requests, ZERO /metrics/
    "long_tail",        # prefix children of a seed
    "neighbours",       # co-searched terms, need not share a word
    "sweep",            # the discovery table across interests — 24 requests
    "audience",         # age/gender per term, WITH the batch-relative skew
    "merchant_share",   # who owns a category's outbound clicks
    "demand_table",     # every category's growth + intent ratio, one request
    "classify",         # free text -> category ids
    "taxonomy_search",  # substring search over category names
    "alerts",           # week-over-week movement, local archive, no network
    "history",          # rank history / longevity, local archive, no network
]

HistoryOp = Literal[
    "keyword",      # every demand reading for a term, oldest first
    "trend",        # Pinterest readings, matched across the wording gap
    "shop",         # a competitor's counter over time — the only MEASURED sales
    "listing",      # one listing's readings
    "rank",         # a listing's rank curve
    "launches",     # what has been listed, with its prediction
    "outcomes",     # did those predictions come true — the LEARN join
    "calibration",  # ...and whether it can be trusted yet (B-04)
]

EtsyPrivateOp = Literal[
    "results_data",      # volume, supply, CVR, prices + 20 competitor cards, one call
    "daily_stats",       # the DAILY curve riding free on that same call (D-51)
    "chart_series",      # the 12-month seasonal curve (D-45)
    "similar_keywords",  # Etsy's own LLM expansion, each edge pre-sized
    "trending",          # rising terms per taxonomy id, no quota cost
]

EtsyPublicOp = Literal[
    "search",         # the SERP: supply, ranked ids, ~12 cards
    "listing",        # tags + breadcrumb + type + age + Etsy's own query expansion
    "listing_live",   # cart / favourites / 24h badge — volatile, NEVER cached
    "shop_metrics",   # a competitor shop's totals
    "shop_listings",  # a competitor shop's inventory
]

AnalyzeOp = Literal[
    "winnability",   # demand-per-listing — the ranking number (D-31)
    "intent",        # CVR vs the pooled median — RELATIVE only (D-43)
    "seasonality",   # peak/trough from Etsy's own 12-month curve (D-45)
    "saturation",    # page-one share, brackets withheld when inconclusive (D-36)
    "freshness",     # how old is every reading for this term
    "filter_trust",  # which SERP filters may be believed at all (D-32)
    "discriminate",  # CAN this pool be ranked, or would a score be noise (N-01)
]

CrawlOp = Literal[
    "crawl",        # recursive best-first expansion + the winnable pockets
    "expand_seed",  # one level only, cheaper
]

# --- the three spellings of one idea ---------------------------------------------------
# The same "upper prediction bound" ships under a different key on every endpoint
# that has one. Normalising here means a consumer never has to know which
# endpoint a point came from.
_UPPER_KEYS = (
    "predictedUpperBoundNormalizedCount",        # search /metrics/
    "normalized_predicted_upper_bound",          # shopping category_metrics
    "predicted_normalized_upper_bound_count",    # moment_metrics
)
_LOWER_KEYS = (
    "predictedLowerBoundNormalizedCount",
    "normalized_predicted_lower_bound",
    "predicted_normalized_lower_bound_count",
)


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return None


def normalise_point(p):
    """One series point in a single shape, whichever endpoint produced it.

    Also absorbs the OTHER shape hazard: `/metrics/` returns two different row
    types depending on whether the SeriesStore served it locally. A wire point
    carries `date`/`normalizedCount`/bounds; a locally-served point carries only
    `count`. A consumer reading `p["date"]` breaks on the second, and
    `split_forecast()` on it silently returns everything as observed.
    """
    if not isinstance(p, dict):
        return {"count": p, "date": None, "is_forecast": False}
    upper = _first(p, _UPPER_KEYS)
    return {
        "date": p.get("date") or p.get("label"),
        "timestamp": p.get("timestamp"),
        # `count` is the raw series; `normalized` is the 0-100 scale where present.
        "count": p.get("count") if p.get("count") is not None else p.get("normal_counts"),
        "normalized": p.get("normalizedCount"),
        "predicted_upper": upper,
        "predicted_lower": _first(p, _LOWER_KEYS),
        # The ONLY reliable marker: moment_metrics has no has_prediction flag at
        # all, so a non-null upper bound is what makes a point a prediction.
        "is_forecast": upper is not None,
    }


def normalise_series(points):
    """A whole series, plus the observed/forecast split stated rather than implied."""
    out = [normalise_point(p) for p in (points or [])]
    return {
        "points": out,
        "observed_points": sum(1 for p in out if not p["is_forecast"]),
        "forecast_points": sum(1 for p in out if p["is_forecast"]),
        "basis": "measured; points flagged is_forecast are PREDICTED, not observed",
    }

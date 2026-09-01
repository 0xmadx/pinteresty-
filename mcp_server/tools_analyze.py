"""The judgements — free, fast, and the half that turns data into a decision.

Every operation here reads the local database or is pure arithmetic. **No network,
no session, no preflight**, so an agent can reason as much as it likes without
spending anything. That is deliberate: the expensive tools fetch, and this one
decides, and separating them means thinking is never rationed.

WHAT THESE ARE FOR
------------------
The system's whole failure mode is *a plausible wrong number*. These are the
functions that refuse to produce one:

* `winnability` returns the RATIO, not a score — "you cannot rank here" has to be
  checkable, and a composite would rank the list equally well while explaining
  nothing (D-31).
* `intent` compares CVR **between** terms and never as an absolute, because
  `query_cvr` has no known units — `volume x cvr` implies 39.8 orders/month for a
  term whose top listing holds 14,733 reviews (D-43).
* `survivorship` reports a BOUND and calls a 100% share `uninformative` rather
  than "healthy".
* `saturation` withholds any bracket whose confidence interval straddles a
  threshold — 0 of 6 does not establish an empty bracket (D-36).
* `discriminate` refuses to rank at all when the dimensions cannot separate the
  pool.

Every one of them can return "unmeasured", and that is a real answer here rather
than a failure: absent is not zero (N-02).
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import AnalyzeOp
from mcp_server._plumbing import _fail, _guarded, _ok, mcp

_NEEDS_TERM = {"winnability", "intent", "seasonality", "saturation", "freshness"}

_OP_DOC = (
    "winnability: demand-per-listing, THE ranking number — pass term, or "
    "volume+supply. intent: CVR vs the pooled median, RELATIVE only. "
    "seasonality: peak/trough from Etsy's own curve. saturation: page-one share, "
    "inconclusive brackets withheld. freshness: age of every reading. "
    "filter_trust: which SERP filters may be believed. discriminate: CAN this pool "
    "be ranked, or is a score noise. All free — DB or pure, no session."
)


@mcp.tool()
@_guarded
def analyze(
    operation: Annotated[AnalyzeOp, Field(description=_OP_DOC)],
    term: str | None = None,
    volume: int | None = None,
    supply: int | None = None,
    cvr: float | None = None,
) -> dict:
    """Judgements over what is already known. Free, offline, and allowed to say 'unmeasured'."""
    if operation in _NEEDS_TERM and not term and operation != "winnability":
        return _fail(f"operation '{operation}' needs `term`",
                     fix="Pass the keyword to judge.")
    if operation == "winnability" and not term and not (volume and supply):
        return _fail("winnability needs either `term` or both `volume` and `supply`",
                     fix="term reads the stored measurement; volume+supply judges "
                         "numbers you already have.")

    from core.database import MarketDatabase
    db = MarketDatabase()

    if operation == "winnability":
        return _winnability(db, term, volume, supply, cvr)
    if operation == "intent":
        return _intent(db, term, cvr)
    if operation == "seasonality":
        return _seasonality(db, term)
    if operation == "saturation":
        return _saturation(db, term)
    if operation == "freshness":
        return _freshness(db, term)
    if operation == "filter_trust":
        return _filter_trust()
    if operation == "discriminate":
        return _discriminate(db)
    return _fail(f"unknown operation: {operation}")


def _winnability(db, term, volume, supply, cvr):
    from etsy.analytics.discover import winnability

    src = "supplied"
    if term and not (volume and supply):
        row = db.get_keyword(term) or {}
        volume = volume or row.get("search_volume")
        supply = supply or row.get("competition")
        cvr = cvr if cvr is not None else row.get("query_cvr")
        src = f"stored reading from {row.get('collected_at')}" if row else "not in the database"

    verdict = winnability({"volume": volume, "supply": supply, "cvr": cvr})
    return _ok({
        "operation": "winnability", "term": term,
        "volume": volume, "supply": supply, "verdict": verdict, "source": src,
        "note": "The RATIO is the answer, not a score. A term with 2M listings is a "
                "wall however large its traffic — rank by demand_per_listing, never "
                "by volume (D-31). A null ratio means unsized, NOT hopeless.",
    })


def _intent(db, term, cvr):
    from etsy.analytics.discover import reference_median

    row = db.get_keyword(term) or {}
    mine = cvr if cvr is not None else row.get("query_cvr")
    # measured_cvrs() returns {keyword: cvr}, NOT a list. Iterating it bare yields
    # the keyword STRINGS, which reach _median and crash on `str / int`. Caught by
    # smoke-testing the tool rather than by reading the signature.
    pool = [c for c in (db.measured_cvrs() or {}).values() if c]
    median = reference_median([], extra_cvrs=pool)

    if mine is None or median is None:
        return _ok({
            "operation": "intent", "term": term, "verdict": "unmeasured",
            "cvr": mine, "pool_median": median, "pool_size": len(pool),
            "basis": "unmeasured",
            "note": "No measured CVR for this term, or too few in the pool to form "
                    "a reference. That is a refusal, not a low score.",
        })

    ratio = mine / median if median else None
    verdict = ("strong" if ratio and ratio >= 1.5 else
               "typical" if ratio and ratio >= 0.75 else "weak")
    return _ok({
        "operation": "intent", "term": term, "cvr": mine,
        "pool_median": median, "pool_size": len(pool),
        "vs_median": round(ratio, 3) if ratio else None,
        "verdict": verdict, "basis": "relative_only",
        "note": "⚠️ RELATIVE ONLY. query_cvr has no known units — volume x cvr is "
                "NOT an order count (it implies 39.8/month for a term whose #1 "
                "listing holds 14,733 reviews). Compare between terms; never "
                "threshold it as a quantity (D-43).",
    })


def _seasonality(db, term):
    stored = db.latest_seasonality(term)
    if not stored:
        return _ok({
            "operation": "seasonality", "term": term, "verdict": "unmeasured",
            "basis": "unmeasured",
            "note": "No stored curve for this term. Etsy ships a 12-month volume "
                    "curve free on every chart-series call (D-45); it is collected "
                    "by the keyword sweep, so a term that has never been swept has "
                    "no curve rather than a flat one.",
        })
    return _ok({"operation": "seasonality", "term": term, "profile": stored,
                "basis": "measured",
                "note": "⚠️ The last bucket is the CURRENT month, counted so far — "
                        "judging on it manufactures a collapse."})


def _saturation(db, term):
    comp = db.latest_keyword_competition(term)
    if not comp:
        return _ok({"operation": "saturation", "term": term, "verdict": "unmeasured",
                    "basis": "unmeasured",
                    "note": "No stored page-one reading for this term."})
    return _ok({
        "operation": "saturation", "term": term,
        "total_results": comp.get("total_results"),
        "organic_sample": comp.get("organic_sample"),
        "ranked_ids": comp.get("ranked_ids_count"),
        "saturation": comp.get("saturation"),
        "delivery_bands": comp.get("delivery_bands"),
        "median_delivery": comp.get("median_delivery"),
        "collected_at": comp.get("collected_at"),
        "basis": "measured on a ~9-listing page-one SAMPLE, not the market",
        "note": "A page-one share is ~9 listings. A bracket whose confidence "
                "interval straddles a threshold is WITHHELD rather than reported — "
                "0 of 6 does not establish an empty bracket, the true share could "
                "be 39% (D-36). Never divide this sample by total_results.",
    })


def _freshness(db, term):
    from etsy.analytics.freshness import freshness_floor, freshness_tag, staleness_days

    stamps, seen = {}, []
    for label, row in (("demand", db.get_keyword(term)),
                       ("competition", db.latest_keyword_competition(term))):
        ts = (row or {}).get("collected_at")
        stamps[label] = ts
        if ts:
            seen.append(ts)
    floor = freshness_floor(*seen) if seen else None
    return _ok({
        "operation": "freshness", "term": term, "readings": stamps,
        "oldest": floor, "days_stale": staleness_days(floor) if floor else None,
        "tag": freshness_tag(floor) if floor else "never measured",
        "basis": "measured" if floor else "unmeasured",
        "note": "A composite is only as fresh as its OLDEST input — that is what "
                "`oldest` reports. A missing reading is 'never looked', not 'zero'.",
    })


def _filter_trust():
    from etsy.analytics import filter_trust
    reg = filter_trust.load()
    trusted = sorted(n for n, v in reg.items() if v.usable and not v.stale)
    return _ok({
        "operation": "filter_trust",
        "trusted": trusted, "total_audited": len(reg),
        "filters": [{"name": n, "status": v.status, "usable": v.usable,
                     "stale": v.stale, "note": v.note} for n, v in sorted(reg.items())],
        "note": f"Only {len(trusted)} of {len(reg)} audited filters return a real "
                f"subset. The rest silently lie — min_rating=5 returns 4.8-rated "
                f"listings, colour brackets sum to 562% of supply. find_gaps refuses "
                f"them outright rather than reporting a percentage (D-32).",
    })


def _discriminate(db):
    from etsy.analytics.scoring import can_discriminate
    from etsy.ui.app_data import build_discovered

    pool = build_discovered(limit=2000)
    v = can_discriminate(pool)
    # can_discriminate returns a NamedTuple. Left alone it serialises to a bare
    # JSON array — ["true", "single dimension...", ["supply"], null] — and every
    # field name is lost on the wire, so the consumer has to know the positional
    # order to read its own answer. Explicit dict instead.
    verdict = {"ok": v.ok, "reason": v.reason,
               "dimensions": list(v.dimensions or ()), "spread": v.spread}
    return _ok({
        "operation": "discriminate", "pool_size": len(pool), "verdict": verdict,
        "note": "Ask this BEFORE trusting any ranking. When the dimensions cannot "
                "separate the pool, a score is noise wearing a number — the honest "
                "output is a labelled filter, not an ordering (N-01).",
    })

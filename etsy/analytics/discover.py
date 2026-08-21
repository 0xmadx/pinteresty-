"""DISCOVER — candidates without typing a keyword (the calendar's other half).

Until now the system dated and judged terms the operator supplied. That is a checker
with a calendar bolted on. The front door is Etsy telling *us* what is moving.

`trending-search-terms-v2` returns a category's rising terms with real search volumes,
and per its own docstring does not consume the daily quota. Verified live 2026-08-15
across a probe of 15 taxonomy ids: **only seven are populated**, four terms each.

    1     Accessories            badge reel 218k, keychain 116k, bag charm 81k
    66    Art & Collectibles     back to school 211k, needlepoint canvas 62k, fall png 44k
    199   Bath & Beauty          press on nails 218k, birthday gift 78k
    323   Books, Movies & Music
    891   Home & Living          home decor 310k, personalized gift 209k
    1429  Shoes
    1633  Weddings               wedding gifts 272k, wedding 156k

The id list is empirical, not documented — several plausible ids (Jewelry, Clothing,
Craft Supplies) returned nothing, so it is a parameter rather than a constant.

⚠️ **These are Etsy's picks, not the top terms by volume.** Etsy chose to surface them,
by criteria it does not publish. That is a selection effect of exactly the kind B-01
warns about: treating this list as "what is trending" rather than "what Etsy is
promoting" would quietly inherit someone else's agenda as market truth. Every candidate
carries `basis="etsy_curated"` so the bias travels with the data.

**Two fields that are NOT a front door, contrary to earlier notes in this repo.**
`similar_search_terms` and `market_gap_recommendations` were recorded as free unread
signals when the snake_case bug was found. Probed on `felt garland`, `mom necklace` and
`christmas ornament`, all three returned `total_results_count: 0` and a null gap block.
The keys are in the response schema; Etsy returns nothing in them. Corrected here so
nothing is built on them again.

**Two gates, not one (D-43).** `winnability` asks *can I rank here* — searches
divided by listings, both supply-side facts, free with every edge. `confirm_intent`
asks *do these searchers buy* — which needs `query_cvr`, a field the expansion
endpoint does not return at any price, so it costs one results-data call per term.

A term passing only the first is the reported failure: a Pinterest-sourced trend with
real traffic, few competitors, and searchers who never check out — "winnable" by
ratio, dead in practice. The cheap gate runs wide and first; the expensive one runs
only on what survived it, and the headline verdict is the worse of the two.

The intent gate is deliberately **relative** — a term against the median of the terms
measured beside it — because `query_cvr` cannot be converted into an order count.
See `confirm_intent` for the evidence that killed the absolute version.
"""
# Empirically populated top-level categories. Others returned zero terms.
TRENDING_TAXONOMIES = {
    1: "Accessories",
    66: "Art & Collectibles",
    199: "Bath & Beauty",
    323: "Books, Movies & Music",
    891: "Home & Living",
    1429: "Shoes",
    1633: "Weddings",
}


def trending_candidates(api, taxonomy_ids=None):
    """Rising terms across categories, deduped, highest volume first.

    A term appearing in two categories keeps the higher volume and records both, since
    breadth across categories is itself a signal.
    """
    taxonomy_ids = taxonomy_ids or list(TRENDING_TAXONOMIES)
    seen = {}
    for tid in taxonomy_ids:
        payload = api.get_trending_terms(taxonomy_id=tid)
        if not payload:
            continue
        category = payload.get("category_name") or TRENDING_TAXONOMIES.get(tid)
        for entry in payload.get("search_terms") or []:
            term = entry.get("search_term")
            volume = entry.get("search_volume")
            if not term:
                continue
            existing = seen.get(term)
            if existing:
                existing["categories"].append(category)
                if volume and (existing["volume"] or 0) < volume:
                    existing["volume"] = volume
                continue
            seen[term] = {
                "term": term,
                # None, not 0: a term Etsy surfaced without a volume is unmeasured,
                # and 0 would sort it last as though nobody searches it (N-02).
                "volume": volume,
                "categories": [category],
                # Etsy chose this list. It is not the top of the market by volume.
                "basis": "etsy_curated",
            }
    return sorted(seen.values(), key=lambda c: c["volume"] or -1, reverse=True)


def winnability(data):
    """Can this shop plausibly rank here? Demand per listing, and the intent behind it.

    **Market size is not opportunity.** Measured live 2026-08-15:

        home decor          310,467 searches / 2,160,627 listings = 0.14   cvr 0.00005
        backpack name tag    69,874 searches /    25,031 listings = 2.79   cvr 0.00279

    `backpack name tag` has 19x the demand per listing and 56x the conversion rate.
    Ranked by volume it sits seventeenth, under three terms this shop can never reach.

    Returns the ratio itself rather than a score. A composite number would rank the
    list just as well and tell the operator nothing about why — and "you cannot rank
    here" is a conclusion they need to be able to check.
    """
    volume, supply, cvr = data.get("volume"), data.get("supply"), data.get("cvr")
    if not volume or not supply:
        # Absent is not zero: an unsized term is unknown, and a 0 ratio would sort it
        # alongside terms measured to be hopeless (N-02).
        return {"demand_per_listing": None, "basis": "unmeasured",
                "detail": "volume or supply missing"}

    ratio = volume / supply
    # Thresholds are deliberately coarse and named, not tuned. They separate "a wall"
    # from "a chance" for a shop with no ranking authority; they are not a prediction.
    if ratio >= 1.0:
        verdict, reason = "winnable", "more searches than listings — a new listing can surface"
    elif ratio >= 0.25:
        verdict, reason = "contested", "several listings per search — possible, not easy"
    else:
        verdict, reason = "wall", f"{supply:,} listings against {volume:,} searches"

    return {
        "demand_per_listing": round(ratio, 3),
        "volume": volume,
        "supply": supply,
        "cvr": cvr,
        "verdict": verdict,
        "reason": reason,
        "basis": "measured",
    }


# Below this many measured terms, the pool median is not a reference point and the
# intent gate refuses rather than ranking against noise — the same discipline
# `score_pool`'s PoolTooSmall applies (D-15).
MIN_POOL_FOR_INTENT = 8

# A term converting below this fraction of the pool median is flagged. Relative, and
# deliberately coarse: half the typical rate is a difference of kind, not of degree.
WEAK_INTENT_RATIO = 0.5


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return None
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def confirm_intent(data, pool_median_cvr):
    """Do the people searching this term buy it — *relative to its peers*?

    `winnability` divides searches by listings. Both halves are supply-side facts, so
    a term can pass that gate on traffic alone — high searches, few listings — while
    converting far below everything around it. That is the standard shape of a
    Pinterest-sourced trend: the interest is real, aspirational, and never reaches a
    checkout.

    **Why relative, and not a units-per-week threshold.** The obvious design is
    `volume × query_cvr` = orders, then reject below N orders/week. That was built
    first and thrown away, because the arithmetic does not survive contact with
    observable evidence:

        "personalized gift"  209,917 searches/mo × query_cvr 0.00018970
                             => 39.8 orders/month for the WHOLE market
        ...while the #1 listing for that term carries 14,733 lifetime reviews.

    One listing would need three decades to accumulate that, against 705,767
    competitors. So `volume × query_cvr` is not a count of orders, and any absolute
    threshold built on it would be a confident number with unknown units — the exact
    failure this system exists to prevent. (`opportunity.market_demand` makes that
    claim and is wrong; see D-43 and the note in that module.)

    What survives is the **comparison**. `query_cvr` is one field from one endpoint,
    defined the same way for every term, so a ratio between two terms is meaningful
    even when the constant relating it to orders is not known. A term converting at a
    fifth of its peers converts badly, whatever the units are.

    `pool_median_cvr` is the reference — the median across the terms measured in the
    same run. `None` means the pool was too small to have one, and the gate refuses.
    """
    cvr = (data or {}).get("cvr")
    if cvr is None:
        # Absent is not zero (N-02). A term whose CVR never came back is UNKNOWN;
        # branding it weak would reject real niches on a missing field.
        return {"verdict": "unmeasured", "cvr": None, "cvr_vs_pool": None,
                "basis": "unmeasured", "detail": "no CVR returned for this term"}
    if not pool_median_cvr:
        return {"verdict": "unmeasured", "cvr": cvr, "cvr_vs_pool": None,
                "basis": "pool_too_small",
                "detail": f"fewer than {MIN_POOL_FOR_INTENT} measured terms — no "
                          f"median to compare against, so intent is not judged"}

    share = cvr / pool_median_cvr
    if share < WEAK_INTENT_RATIO:
        verdict, reason = "weak", (
            f"converts at {share:.2f}x the median of the terms measured beside it — "
            f"searched far more than it is bought")
    elif share < 1.5:
        verdict, reason = "typical", (
            f"converts at {share:.2f}x the pool median — ordinary for this pool")
    else:
        verdict, reason = "strong", (
            f"converts at {share:.2f}x the pool median — its searchers buy")

    return {"verdict": verdict, "cvr": cvr, "cvr_vs_pool": round(share, 3),
            "basis": "measured_relative", "reason": reason,
            # Said plainly, because a reader WILL want to turn this into a sales
            # figure and it cannot be turned into one.
            "note": "a RELATIVE comparison between terms, not a conversion rate or "
                    "an order count"}


def combined_verdict(win, intent):
    """The headline the operator reads: the WORSE of supply and intent, never averaged.

    Both readings are kept whole and separate (B-05) — `winnability` still says what
    the supply side says, `intent` still says what the demand side says. This only
    decides which one is allowed to lead, and the answer is always the pessimist:
    passing one gate is not passing both.

    A `weak` intent produces `weak_intent`, a verdict distinct from `wall`. They fail
    for opposite reasons and the fix differs — a wall has too many competitors, a
    weak-intent term has searchers who do not buy, and ranking effort helps neither
    but means something different to the operator reading it.
    """
    ratio_verdict = win.get("verdict")
    if not ratio_verdict:
        return None, None
    if ratio_verdict == "wall":
        # Already rejected on supply; intent cannot rescue it and was not spent on it.
        return "wall", win.get("reason")

    if (intent or {}).get("verdict") == "weak":
        return "weak_intent", intent.get("reason")
    return ratio_verdict, win.get("reason")


def apply_intent(candidates, fetch, top_n=25):
    """Spend one results-data call each on the top candidates, to check they convert.

    **Why only the top N.** The ratio gate is free (volume and supply arrive inline
    with every edge), the intent check is not — it costs one private-tier call per
    term, and the private tier authenticates as the operator's own seller account
    (D-29). Checking four hundred expansions would spend the one irreplaceable asset
    on terms already rejected on supply. So the cheap gate runs wide and first, and
    the expensive one runs only on what survived it.

    Candidates below the cut keep `intent.basis = "not_checked"` — explicitly not the
    same claim as "checked and found nothing". A reader can tell which terms were
    examined.

    Two passes, because the gate is relative: every eligible term is measured first,
    then the median of what came back becomes the reference each is judged against.
    A single term cannot be judged alone, and this is why.
    """
    # Pass 1 — measure. One private call per eligible candidate, and no judgement yet.
    measured = {}
    for i, candidate in enumerate(candidates):
        win = candidate.get("winnability") or {}
        if i < top_n and win.get("verdict") in ("winnable", "contested"):
            measured[candidate["term"]] = fetch(candidate["term"])

    # The reference: the median CVR of the terms measured in THIS run. Refuses below
    # MIN_POOL_FOR_INTENT, where a median is noise rather than a reference point.
    cvrs = [d["cvr"] for d in measured.values()
            if d and d.get("cvr") is not None]
    pool_median = _median(cvrs) if len(cvrs) >= MIN_POOL_FOR_INTENT else None

    # Pass 2 — judge each against the pool.
    out = []
    for candidate in candidates:
        win = candidate.get("winnability") or {}
        if candidate["term"] not in measured:
            intent = {"verdict": None, "cvr": None, "cvr_vs_pool": None,
                      "basis": "not_checked",
                      "detail": "outside the top N, or already rejected on supply"}
        elif not measured[candidate["term"]]:
            intent = {"verdict": "unmeasured", "cvr": None, "cvr_vs_pool": None,
                      "basis": "fetch_failed",
                      "detail": "results-data returned nothing"}
        else:
            intent = confirm_intent(measured[candidate["term"]], pool_median)

        verdict, reason = combined_verdict(win, intent)
        out.append({**candidate, "intent": intent,
                    "verdict": verdict, "verdict_reason": reason,
                    "pool_median_cvr": pool_median})

    # Re-sort: a weak-intent term must not keep the seat its ratio won. Strong intent
    # leads, then typical, then unchecked/unmeasured, then weak.
    tier = {"strong": 3, "typical": 2, None: 1, "unmeasured": 1, "weak": 0}
    return sorted(
        out,
        key=lambda c: (tier.get((c.get("intent") or {}).get("verdict"), 1),
                       (c.get("winnability") or {}).get("demand_per_listing") is not None,
                       (c.get("winnability") or {}).get("demand_per_listing") or 0),
        reverse=True)


def rank_by_opportunity(candidates, fetch):
    """Re-rank candidates by winnability, not by market size.

    `fetch` returns parsed results-data for a term. Terms that cannot be sized keep
    their place at the end rather than being dropped — unmeasured is not hopeless.
    """
    out = []
    for candidate in candidates:
        data = fetch(candidate["term"])
        out.append({**candidate,
                    "winnability": winnability(data) if data else
                    {"demand_per_listing": None, "basis": "fetch_failed"}})
    # Sort on the ratio, then CVR as the tiebreak: of two equally crowded terms the
    # one whose searchers actually buy is the better bet.
    return sorted(
        out,
        key=lambda c: (c["winnability"]["demand_per_listing"] is not None,
                       c["winnability"].get("demand_per_listing") or 0,
                       c["winnability"].get("cvr") or 0),
        reverse=True)


def expand_seed(api, seed):
    """One seed keyword → its long-tail neighbourhood, each sized for winnability.

    Wraps `get_similar_keywords` (the LLM keyword endpoint, ~118 edges per seed) into
    the candidate shape the rest of DISCOVER uses. Each edge already carries its own
    search_volume and avg_total_listings, so winnability is computable without a second
    call per term — which is what makes recursion affordable.

    This is the answer to the narrowness of the curated front door. `trending_candidates`
    returns 28 head terms Etsy chose to promote; a single seed here returns a hundred
    long-tail terms Etsy did NOT promote, which is exactly where the winnable ground
    lives (see the etsy-seo-and-opportunity skill).

    The endpoint caches server-side: the first call for a seed computes the run, later
    calls return it in `cached_data` instantly. Combined with the local RequestCache,
    the second hunt over a seed is effectively free — the self-learning flywheel, but
    the cache is Etsy's and ours rather than something we had to build.
    """
    from etsy.api.private.api import edge_term

    edges = api.get_similar_keywords(seed)
    if not edges:
        return []
    out = []
    for edge in edges:
        term = edge_term(edge)
        if not term or term == seed:
            continue
        out.append({
            "term": term,
            "volume": edge.get("search_volume"),
            "supply": edge.get("avg_total_listings"),
            "categories": [f"expanded from '{seed}'"],
            # NOT etsy_curated: these are the algorithm's neighbours of a seed WE chose,
            # so the curation bias is ours and known, not Etsy's promotional agenda.
            "basis": "seed_expansion",
            "seed": seed,
        })
    return out


def rank_expanded(candidates):
    """Rank already-sized candidates by winnability, with no extra fetch.

    `expand_seed` edges carry their own volume and supply, so their winnability is
    computable directly — the whole point of the LLM endpoint returning metrics inline.
    A separate `fetch`-based path (`rank_by_opportunity`) exists for candidates that
    arrive unsized, like the trending front door.
    """
    out = [{**c, "winnability": winnability(c)} for c in candidates]
    return sorted(
        out,
        key=lambda c: (c["winnability"]["demand_per_listing"] is not None,
                       c["winnability"].get("demand_per_listing") or 0,
                       c["winnability"].get("cvr") or 0),
        reverse=True)


def attach_moments(candidates, calendar_rows):
    """Tag each candidate with the seasonal moment it belongs to, if any.

    This is the join that makes the front door a *calendar*: "back to school" and
    "fall png" are not merely popular, they are popular *now* and have a deadline.

    Containment on content words, most specific wins — a candidate matching no moment
    is evergreen, which is a fact about it rather than a gap in the data.
    """
    from etsy.analytics.term_join import content_words

    out = []
    for candidate in candidates:
        words = content_words(candidate["term"])
        best, best_size = None, 0
        for row in calendar_rows or []:
            needed = content_words(row.get("moment") or "")
            if needed and needed <= words and len(needed) > best_size:
                best, best_size = row, len(needed)
        out.append({
            **candidate,
            "moment": best["moment"] if best else None,
            "list_by": best["list_by"] if best else None,
            "state": best["state"] if best else None,
            "is_late": best.get("is_late") if best else None,
            # An evergreen term has no deadline. Saying so beats leaving the field
            # blank and letting a reader assume it was simply not checked.
            "timing": "seasonal" if best else "evergreen",
        })
    return out


def render(candidates, limit=20):
    icon = {"winnable": "🟢", "contested": "🟡", "wall": "🔴", "weak_intent": "⛔"}
    lines = []
    for c in candidates[:limit]:
        volume = f"{c['volume']:>8,}" if c["volume"] is not None else "       ?"
        when = ""
        if c.get("timing") == "seasonal":
            when = f"  → {c['moment']} by {c['list_by']}"
            if c.get("is_late"):
                when += " ⚠️LATE"

        win = c.get("winnability")
        if win and win.get("demand_per_listing") is not None:
            # The ratio is shown, not a score: "you cannot rank here" is a conclusion
            # the operator has to be able to check.
            verdict = c.get("verdict") or win["verdict"]
            head = (f"{icon.get(verdict, '⚪')} {win['demand_per_listing']:>6.2f}/listing")
        else:
            head = f"⚪ {'unsized':>14}"
        lines.append(f"{head}  {volume}  {c['term']:<28}{when}")

        # The intent line, indented under its term: a ratio that passed on traffic
        # alone must not be the last word the operator reads.
        intent = c.get("intent") or {}
        if intent.get("basis") == "measured_relative":
            lines.append(f"{'':>4}   {intent['reason']}")
        elif intent.get("basis") in ("unmeasured", "fetch_failed", "pool_too_small"):
            lines.append(f"{'':>4}   intent UNKNOWN — {intent.get('detail')}")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(prog="discover")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seasonal-only", action="store_true")
    parser.add_argument("--by-volume", action="store_true",
                        help="rank by market size instead of winnability (rarely useful)")
    parser.add_argument("--no-intent-check", action="store_true",
                        help="skip the CVR/intent gate (saves one private call per "
                             "candidate, and lets traffic-only terms read as winnable)")
    args = parser.parse_args(argv)

    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.analytics.calendar import build
    from pinterest.endpoints.api import PinterestTrendsAPI

    api = EtsyPrivateAPI()
    candidates = trending_candidates(api)
    with PinterestTrendsAPI() as pin:
        rows = build(pin.moments_calendar(country="US"))

    tagged = attach_moments(candidates, rows)
    if args.seasonal_only:
        tagged = [c for c in tagged if c["timing"] == "seasonal"]

    def fetch(term):
        raw = api.get_results_data(term)
        return parse_results_data(raw) if raw else None

    if not args.by_volume:
        tagged = rank_by_opportunity(tagged[:args.limit], fetch)
        if not args.no_intent_check:
            # The second gate: rankable is not the same as bought (D-43).
            tagged = apply_intent(tagged, fetch, top_n=args.limit)

    print(f"{len(tagged)} candidates — Etsy's curated picks, not the top of the market. "
          f"Ranked by {'volume' if args.by_volume else 'winnability, then intent'}.\n")
    print(render(tagged, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

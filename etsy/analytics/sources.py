"""Term discovery across SEVERAL doors, combined with a stated rule.

The operator's ask: *"there is a lot of strategies, so my platform and api need to
have parameters and payload like OR / AND and get synthesised."* This is that seam.

THE THREE DOORS ARE NOT THE SAME SHAPE — that is the whole reason to combine them.
Measured 2026-09-01 on `halloween badge reel`:

    etsy_suggest     CHILDREN   longer real buyer queries      18 terms   PUBLIC, 2 req
                                `halloween badge reel nurse`
    etsy_expand      SIBLINGS   same level, sideways          180 terms   SELLER, 1 expansion
                                `fall badge reel`, `ghost badge reel`
    pinterest_prefix NEIGHBOURS Pinterest's own vocabulary     10 terms   PINTEREST, 1 req
                                `badge reel ideas`, `cute badge reel`

The Etsy doors returned **completely disjoint** sets — all 18 suggestions were
absent from all 180 expansion children. Reading one door and calling it "the
neighbourhood" is how a search misses half the map.

WHAT EACH DOOR COSTS, because they are not interchangeable
----------------------------------------------------------
`etsy_suggest` is free and public. `pinterest_prefix` is free of the Etsy seller
account and carries a **52-week momentum series per term at no extra call**.
`etsy_expand` spends the operator's own seller session (D-29) and is the only one
that returns volume and supply inline. So the cheap doors find candidates and the
expensive one sizes them — never the reverse.

THE COMBINE RULES
-----------------
    any        union — every term any door returned. Widest net.
    all        intersection — only terms EVERY consulted door returned.
    min_n      terms at least N doors agree on. `all` is min_n at N=len(sources).

Agreement is a real signal: a term both Etsy's search box and Pinterest's
autocomplete know is corroborated by two independent populations. But it is a
signal about **vocabulary**, never about winnability — none of these doors
measures supply except `etsy_expand`, and a term everyone suggests can still be a
wall. Size before ranking.

⚠️ **A FAILED DOOR MUST NOT LOOK LIKE A DISAGREEING ONE.** This is the trap that
makes intersection dangerous: if Pinterest is down and the rule is `all`, the
intersection silently becomes "whatever Etsy said", or empty — and an empty result
reads as *"the doors disagree"* when it means *"we only asked one door"* (N-02).
So `combine()` computes agreement over **doors that actually answered**, reports
`sources_failed`, and REFUSES an `all`/`min_n` rule when a door it needed did not
answer, rather than quietly lowering the bar.
"""

# What each door is, what it costs, and what it returns. Kept as data so a caller
# can show the operator the price before spending it.
DOORS = {
    "etsy_suggest": {
        "tier": "etsy_public", "cost": "2 public requests",
        "spends_seller_account": False,
        "returns": "children — longer queries buyers actually type",
        "sized": False,
    },
    "etsy_expand": {
        "tier": "etsy_private", "cost": "1 expansion (~10 requests, 0 if cached)",
        "spends_seller_account": True,
        "returns": "siblings — same-level neighbours from Etsy's LLM expansion",
        "sized": True,
    },
    "pinterest_prefix": {
        "tier": "pinterest", "cost": "1 request",
        "spends_seller_account": False,
        "returns": "neighbours in Pinterest's vocabulary, each with 52 weeks of momentum",
        "sized": False,
    },
}


def _norm(term):
    return " ".join((term or "").lower().split())


def combine(results, mode="any", min_n=None, failed=()):
    """Merge per-door term lists into one candidate set with provenance.

    `results` is `{door: [term, ...]}` for doors that ANSWERED. `failed` names doors
    that were asked and did not, so an intersection can refuse rather than pretend.

    Every candidate carries `found_by` and `source_count`. Nothing is scored here —
    agreement is about vocabulary, not merit, and conflating the two would put a
    consensus wall above a lone winner.
    """
    answered = [d for d in results if d not in failed]
    if not answered:
        return {"candidates": [], "basis": "no_source_answered",
                "sources_ok": [], "sources_failed": list(failed),
                "note": "Every door failed. This is NOT 'the seed has no neighbours' "
                        "— nobody answered (N-02)."}

    seen = {}
    for door in answered:
        for term in results.get(door) or []:
            key = _norm(term)
            if not key:
                continue
            row = seen.setdefault(key, {"term": term, "found_by": []})
            if door not in row["found_by"]:
                row["found_by"].append(door)

    need = 1
    if mode == "all":
        need = len(answered)
    elif mode == "min_n":
        need = int(min_n or 1)
    elif mode != "any":
        return {"candidates": [], "basis": "bad_mode",
                "note": f"mode '{mode}' is not one of any / all / min_n"}

    # ⚠️ The refusal that makes intersection safe. With a door missing, `all` would
    # quietly mean "all the doors that happened to work" — a weaker claim wearing a
    # stronger name, and the result would be indistinguishable from real consensus.
    if failed and mode in ("all", "min_n"):
        return {
            "candidates": [], "basis": "refused_incomplete_sources",
            "sources_ok": answered, "sources_failed": list(failed),
            "note": (f"mode '{mode}' needs agreement across doors, and "
                     f"{sorted(failed)} did not answer. Agreeing over the survivors "
                     f"would report a weaker claim under a stronger name — and an "
                     f"empty intersection would read as 'the doors disagree' when it "
                     f"means 'we did not ask them all'. Retry, or use mode='any'."),
        }

    out = [{**r, "source_count": len(r["found_by"])}
           for r in seen.values() if len(r["found_by"]) >= need]
    # Most-corroborated first, then alphabetical so the order is stable across runs
    # (a shifting order between identical calls reads as new information).
    out.sort(key=lambda r: (-r["source_count"], r["term"]))

    overlap = sum(1 for r in seen.values() if len(r["found_by"]) > 1)
    return {
        "candidates": out,
        "returned": len(out),
        "pool_before_rule": len(seen),
        "sources_ok": answered,
        "sources_failed": list(failed),
        "mode": mode,
        "required_sources": need,
        "corroborated": overlap,
        "basis": "measured",
        "note": ("Agreement is about VOCABULARY, not winnability. None of these doors "
                 "measures supply except etsy_expand, so a term every door suggests "
                 "can still be a wall — size with `compare` before ranking anything. "
                 f"{overlap} of {len(seen)} terms were returned by more than one door."),
    }


def _door_etsy_suggest(seed, api=None):
    """Etsy's search box. PUBLIC — 2 requests, no seller cost."""
    from etsy.api.public.api import EtsyPublicAPI
    data = (api or EtsyPublicAPI()).get_search_suggestions(seed)
    if data is None:
        return None                      # None = did not answer. [] = answered, nothing.
    return data.get("suggestions") or []


def _door_etsy_expand(seed, api=None, max_nodes=200):
    """Etsy's LLM expansion. SPENDS THE SELLER ACCOUNT — one expansion.

    The only door that returns volume and supply inline, which is why the sized
    rows are handed back separately: a caller that already has them should not pay
    `compare` to measure them again.
    """
    from etsy.analytics import keyword_crawl as kc
    from etsy.api.private.api import EtsyPrivateAPI
    nodes = kc.crawl(api or EtsyPrivateAPI(), seed, max_nodes=max_nodes, max_depth=1)
    return [n["term"] for n in nodes if _norm(n.get("term")) != _norm(seed)]


def _door_pinterest_prefix(seed, api=None):
    """Pinterest's autocomplete. One request, and every term carries 52 weeks of
    momentum at no extra `/metrics/` call — the cheapest signal on the surface.

    ⚠️ The counts are OLDEST-FIRST (verified 2026-09-01: `halloween nails` peaks at
    index 5 ≈ Oct 2025 then flatlines and ramps again at the tail). That is the
    OPPOSITE of `moment_metrics`, whose series arrives newest-first — so the two
    Pinterest series cannot be read the same way, and the last value here is now.

    ⚠️ Counts are peak-normalised 0-100 WITHIN this response. Comparable to
    themselves over time, never to another response's numbers.
    """
    from pinterest.endpoints.api import PinterestTrendsAPI
    rows = (api or PinterestTrendsAPI(store=False)).prefix_match(seed)
    if rows is None:
        return None
    return [r.get("term") for r in rows if r.get("term")]


DOOR_FETCHERS = {
    "etsy_suggest": _door_etsy_suggest,
    "etsy_expand": _door_etsy_expand,
    "pinterest_prefix": _door_pinterest_prefix,
}


def discover_terms(seed, sources=("etsy_suggest", "pinterest_prefix"),
                   mode="any", min_n=None, fetchers=None):
    """Open the named doors on one seed and combine them under a stated rule.

    Defaults to the two FREE doors — Etsy's public search box and Pinterest — so
    the cheap answer is the one you get without asking. `etsy_expand` is opt-in
    because it is the only one that spends the seller account (D-29).

    A door that raises is recorded as failed, never as empty: those are different
    claims and only one of them is about the market.
    """
    fetchers = fetchers or DOOR_FETCHERS
    unknown = [s for s in sources if s not in fetchers]
    if unknown:
        return {"candidates": [], "basis": "unknown_source",
                "note": f"no such door: {unknown}. Known: {sorted(fetchers)}"}

    results, failed, errors = {}, [], {}
    for door in sources:
        try:
            got = fetchers[door](seed)
        except Exception as e:                      # a door that raises is not a door
            got, errors[door] = None, f"{type(e).__name__}: {e}"
        if got is None:
            failed.append(door)
        else:
            results[door] = got

    out = combine(results, mode=mode, min_n=min_n, failed=failed)
    out["seed"] = seed
    out["per_source_count"] = {d: len(v) for d, v in results.items()}
    out["cost"] = {d: DOORS[d]["cost"] for d in sources if d in DOORS}
    out["spends_seller_account"] = sorted(
        d for d in sources if DOORS.get(d, {}).get("spends_seller_account"))
    if errors:
        out["errors"] = errors
    return out


# Above this the sizing call refuses rather than trims, so the pipeline must cut the
# candidate list itself — and SAY what it cut. A cap applied in silence reads as
# "this is the whole neighbourhood" when it is a slice, which is the same error the
# drill made at max_nodes=60.
DEFAULT_SIZE_LIMIT = 24


def hunt(seed, sources=("etsy_suggest", "pinterest_prefix"), mode="any",
         min_n=None, size_mode="cheap", limit=DEFAULT_SIZE_LIMIT,
         fetchers=None, sizer=None):
    """Discover terms across doors, size them, rank them — one call, one table.

    The whole strategy in order: cheap doors find candidates, the private tier sizes
    only the survivors, and the gates rank what is left. Running it the other way —
    sizing everything, then filtering — spends the seller account on terms that were
    never going to matter.

    Returns `compare`'s table with each row carrying the `found_by` / `source_count`
    provenance from discovery, so "two independent populations use this word" and
    "it is winnable" stay visible as SEPARATE facts. They answer different questions
    and a term can pass one while failing the other.
    """
    from etsy.analytics.compare import compare as _compare

    found = discover_terms(seed, sources=sources, mode=mode, min_n=min_n,
                           fetchers=fetchers)
    cands = found.get("candidates") or []
    if not cands:
        # Discovery failing and discovery finding nothing are different claims, and
        # `basis` already carries which. Do not spend a sizing call on either.
        return {**found, "rows": [], "ranked": None,
                "note": f"{found.get('note', '')} Nothing was sized — "
                        f"no candidate survived discovery."}

    keep = cands[:limit]
    dropped = cands[len(keep):]
    # Ordered by corroboration, so a cut takes the least-corroborated first — but it
    # is still a cut, and the dropped terms are named rather than counted so the
    # operator can re-run on them.
    sized = (sizer or _compare)(",".join(c["term"] for c in keep), mode=size_mode)
    if not sized.get("ok"):
        return {**found, "rows": [], "ranked": None,
                "sizing_error": sized.get("error"),
                "note": "Discovery succeeded; SIZING failed. The candidates below are "
                        "real, they are simply unmeasured — not walls."}

    prov = {_norm(c["term"]): c for c in keep}
    rows = []
    for row in sized.get("rows") or []:
        p = prov.get(_norm(row.get("term"))) or {}
        rows.append({**row,
                     "found_by": p.get("found_by", []),
                     "source_count": p.get("source_count")})

    return {
        "seed": seed, "rows": rows, "ranked": sized.get("ranked"),
        "rankable": sized.get("rankable"), "floors": sized.get("floors"),
        "discovery": {k: found.get(k) for k in
                      ("sources_ok", "sources_failed", "per_source_count",
                       "corroborated", "mode", "required_sources", "basis")},
        "sized": len(rows),
        "found_total": len(cands),
        "not_sized": [c["term"] for c in dropped],
        "size_limit": limit,
        "spent": {"discovery": found.get("cost"),
                  "sizing_private_requests_upper_bound":
                      (sized.get("spent") or {}).get("private_requests_upper_bound"),
                  "spends_seller_account": found.get("spends_seller_account", [])
                                           + (["compare"] if rows else [])},
        "basis": "measured",
        "note": ("Provenance and winnability are SEPARATE facts on every row: "
                 "`found_by` says which populations use the word, the verdict says "
                 "whether you could rank for it. A term both doors know can still be "
                 "a wall. "
                 + (f"⚠️ {len(dropped)} candidate(s) were NOT sized — over the "
                    f"limit of {limit}. They are named in `not_sized`, least "
                    f"corroborated first; re-run on them rather than assuming they "
                    f"were worse." if dropped else "Every candidate was sized.")),
    }

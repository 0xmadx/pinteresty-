"""Opportunity scoring — percentile-normalized, profit-centred.

This replaces three divergent formulas that all ranked on demand-over-supply and none of
which included a cost term:

    master_niche_finder.py:66        (volume / listings) * 1000
    private_scoring_pipeline.py:117  volume / supply
    master_arbitrage.py:85           count / total * 100, seven times

`DECISION_LOG.md` D-02 explains why multiplying raw values is wrong: the original
`(Demand x Momentum x Intent) / (Supply x SERP)` multiplied Etsy absolute counts in the
thousands by Pinterest 0-100 indices, so whichever variable had the biggest raw range
silently dominated the result. The fix is to convert every variable to its **percentile
rank within the pool** and take a weighted sum.

Rejected alternatives, per D-02: z-scores (the distributions are skewed and full of
sentinels) and min-max scaling (one outlier destroys it).

Two consequences that shape this module:

  * **A percentile is meaningless without its pool.** Every score carries `pool_id` and
    `pool_size`, and a pool below `MIN_POOL_SIZE` is refused rather than scored.
  * **Profit is a scored variable, not an afterthought.** D-01. A candidate below its
    product type's margin floor is a no-go however well it ranks on everything else.

Missing inputs are not treated as zero. A zero percentile says "worst in the pool", which
is a claim; a missing value is the absence of one. Missing dimensions are dropped from the
weighting and reported in `missing`, and `confidence` falls accordingly — `GOAL.md:67`
requires low confidence to say so rather than look authoritative.

Pure functions. No I/O.
"""
from dataclasses import dataclass, field

from etsy.analytics.freshness import freshness_floor, freshness_tag

WEIGHTS_VERSION = 1

# Below this a percentile carries no information: with two candidates every value is
# either 0.0 or 1.0. REPO_STRUCTURE_AND_CONFIG.md:130-133 sets it.
MIN_POOL_SIZE = 3

# A small pool can be large enough to score and still fail to discriminate. With n=3 the
# only available percentiles are {0.0, 0.5, 1.0}, so a candidate that is best on some
# dimensions and worst on others cancels out to the pool mean — and every candidate can
# land on an identical score while the ranking looks meaningful.
#
# Observed on the first real three-way run: all three candidates scored exactly 0.500 and
# the margin-floor gate did all the ordering. That is not wrong, but a reader would take
# 0.500 for a judgement rather than an artefact, so it is flagged.
DEGENERATE_SPREAD = 0.05

# True  = a bigger raw number is a better opportunity
# False = a bigger raw number is worse, so the percentile is inverted
DIMENSIONS = {
    "demand": True,       # Etsy search volume
    "momentum": True,     # Pinterest growth
    "intent": True,       # conversion rate
    "profit": True,       # achievable weekly profit, from profit.py
    "supply": False,      # competing listings
    "serp_difficulty": False,   # how strong the incumbents are
}

DEFAULT_WEIGHTS = {
    "demand": 0.20,
    "momentum": 0.15,
    "intent": 0.15,
    "profit": 0.30,       # the largest single weight, by D-01
    "supply": 0.10,
    "serp_difficulty": 0.10,
}


class PoolTooSmall(ValueError):
    """Raised rather than returning a number that cannot mean anything."""


@dataclass
class Scored:
    key: str
    score: float
    percentiles: dict = field(default_factory=dict)
    missing: tuple = ()
    confidence: float = 1.0
    go: bool = True
    reasons: tuple = ()
    pool_id: str = ""
    pool_size: int = 0
    weights_version: int = WEIGHTS_VERSION
    # B-10: the age this score inherits — the oldest collected_at among its inputs, and
    # the plain tag derived from it. None/"unknown" when no input carried a timestamp,
    # which is a distinct state from fresh.
    freshness_floor: str = None
    freshness: str = "unknown"


def percentile_ranks(values):
    """Map each value to its rank within the list, scaled to 0.0-1.0.

    `None` maps to `None` and is excluded from the ranking entirely — it must not become
    a 0.0, which would assert "worst in the pool" about a value nobody measured.

    Ties share the average of the ranks they span, so three identical values all land
    mid-pack instead of one arbitrarily winning.
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if not present:
        return [None] * len(values)
    if len(present) == 1:
        out = [None] * len(values)
        out[present[0][0]] = 0.5      # a lone value is neither best nor worst
        return out

    ordered = sorted(present, key=lambda p: p[1])
    n = len(ordered)
    out = [None] * len(values)

    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        # average rank across the tie group, scaled so the worst is 0 and the best is 1
        avg_rank = (i + j) / 2.0
        pct = avg_rank / (n - 1)
        for k in range(i, j + 1):
            out[ordered[k][0]] = round(pct, 6)
        i = j + 1
    return out


def score_pool(candidates, weights=None, pool_id="default", min_pool_size=MIN_POOL_SIZE,
               now=None):
    """Score a pool of candidates against each other. Returns `Scored`, best first.

    `candidates` is a list of dicts with a `key` plus any of DIMENSIONS. Optional keys:
      margin        — from profit.unit_economics; compared against margin_floor
      margin_floor  — from profit.verdict
      capacity_bound— from profit.verdict; recorded, never silently ignored
      freshness     — dict of dimension -> collected_at (ISO). B-10: the score inherits
                      the oldest timestamp among the dimensions it actually used, and a
                      KNOWN-stale floor halves confidence. Omit it and scoring is
                      time-blind exactly as before — a value that never claimed a
                      freshness is not penalised for lacking one.

    Scores are only comparable **within one pool**. Two candidates scored in different
    pools cannot be ranked against each other, which is what pool_id records.
    """
    weights = weights or DEFAULT_WEIGHTS
    n = len(candidates)
    if n < min_pool_size:
        raise PoolTooSmall(
            f"pool '{pool_id}' has {n} candidate(s); percentiles need at least "
            f"{min_pool_size}. Widen the pool or compare raw values instead.")

    unknown = set(weights) - set(DIMENSIONS)
    if unknown:
        raise ValueError(f"unknown scoring dimension(s): {sorted(unknown)}")

    # Percentile each dimension across the whole pool before any candidate is scored.
    ranked = {}
    for dim, higher_is_better in DIMENSIONS.items():
        if dim not in weights:
            continue
        col = percentile_ranks([c.get(dim) for c in candidates])
        if not higher_is_better:
            col = [None if p is None else round(1.0 - p, 6) for p in col]
        ranked[dim] = col

    results = []
    for i, cand in enumerate(candidates):
        present, missing = {}, []
        for dim in ranked:
            p = ranked[dim][i]
            (present.__setitem__(dim, p) if p is not None else missing.append(dim))

        available_weight = sum(weights[d] for d in present)
        if available_weight <= 0:
            score = 0.0
            confidence = 0.0
        else:
            # Redistribute across the dimensions we actually have, so a candidate missing
            # one input is not penalised as though it scored zero there.
            score = sum(present[d] * weights[d] for d in present) / available_weight
            confidence = round(available_weight / sum(weights.values()), 4)

        reasons = []
        go = True
        margin, floor = cand.get("margin"), cand.get("margin_floor")
        if margin is not None and floor is not None and margin < floor:
            go = False
            reasons.append(f"margin {margin:.1%} below the {floor:.0%} floor")
        if cand.get("capacity_bound"):
            reasons.append("capacity-bound: more demand will not raise achievable profit")
        if missing:
            reasons.append(f"missing input(s): {', '.join(sorted(missing))}")

        # B-10: the floor is the oldest timestamp among the dimensions this candidate
        # ACTUALLY used — a stale input for a dimension that was missing (and so excluded
        # from the score) does not drag the composite's freshness down.
        ts_map = cand.get("freshness") or {}
        used_timestamps = [ts_map[d] for d in present if d in ts_map]
        floor_ts = freshness_floor(*used_timestamps) if used_timestamps else None
        tag = freshness_tag(floor_ts, now=now)
        if tag == "stale":
            confidence = round(confidence * 0.5, 4)
            reasons.append(f"stale: oldest input is {floor_ts} — the score spans that "
                           f"much time and may already have moved")

        results.append(Scored(
            key=cand.get("key", f"candidate_{i}"),
            score=round(score, 6),
            percentiles=present,
            missing=tuple(sorted(missing)),
            confidence=confidence,
            go=go,
            reasons=tuple(reasons),
            pool_id=pool_id,
            pool_size=n,
            freshness_floor=floor_ts,
            freshness=tag,
        ))

    # A pool can clear min_pool_size and still produce scores too close together to mean
    # anything. Say so on every result rather than letting a tied score read as a verdict.
    spread = max(r.score for r in results) - min(r.score for r in results)
    if spread < DEGENERATE_SPREAD:
        note = (f"scores span only {spread:.3f} across {n} candidates — the ranking below "
                f"is not discriminating; widen the pool before trusting the order")
        for r in results:
            r.reasons = r.reasons + (note,)
            r.confidence = round(r.confidence * 0.5, 4)

    # go-first, then score. A no-go never outranks a go, however high it scores — the
    # margin floor is a gate, not another weighted term.
    return sorted(results, key=lambda r: (r.go, r.score), reverse=True)


@dataclass(frozen=True)
class Discrimination:
    """Whether a ranking over this pool could carry information at all."""
    ok: bool
    reason: str
    dimensions: tuple = ()
    spread: float = None


def _available_dimensions(candidates, weights):
    """Dimensions that are weighted AND actually populated for 2+ candidates.

    A dimension present in the weights but None everywhere is not a dimension — it is a
    column of holes. Counting it makes a two-dimensional pool look four-dimensional and
    hides exactly the degeneracy this module exists to catch.
    """
    out = []
    for dim in weights:
        if dim not in DIMENSIONS:
            continue
        values = [c.get(dim) for c in candidates]
        if sum(1 for v in values if v is not None) >= 2:
            out.append(dim)
    return tuple(out)


def can_discriminate(candidates, weights=None, sample_spread=DEGENERATE_SPREAD):
    """Ask BEFORE scoring whether these dimensions could ever separate this pool.

    N-01. `score_pool` detects a flat result after the fact and annotates it, which is
    honest but late: by then a caller has an ordered list and will use it. This answers
    the prior question — is a ranking even possible here — so a caller can fall back to
    a stated filter instead of presenting an arbitrary order as a judgement.

    The killer case is two dimensions at equal weight with one inverted. Percentile ranks
    of perfectly rank-correlated inputs are p and (1-p), so the weighted sum is exactly
    0.5 for every candidate no matter how many there are. Etsy data has that shape by
    nature: popular keywords carry more listings.

    Returns a Discrimination, never a bare bool, so the reason travels with the answer.
    """
    weights = weights or DEFAULT_WEIGHTS
    if len(candidates) < 2:
        return Discrimination(False, "a pool of fewer than 2 cannot be ranked at all")

    dims = _available_dimensions(candidates, weights)
    if not dims:
        return Discrimination(False, "no weighted dimension is populated", dims)
    if len(dims) == 1:
        # One dimension always orders — there is nothing for it to cancel against.
        return Discrimination(True, f"single dimension '{dims[0]}' orders the pool", dims)

    # Score the pool with only the available dimensions and measure the real spread.
    # Cheaper and more truthful than reasoning about correlations analytically: it asks
    # the actual arithmetic what it produces.
    sub = {d: weights[d] for d in dims}
    try:
        scored = score_pool(candidates, weights=sub, pool_id="discrimination-probe",
                            min_pool_size=2)
    except PoolTooSmall as exc:
        return Discrimination(False, str(exc), dims)

    spread = max(s.score for s in scored) - min(s.score for s in scored)
    if spread < sample_spread:
        return Discrimination(
            False,
            f"dimensions {list(dims)} are rank-correlated in this pool — every "
            f"candidate scores within {spread:.4f} of the others, so the order carries "
            f"no information",
            dims, round(spread, 6))
    return Discrimination(True, f"dimensions {list(dims)} separate the pool "
                                f"(spread {spread:.3f})", dims, round(spread, 6))


@dataclass(frozen=True)
class Shortlisted:
    key: str
    reason: str
    selection: str = "filter"   # never "ranking" — this is not an ordering by merit


def shortlist(candidates, limit=3):
    """Select candidates by a STATED rule when ranking is impossible.

    Used where `can_discriminate` says no. The rule is deliberately crude and explicit:
    prefer supply below the pool median, then take the highest demand among those. It is
    a filter for "worth spending a metered deep-dive call on", not a claim that the first
    is better than the third.

    `selection="filter"` is on every result so a caller cannot quietly present these as
    ranked. Ties report that their relative order is arbitrary, because it is.
    """
    if not candidates:
        return []

    supplies = sorted(c.get("supply") for c in candidates if c.get("supply") is not None)
    median = supplies[len(supplies) // 2] if supplies else None

    def sort_key(c):
        below = 0 if (median is not None and (c.get("supply") or 0) <= median) else 1
        return (below, -(c.get("demand") or 0))

    ordered = sorted(candidates, key=sort_key)[:limit]

    # If every pick shares the same key, no rule distinguished them and saying otherwise
    # would be the N-01 error in miniature.
    keys = {sort_key(c) for c in ordered}
    tied = len(keys) == 1 and len(ordered) > 1

    out = []
    for c in ordered:
        below = median is not None and (c.get("supply") or 0) <= median
        reason = (f"supply {c.get('supply')} {'at or below' if below else 'above'} the "
                  f"pool median {median}, demand {c.get('demand')}")
        if tied:
            reason += " — tied with the others; the order among them is arbitrary"
        out.append(Shortlisted(key=c.get("key"), reason=reason))
    return out


def explain(scored, weights=None):
    """One human-readable line per dimension: why this candidate ranked where it did.

    D-02 lists interpretability as the reason percentiles were chosen over a raw product,
    so being able to answer "why" is part of the design, not a debugging extra.
    """
    weights = weights or DEFAULT_WEIGHTS
    lines = [f"{scored.key}: score {scored.score:.3f} "
             f"(pool {scored.pool_id}, n={scored.pool_size}, "
             f"confidence {scored.confidence:.0%}, weights v{scored.weights_version})"]
    for dim, pct in sorted(scored.percentiles.items(), key=lambda kv: -kv[1] * weights[kv[0]]):
        lines.append(f"    {dim:16} p{pct * 100:5.1f}  x weight {weights[dim]:.2f} "
                     f"= {pct * weights[dim]:.4f}")
    for d in scored.missing:
        lines.append(f"    {d:16} MISSING — excluded from the weighting")
    for r in scored.reasons:
        lines.append(f"    ! {r}")
    return "\n".join(lines)

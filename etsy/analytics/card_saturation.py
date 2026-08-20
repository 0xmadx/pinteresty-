"""Saturation measured from listings, not from filter counts.

The filter audit (D-32) left three trustworthy SERP filters out of twelve. The
dimensions it took away — star seller, free shipping, discounting, rating — are
not gone from the data, only from the *filters*. Every one of them is a field on
the SERP cards this system already fetches, so it can be counted directly instead
of being asked for.

That is a strictly better measurement in kind: a filter count is a number Etsy
returns about a result set that may not be a subset of this market, while a card
count is something we observed about listings we can name.

AND IT IS STILL USUALLY NOT ENOUGH.

Only 12 slots render server-side and roughly half are ads, so the organic sample
is 6–11 listings. A share from 6 observations has a 95% interval so wide it spans
both the "thin" (5%) and "crowded" (30%) thresholds at once, which means it cannot
tell them apart — the same reason `scoring.can_discriminate()` refuses to rank a
pool whose dimensions cannot separate it.

So this module measures honestly and then **refuses to produce a verdict it cannot
support**. `share` always comes with `low`/`high` bounds and the sample size, and
`can_discriminate()` says whether the interval is tight enough to place the
bracket on either side of a threshold. A caller that ignores that and reads
`share` alone gets the plausible wrong number this codebase exists to prevent.

THE UPGRADE PATH, NOW THAT IT EXISTS
------------------------------------
`organic_listing_ids` used to come back empty on every page — a parser bug fixed
on 2026-08-20 — and now returns the full ranked list (41 ids on "personalized
towel"). Fetching those listing pages gives a sample of 40+ instead of 6, at one
request each. That is the affordable version of "measure it per listing", and it
is what tightens these intervals from useless to decisive.
"""
from math import sqrt

# Wilson score interval. Chosen over the textbook normal approximation because at
# n=6 the normal one produces bounds below 0 and above 1, which would be a
# confidence interval that is itself impossible.
Z = 1.96


def wilson(successes, n, z=Z):
    """95% interval for a proportion. (low, high), or None when n is 0."""
    if not n:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4))


def _organic(cards):
    return [c for c in (cards or []) if not c.get("is_ad")]


def measure(cards, predicate, thin=0.05, crowded=0.30):
    """Share of organic listings matching `predicate`, with its uncertainty.

    Cards whose field is absent are excluded from BOTH numerator and denominator
    (N-02): a listing whose rating did not parse is not a listing without a
    rating, and counting it as a miss would understate every share.
    """
    organic = _organic(cards)
    judged = [c for c in organic if predicate(c) is not None]
    hits = sum(1 for c in judged if predicate(c))
    n = len(judged)

    bounds = wilson(hits, n)
    share = round(hits / n, 4) if n else None
    return {
        "matched": hits, "sample": n,
        "excluded_unmeasured": len(organic) - n,
        "share": share,
        "low": bounds[0] if bounds else None,
        "high": bounds[1] if bounds else None,
        "basis": "measured, SAMPLE of the top of page one — NOT a market share",
        "can_discriminate": _discriminates(bounds, thin, crowded),
    }


def _discriminates(bounds, thin, crowded):
    """Is the interval tight enough to place this bracket on one side of a line?

    False when the interval straddles a threshold — the honest reading of "we
    measured it and still cannot tell". This is the same refusal
    `scoring.can_discriminate()` makes: a dimension that cannot separate the pool
    must not be used to rank it.
    """
    if not bounds:
        return False
    low, high = bounds
    for threshold in (thin, crowded):
        if low < threshold < high:
            return False
    return True


# The dimensions the filter audit took away, each recoverable from a card field.
# `None` from a predicate means UNMEASURED for that listing, not False.
PREDICATES = {
    ("quality", "star_seller"): lambda c: c.get("star_seller"),
    ("free_shipping", "true"): lambda c: c.get("free_shipping"),
    ("discount", "true"): lambda c: (None if c.get("percent_discount") is None
                                     and c.get("original_price") is None
                                     else bool(c.get("percent_discount"))),
    # `min_rating=5` is one of the filters Etsy silently ignores — it returns 4.8
    # and 4.9 listings. Counted here instead, from the ratings actually shown.
    ("quality", "5_star"): lambda c: (None if c.get("rating") is None
                                      else c["rating"] >= 4.95),
}


def profile(cards, thin=0.05, crowded=0.30):
    """Every recoverable dimension at once, from one already-fetched SERP."""
    return {key: measure(cards, pred, thin, crowded)
            for key, pred in PREDICATES.items()}


def usable_brackets(measured):
    """The subset that can support a verdict: {(dimension, value): (matched, sample)}.

    Only brackets whose interval discriminates survive. Everything else is
    measured and reported but withheld from the gap analysis, because a share that
    cannot be placed against a threshold cannot classify against it either.
    """
    return {key: (m["matched"], m["sample"])
            for key, m in measured.items() if m["can_discriminate"]}


def read(measured):
    """Plain-language lines. Says the sample size every time, without exception."""
    out = []
    for (dimension, value), m in measured.items():
        name = f"{dimension}={value}"
        if not m["sample"]:
            out.append(f"{name}: no listing reported this field — unmeasured")
            continue
        line = (f"{name}: {m['matched']}/{m['sample']} of the listings a buyer sees "
                f"first ({m['share']:.0%}, but anywhere from {m['low']:.0%} to "
                f"{m['high']:.0%} on this sample)")
        if not m["can_discriminate"]:
            line += " — too few listings to call this thin or crowded"
        if m["excluded_unmeasured"]:
            line += f"; {m['excluded_unmeasured']} excluded as unmeasured"
        out.append(line)
    return out

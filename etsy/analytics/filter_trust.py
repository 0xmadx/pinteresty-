"""Which public SERP filters can be believed — measured, recorded, and enforced.

WHY THIS EXISTS
---------------
On 2026-08-19 `locationQuery` was found to return a BROADER result set than the
search it filters. On "monogrammed waffle weave towel" (10,011 listings) it
reported Germany at 28,271 and seven countries summing to 1116% of the market
they claim to partition. Every number was real, well-formed, and meaningless as
a share. `master_arbitrage` had been feeding exactly those counts to `find_gaps`
as "geographic" brackets for the life of the project.

That was caught by hand. Eleven other filters feed the same gap analysis and had
never been checked. This module makes the check systematic and its result
binding: a filter is not trusted because it exists, but because it passed.

WHAT "TRUSTED" MEANS
--------------------
A filter narrows a search. So for a query with N unfiltered results, a filtered
count `n` must satisfy:

    n <= N                 it is a SUBSET
    n != N                 it actually filtered something (unless it truly matches all)
    sum(n_i) <= N          mutually exclusive values partition, they do not overlap

Failing any of these does not make the number wrong — it makes it *not a share*,
which is worse, because a share is exactly how the gap analysis reads it.

STATUSES
--------
    trusted        behaves as a subset across every probe
    not_a_subset   returned more than the unfiltered total, or values oversum
    ignored        returned exactly the unfiltered total on every probe
    unstable       passed on some queries and failed on others
    unverified     never probed — treated as untrusted by find_gaps

`unverified` is the default, and it is deliberately not the same as `trusted`.
Absence of evidence is the thing that let locationQuery run for a year.
"""
import json
import os
import time
from dataclasses import asdict, dataclass, field

TRUSTED = "trusted"
NOT_A_SUBSET = "not_a_subset"
IGNORED = "ignored"
UNSTABLE = "unstable"
UNVERIFIED = "unverified"

# Only a trusted filter may produce a gap bracket.
USABLE = (TRUSTED,)

REGISTRY_PATH = os.path.join("config", "filter_trust.json")

# `organic_listings_count` is an ESTIMATE, not a count. Measured 2026-08-19 by
# repeating identical unfiltered searches: "personalized towel" returned 217,196 /
# 217,196 / 217,395 — a 199-listing swing — and "printable wall art" drifted by one
# listing across three calls. So a filtered count that lands a hair above the
# unfiltered total is jitter, NOT a broken filter, and an exact-equality test for
# "ignored" misses a filter that was ignored but sampled a moment later.
#
# 2% is generous against the ~0.1% observed drift. It is set wide on purpose: the
# cost of calling a working filter untrusted is a lost dimension, while the cost of
# trusting a broken one is a wrong verdict the operator acts on.
COUNT_JITTER = 0.02

# How long a verdict stands before it should be re-measured. Etsy changes its
# SERP; a filter that partitioned correctly in August may not in December.
STALE_AFTER_DAYS = 90

# The filters master_arbitrage actually sends. `values` are the ones probed;
# `exclusive` marks sets whose values should not overlap, so their counts may be
# summed and compared against the total.
FILTER_SPECS = {
    "is_digital":        {"values": ["1"], "exclusive": False},
    "is_star_seller":    {"values": ["1"], "exclusive": False},
    "best_by_etsy":      {"values": ["1"], "exclusive": False},
    "min_rating":        {"values": ["5"], "exclusive": False},
    "is_personalizable": {"values": ["true"], "exclusive": False},
    "is_discounted":     {"values": ["true"], "exclusive": False},
    "free_shipping":     {"values": ["true"], "exclusive": False},
    "gift_wrap":         {"values": ["true"], "exclusive": False},
    "holiday":           {"values": ["halloween", "christmas"], "exclusive": False},
    # Cumulative, not exclusive: <=14 contains <=7. Verified sound 2026-08-19.
    "delivery_days":     {"values": ["7", "14", "21", "30"], "exclusive": False,
                          "cumulative": True},
    # A listing has one primary colour, so these should partition. attr_1 ids are
    # Etsy's colour taxonomy.
    "attr_1":            {"values": ["1", "2", "3", "4", "5", "6", "7"],
                          "exclusive": True},
    # Known bad — kept in the registry so the reason is recorded, not forgotten.
    "locationQuery":     {"values": ["6252001", "2635167", "2921044"],
                          "exclusive": True},
}


@dataclass
class FilterVerdict:
    name: str
    status: str = UNVERIFIED
    checked_at: float = None
    queries: tuple = field(default_factory=tuple)
    evidence: tuple = field(default_factory=tuple)
    note: str = ""

    @property
    def usable(self):
        return self.status in USABLE

    @property
    def stale(self):
        if not self.checked_at:
            return True
        return (time.time() - self.checked_at) > STALE_AFTER_DAYS * 86400


def classify(observations, cumulative=False, exclusive=False, jitter=COUNT_JITTER):
    """Turn raw (total, {value: count}) observations into one status.

    `observations` is a list of (total, counts) — one entry per probe query. Pure
    function: every live call happens in probe(), so the rule is testable offline
    and can be re-run over stored evidence without touching the network.
    """
    if not observations:
        return UNVERIFIED, "no probes ran"

    verdicts, reasons = set(), []
    for total, counts in observations:
        measured = {k: v for k, v in counts.items() if v is not None}
        if not total or not measured:
            continue

        ceiling = total * (1 + jitter)

        # Genuinely more than the market. Not estimation noise — a different set.
        over = {k: v for k, v in measured.items() if v > ceiling}
        if over:
            worst = max(over.items(), key=lambda kv: kv[1])
            verdicts.add(NOT_A_SUBSET)
            reasons.append(f"{worst[0]}={worst[1]} exceeds unfiltered {total} "
                           f"by {worst[1] / total - 1:.0%}")
            continue

        # Within jitter of the total is the SAME result set, arriving with a
        # slightly different estimate. min_rating=5 did exactly this while
        # returning 4.8- and 4.9-rated listings.
        if all(abs(v - total) <= total * jitter for v in measured.values()):
            verdicts.add(IGNORED)
            reasons.append(f"every value returned the unfiltered total (~{total})")
            continue

        # Cumulative filters must be monotonic. Summing them would manufacture a
        # false failure, since <=14 legitimately contains <=7.
        if cumulative:
            seq = [measured[v] for v in sorted(measured, key=lambda x: int(x))
                   if v.isdigit()]
            if seq != sorted(seq):
                verdicts.add(NOT_A_SUBSET)
                reasons.append(f"cumulative brackets are not monotonic: {seq}")
                continue

        # Exclusive values partition the market, so they may be summed. This is
        # the check that caught locationQuery — each value sat below the total and
        # only the SUM revealed the overlap.
        if exclusive and len(measured) > 1:
            s = sum(measured.values())
            if s > ceiling:
                verdicts.add(NOT_A_SUBSET)
                reasons.append(f"values sum to {s} ({s / total:.0%}) of {total}")
                continue

        verdicts.add(TRUSTED)

    if not verdicts:
        return UNVERIFIED, "no probe produced a usable total"
    if verdicts == {TRUSTED}:
        return TRUSTED, "subset on every probe"
    if len(verdicts) > 1 and TRUSTED in verdicts:
        # Passing sometimes is not passing. A filter that partitions on one query
        # and not another cannot be relied on for a query we have not run.
        bad = ", ".join(sorted(verdicts - {TRUSTED}))
        return UNSTABLE, f"passed some probes, {bad} on others: {'; '.join(reasons[:2])}"
    status = NOT_A_SUBSET if NOT_A_SUBSET in verdicts else IGNORED
    return status, "; ".join(reasons[:2])


def reclassify(path=REGISTRY_PATH, jitter=COUNT_JITTER):
    """Re-run the rule over evidence already stored. No network.

    The registry keeps every raw observation, so a change to the rule can be
    replayed against what was actually measured instead of re-probing Etsy —
    and a rule change that would flip a verdict is visible before it ships.
    """
    verdicts = load(path)
    changed = {}
    for name, v in verdicts.items():
        if not v.evidence:
            continue
        spec = FILTER_SPECS.get(name, {})
        obs = [(total, counts) for _, total, counts in v.evidence]
        status, note = classify(obs, spec.get("cumulative", False),
                                spec.get("exclusive", False), jitter)
        if status != v.status:
            changed[name] = (v.status, status)
        v.status, v.note = status, note
    save(verdicts, path)
    return verdicts, changed


# --- persistence -------------------------------------------------------------------------

def load(path=REGISTRY_PATH):
    """The registry as {name: FilterVerdict}. Unknown filters come back UNVERIFIED."""
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for name, d in (json.load(f).get("filters") or {}).items():
                d.pop("name", None)
                d["queries"] = tuple(d.get("queries") or ())
                d["evidence"] = tuple(tuple(e) if isinstance(e, list) else e
                                      for e in (d.get("evidence") or ()))
                out[name] = FilterVerdict(name=name, **d)
    for name in FILTER_SPECS:
        out.setdefault(name, FilterVerdict(name=name))
    return out


def save(verdicts, path=REGISTRY_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"updated_at": time.time(),
               "filters": {name: asdict(v) for name, v in sorted(verdicts.items())}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def trusted_names(path=REGISTRY_PATH):
    return {n for n, v in load(path).items() if v.usable and not v.stale}


def is_trusted(name, path=REGISTRY_PATH):
    v = load(path).get(name)
    return bool(v and v.usable and not v.stale)


# --- probing (live) -----------------------------------------------------------------------

def probe(public_api, name, spec, queries, pause=0.0):
    """Measure one filter against several queries. Returns a FilterVerdict."""
    observations, evidence = [], []
    for q in queries:
        base = public_api.get_public_search(q)
        total = (base or {}).get("total_results")
        if not total:
            continue
        counts = {}
        for value in spec["values"]:
            d = public_api.get_public_search(q, filters={name: value})
            counts[value] = (d or {}).get("total_results")
            if pause:
                time.sleep(pause)
        observations.append((total, counts))
        evidence.append((q, total, counts))

    status, note = classify(observations, spec.get("cumulative", False),
                            spec.get("exclusive", False))
    return FilterVerdict(name=name, status=status, checked_at=time.time(),
                         queries=tuple(queries), evidence=tuple(evidence), note=note)


def audit(public_api, queries, names=None, path=REGISTRY_PATH, pause=0.0, verbose=True):
    """Probe every filter and persist the registry. Returns {name: FilterVerdict}."""
    verdicts = load(path)
    for name, spec in FILTER_SPECS.items():
        if names and name not in names:
            continue
        v = probe(public_api, name, spec, queries, pause=pause)
        verdicts[name] = v
        if verbose:
            mark = "OK " if v.usable else "!! "
            print(f"  {mark}{name:18} {v.status:14} {v.note}")
    save(verdicts, path)
    return verdicts


def main():
    from etsy.api.public.api import EtsyPublicAPI

    # The mirror this project reads is only refreshed by preflight (D-33), and a CLI
    # run does not get the scheduler's copy of that. Sync-and-check first, or a stale
    # pool takes this audit down mid-sweep and the registry keeps yesterday's answer.
    from core.preflight import require
    require("etsy")

    # Deliberately unlike each other: a broad personalized physical term, a
    # narrow long-tail one, and a digital-heavy one. A filter that partitions
    # only on easy queries is not trusted.
    queries = ["personalized towel", "monogrammed waffle weave towel",
               "printable wall art"]
    print(f"Auditing {len(FILTER_SPECS)} filters against {len(queries)} queries...")
    verdicts = audit(EtsyPublicAPI(), queries)
    ok = sorted(n for n, v in verdicts.items() if v.usable)
    bad = sorted(n for n, v in verdicts.items() if not v.usable)
    print(f"\n  trusted ({len(ok)}): {', '.join(ok) or 'none'}")
    print(f"  NOT usable ({len(bad)}): {', '.join(bad) or 'none'}")
    print(f"\n  registry: {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# --- binding the registry to the gap analysis --------------------------------------------

# Which SERP filter produces each gap bracket. `find_gaps` uses this to refuse a
# bracket whose underlying filter did not pass the audit — the whole point of
# measuring trust is that something acts on it.
#
# Keyed by (dimension, value) where the value matters (quality asks three
# different filters), by dimension alone otherwise.
DIMENSION_FILTERS = {
    "format": "is_digital",
    "geographic": "locationQuery",
    "occasion": "holiday",
    "personalizable": "is_personalizable",
    "discount": "is_discounted",
    "free_shipping": "free_shipping",
    "gift_wrap": "gift_wrap",
    "shipping_speed": "delivery_days",
    "color": "attr_1",
}
QUALITY_FILTERS = {
    "star_seller": "is_star_seller",
    "etsys_pick": "best_by_etsy",
    "5_star": "min_rating",
}


def filter_for(dimension, value=None):
    """The SERP filter behind one gap bracket, or None if it is not filter-derived."""
    if dimension == "quality":
        return QUALITY_FILTERS.get(value)
    return DIMENSION_FILTERS.get(dimension)


def bracket_is_trusted(dimension, value=None, registry=None, path=REGISTRY_PATH):
    """May this bracket be classified at all?

    A bracket with no filter behind it (demand measured some other way) is trusted
    by default — this gate is about SERP filter counts, not about every number.
    """
    name = filter_for(dimension, value)
    if name is None:
        return True
    reg = registry if registry is not None else load(path)
    v = reg.get(name)
    return bool(v and v.usable and not v.stale)

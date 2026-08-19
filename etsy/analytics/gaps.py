"""Competition gap finder, with the empty-bracket gate.

`master_arbitrage.py:70-237` slices a keyword across seven dimensions and reports low
saturation as a loophole. `_old_etsy_master_architecture.md:42-43` states the goal as
finding "0% saturation loopholes" — which is the trap, written down as a feature.

`DECISION_LOG.md` D-10 is the correction:

    Context:  Slicing a market 7 ways always produces empty cells; the original design
              read 0% saturation as a loophole.
    Chosen:   Demand must be shown to hold *inside* the bracket; dimension sets are
              selected by product type.
    Rejected: Treating any 0% bracket as opportunity.

The worked example from D-10: shipping-speed arbitrage on a digital product returns a
guaranteed-empty bracket. There are no listings offering 7-day delivery on a download,
so saturation is 0% — and it means nothing at all. The old code would report that as the
single best opportunity in the run.

So a bracket becomes a gap only when **both** hold:
  1. the dimension applies to this product type at all, and
  2. demand has been demonstrated *inside* the bracket, not merely for the keyword

Anything else is reported as `empty` or `not_applicable`, never as opportunity.

Pure functions. No I/O.
"""
from dataclasses import dataclass

DIGITAL = "digital"
PHYSICAL = "physical"
PERSONALIZED = "personalized"

# Which of the seven dimensions can produce a meaningful bracket for each product type.
# A dimension excluded here is not "a gap nobody has filled" — it is a question that
# cannot be asked of this product.
APPLICABLE = {
    DIGITAL: {
        # A download has no delivery window, no gift wrap and no shipping to be free of.
        "format", "geographic", "quality", "occasion", "personalizable", "discount", "color",
    },
    PHYSICAL: {
        "format", "geographic", "quality", "occasion", "personalizable", "discount",
        "free_shipping", "gift_wrap", "shipping_speed", "color",
    },
    PERSONALIZED: {
        "format", "geographic", "quality", "occasion", "personalizable", "discount",
        "free_shipping", "gift_wrap", "shipping_speed", "color",
    },
}

ALL_DIMENSIONS = set().union(*APPLICABLE.values())

# Below this share of total supply a bracket is thin enough to be worth a look — but only
# once the demand gate has passed.
THIN_SHARE = 0.05
CROWDED_SHARE = 0.30


@dataclass(frozen=True)
class Bracket:
    dimension: str
    value: str
    listings: int
    total_listings: int
    share: float
    status: str          # gap | thin_but_unproven | crowded | empty |
                         # not_applicable | untrusted_source
    demand_evidence: str
    note: str = ""

    @property
    def is_gap(self):
        return self.status == "gap"


def analyse_bracket(dimension, value, listings, total_listings, product_type,
                    trusted=True,
                    demand_in_bracket=None):
    """Classify one bracket. Returns a `Bracket`, never a bare number.

    `demand_in_bracket` is the gate. It is deliberately not inferred from the supply
    count — the whole failure mode is concluding that "nobody sells this" means "people
    want this". Pass a positive figure (sales, reviews, or search volume observed *within*
    the bracket) or None if it was never measured.
    """
    if product_type not in APPLICABLE:
        raise ValueError(f"unknown product_type {product_type!r}")
    if dimension not in ALL_DIMENSIONS:
        raise ValueError(f"unknown dimension {dimension!r}")


    share = (listings / total_listings) if total_listings else 0.0

    # Before any classification: is the number even a share of this market? A
    # filter that returns a superset, or that Etsy silently ignores, produces a
    # count that is real, well-formed, and meaningless here. Classifying it turns
    # a measurement error into a launch recommendation, so this outranks every
    # other rule below — including a thin bracket with proven demand.
    if trusted is False:
        return Bracket(dimension, value, listings, total_listings, share,
                       "untrusted_source", "none",
                       f"the SERP filter behind '{dimension}' did not pass the "
                       f"trust audit — its count is not a share of this market. "
                       f"Re-run: python -m etsy.analytics.filter_trust")

    if dimension not in APPLICABLE[product_type]:
        return Bracket(dimension, value, listings, total_listings, share, "not_applicable",
                       "n/a",
                       f"'{dimension}' cannot apply to a {product_type} product; a 0% "
                       f"reading here is structural, not an opportunity")

    if listings == 0 and not demand_in_bracket:
        return Bracket(dimension, value, listings, total_listings, share, "empty", "none",
                       "no listings and no demonstrated demand — an empty cell, not a gap")

    if share >= CROWDED_SHARE:
        return Bracket(dimension, value, listings, total_listings, share, "crowded",
                       "measured" if demand_in_bracket else "none")

    if share < THIN_SHARE:
        if demand_in_bracket:
            return Bracket(dimension, value, listings, total_listings, share, "gap",
                           "measured",
                           f"thin supply ({share:.1%}) with demand demonstrated inside "
                           f"the bracket")
        return Bracket(dimension, value, listings, total_listings, share,
                       "thin_but_unproven", "none",
                       "supply is thin but no demand was measured inside the bracket — "
                       "cannot be called a gap")

    return Bracket(dimension, value, listings, total_listings, share, "crowded",
                   "measured" if demand_in_bracket else "none")


def find_gaps(brackets, product_type, total_listings, demand_by_bracket=None,
              trust=None):
    """Classify many brackets at once.

    `brackets` maps (dimension, value) -> listing count.
    `demand_by_bracket` maps the same keys -> demand observed inside that bracket.
    `trust` decides whether a bracket's underlying SERP filter may be believed:

        None       consult the filter-trust registry on disk (the default, and
                   what any real run should do)
        True       trust everything — for offline tests of the classification
                   rules themselves, never for a live run
        callable   trust(dimension, value) -> bool, for injecting a fixture

    Returns every bracket classified, so a caller can see what was ruled out and why —
    silently dropping the non-applicable ones is how the trap gets rebuilt.
    """
    demand_by_bracket = demand_by_bracket or {}

    if trust is None:
        # Imported here, not at module scope: gaps.py is pure classification logic
        # and must stay importable without a registry file present.
        from etsy.analytics import filter_trust
        registry = filter_trust.load()
        def trust(dimension, value):
            return filter_trust.bracket_is_trusted(dimension, value, registry=registry)
    elif trust is True:
        def trust(dimension, value):
            return True

    out = []
    for (dimension, value), listings in brackets.items():
        out.append(analyse_bracket(
            dimension, value, listings, total_listings, product_type,
            trusted=trust(dimension, value),
            demand_in_bracket=demand_by_bracket.get((dimension, value))))
    # Real gaps first, then the thin-but-unproven ones worth measuring next.
    order = {"gap": 0, "thin_but_unproven": 1, "crowded": 2, "empty": 3,
             "not_applicable": 4, "untrusted_source": 5}
    return sorted(out, key=lambda b: (order[b.status], b.share))


def summarise(brackets):
    """Counts per status — the honest headline for a run."""
    counts = {}
    for b in brackets:
        counts[b.status] = counts.get(b.status, 0) + 1
    return counts

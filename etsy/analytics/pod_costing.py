"""Cost a product the analysis has already chosen.

This is the LAST step, not the first. The Etsy side decides what to make; this
answers the two questions that decide whether making it pays:

    1. what would I have to charge for this to clear the margin floor?
    2. can I even deliver it fast enough to compete here?

Question 2 is the one sellers skip. A POD towel carries a 10-day handling time
before a parcel moves, so the fast-delivery bracket is structurally closed no
matter how good the design is. Costing a product you cannot ship on time is a
wasted launch, so lead time is checked alongside price, not after it.

PRODUCTION COST IS NOT AVAILABLE FROM PRINTIFY'S CATALOG (see client.py). It
stays None until the operator confirms it. Nothing here substitutes a default:
a plausible COGS produces a plausible price, and a plausible wrong price is the
failure mode this whole codebase is built to prevent.
"""
import math
from dataclasses import dataclass, field

from etsy.analytics import profit

# Etsy's cheapest bracket. A POD product whose handling time alone exceeds this
# cannot enter it, whatever the shipping service.
FAST_BRACKET_DAYS = 7
# Rough US transit on top of handling. Deliberately a RANGE, and labelled
# derived wherever it surfaces -- Printify publishes handling, never transit.
US_TRANSIT_DAYS = (2, 6)

# Upper edge of each band produced by sourcing.delivery_distribution().
_BAND_EDGE = {"0-7 days": 7, "8-14 days": 14, "15-21 days": 21, "22-30 days": 30}


@dataclass(frozen=True)
class PodOption:
    """One blueprint x print provider, priced as far as the API allows."""
    blueprint_id: int
    blueprint_title: str
    provider_id: int
    provider_title: str
    variants: int
    ship_first_item: float = None      # USD, to the operator's market
    ship_additional: float = None
    handling_days: int = None
    cogs: float = None                 # operator-confirmed only; None = unknown
    notes: tuple = field(default_factory=tuple)

    @property
    def lead_days(self):
        """(min, max) days from order to doorstep. None when handling is unknown."""
        if self.handling_days is None:
            return None
        return (self.handling_days + US_TRANSIT_DAYS[0],
                self.handling_days + US_TRANSIT_DAYS[1])

    @property
    def can_ship_fast(self):
        """Can this option ever land in Etsy's 7-day bracket? None = unknown, not yes."""
        if self.handling_days is None:
            return None
        return self.handling_days + US_TRANSIT_DAYS[0] <= FAST_BRACKET_DAYS


def required_price(cogs, product_type, shipping_cost=0.0, shipping_charged=0.0,
                   labor_minutes=0.0, config=None, tolerance=0.005):
    """The lowest price that clears the margin floor for its type.

    This is the inverse of the profit gate, and the number the operator actually
    needs while looking at a supplier: not "is $16.60 profitable" but "what is the
    least I can charge and still clear 50%?".

    Solved by bisection rather than algebra because Etsy's fee schedule is not
    linear in price -- there is a flat listing fee in it, so margin is a curve.
    Returns None when NO price clears the floor, which happens more often than
    sellers expect and is a real answer rather than an error.
    """
    if cogs is None:
        return None                    # an unknown cost cannot produce a known price

    def margin_at(p):
        return profit.unit_economics(p, product_type, cogs, shipping_cost,
                                     shipping_charged, labor_minutes, config)["margin"]

    floor = (config or profit.ProfitConfig()).floors.for_type(product_type)
    lo, hi = 0.01, 1000.0
    if margin_at(hi) < floor:
        # Margin rises with price and still misses at $1000 -- nothing clears it.
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if margin_at(mid) >= floor:
            hi = mid
        else:
            lo = mid
        if hi - lo < tolerance:
            break
    # CEIL to the cent, never round. Rounding a boundary price down puts it back
    # below the floor -- the caller would be handed a price that fails the very
    # gate it was computed to pass.
    return math.ceil(hi * 100) / 100


def find_options(client, term, market="US", limit=8):
    """Blueprints whose title matches `term`, priced and lead-timed.

    Matching is on the blueprint title only -- Printify has no search endpoint and
    the full list is 2,059 items, so this is a substring filter over one fetch, not
    a semantic search. A term matching nothing returns [], which means "Printify
    does not list this under that name", never "this is not makeable".
    """
    needle = term.lower().strip()
    hits = [b for b in client.blueprints() if needle in b["title"].lower()][:limit]

    options = []
    for bp in hits:
        for pp in client.print_providers(bp["id"]):
            notes = []
            try:
                ship = client.shipping(bp["id"], pp["id"])
            except Exception:
                ship = {}
                notes.append("shipping unavailable")

            profile = next((p for p in ship.get("profiles", [])
                            if market in p.get("countries", [])), None)
            if profile is None and ship:
                # Not free shipping -- no profile covers this market at all.
                notes.append(f"no shipping profile covers {market}")

            try:
                nvar = len(client.variants(bp["id"], pp["id"]))
            except Exception:
                nvar = 0
                notes.append("variant list unavailable")

            options.append(PodOption(
                blueprint_id=bp["id"], blueprint_title=bp["title"],
                provider_id=pp["id"], provider_title=pp["title"],
                variants=nvar,
                ship_first_item=(profile["first_item"]["cost"] / 100) if profile else None,
                ship_additional=(profile["additional_items"]["cost"] / 100) if profile else None,
                handling_days=(ship.get("handling_time") or {}).get("value"),
                notes=tuple(notes)))
    return options


def faster_share(option, market_bands):
    """Share of the market already delivering faster than this option's slowest case.

    Uses the bands from sourcing.delivery_distribution(). Returns None when either
    side is unknown -- an unmeasured market must not read as "nobody is faster".
    """
    if not market_bands or not option.lead_days:
        return None
    _, slowest = option.lead_days
    return round(sum(share for band, share in market_bands
                     if _BAND_EDGE.get(band) is not None
                     and _BAND_EDGE[band] <= slowest), 4)


def read(option, product_type=profit.PERSONALIZED, market_bands=None, config=None):
    """Plain-language verdict on one option. States what is unknown as loudly as what is not."""
    out = []

    if option.cogs is None:
        out.append("Production cost is UNKNOWN -- Printify's catalog carries no price. "
                   "Confirm it from the Printify UI before any price here is real.")
    else:
        need = required_price(option.cogs, product_type,
                              shipping_cost=option.ship_first_item or 0.0,
                              config=config)
        ship = option.ship_first_item or 0.0
        if need is None:
            out.append(f"No price clears the {product_type} floor at ${option.cogs:.2f} "
                       f"COGS + ${ship:.2f} shipping. This one cannot be made to pay "
                       f"at any price.")
        else:
            out.append(f"Charge at least ${need:.2f} to clear the {product_type} floor "
                       f"(COGS ${option.cogs:.2f} + shipping ${ship:.2f}).")

    if option.handling_days is None:
        out.append("Handling time unknown -- lead time not assessed.")
    else:
        lo, hi = option.lead_days
        out.append(f"Lead time {lo}-{hi} days ({option.handling_days}d handling + "
                   f"{US_TRANSIT_DAYS[0]}-{US_TRANSIT_DAYS[1]}d transit, transit derived).")
        if option.can_ship_fast is False:
            out.append(f"Cannot enter Etsy's {FAST_BRACKET_DAYS}-day bracket: handling "
                       f"alone is {option.handling_days} days. Speed is not available "
                       f"to you here, however well the listing is optimised.")

    # The join that makes lead time mean something: where it lands in this market's
    # own delivery distribution, rather than in the abstract.
    share = faster_share(option, market_bands)
    if share is not None:
        out.append(f"{share:.0%} of this market already delivers faster than your "
                   f"slowest case.")

    for n in option.notes:
        out.append(f"[!] {n}")
    return out


def affordable_cogs(price, product_type, shipping_cost=0.0, shipping_charged=0.0,
                    labor_minutes=0.0, config=None, tolerance=0.005):
    """The most a unit may cost to make and still clear the floor at this price.

    The other inverse, and the one that turns a rejection into a negotiation. When
    required_price() says "charge $45.78" against a market that pays $16.60, the
    useful follow-up is not "no" — it is "then I need to source this for under
    $X", which is a number a supplier can be asked about.

    Returns None when even a FREE product misses the floor at this price, which
    means the price itself is too low to carry Etsy's fees. That is a real and
    common answer: it says the problem is not the supplier.

    ⚠️ `labor_minutes` no longer moves this number (changed 2026-09-01). The floor
    is now tested against CASH margin — fees, materials and shipping — because the
    operator does not pay themselves a wage, they keep the profit. Their time is
    reported as `profit_per_hour` and judged by them, not gated here. For POD this
    is also simply more accurate: the printer does the work, and charging the
    seller 12 minutes of labour against a printed unit was never right.
    """
    def margin_at(c):
        return profit.unit_economics(price, product_type, c, shipping_cost,
                                     shipping_charged, labor_minutes, config)["margin"]

    floor = (config or profit.ProfitConfig()).floors.for_type(product_type)
    if margin_at(0.0) < floor:
        return None

    lo, hi = 0.0, max(price, 1.0)
    for _ in range(60):
        mid = (lo + hi) / 2
        if margin_at(mid) >= floor:
            lo = mid
        else:
            hi = mid
        if hi - lo < tolerance:
            break
    # FLOOR to the cent, the mirror of required_price's ceil: rounding a maximum
    # cost up would authorise a supplier price that misses the floor.
    return math.floor(lo * 100) / 100


def cogs_ladder(prices, product_type, shipping_cost=0.0, labor_minutes=0.0, config=None):
    """[(price, max affordable COGS)] across a range of prices.

    Read against what the market actually pays, this shows where a product becomes
    possible rather than just whether today's supplier works.
    """
    return [(p, affordable_cogs(p, product_type, shipping_cost=shipping_cost,
                                labor_minutes=labor_minutes, config=config))
            for p in prices]

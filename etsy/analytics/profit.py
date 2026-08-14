"""Profit model — the metric the whole system is supposed to rank on.

`GOAL.md:104-120` and `DECISION_LOG.md` D-01 both say the original architecture's central
flaw was having **no cost input anywhere**: it estimated revenue and treated a big number
as a win. Nothing in this repo computed a fee, a cost, or a margin until this module.

Why revenue ranks the wrong things, from GOAL.md:
  * a digital product at $6 with ~97% margin can beat a physical at $38 with 30%
  * a personalized product with great margin is worthless if it needs 40 made-to-order
    units a week and the operator has time for 15
  * in the three-way demo, the highest-revenue option was a **no-go** on margin

So this module answers "should I make this?" per product type, and a verdict can fail on
either **margin** or **capacity** — the second is what makes personalized goods different
from digital, and no amount of demand fixes it.

Pure functions. No I/O, no imports from other layers, so every number here is testable
without a network or a database.

⚠️ FEE SCHEDULE: verified against Etsy's published rates as of the date in
`FeeSchedule.verified`. Etsy changes these. Re-check that date before trusting a verdict,
and treat the value as config — `REPO_STRUCTURE_AND_CONFIG.md:135-147` specifies these
living in `config/default.yaml`, which does not exist yet. The defaults below are that
document's values, kept here so the model works today and moves out unchanged later.
"""
from dataclasses import dataclass, field

DIGITAL = "digital"
PHYSICAL = "physical"
PERSONALIZED = "personalized"
PRODUCT_TYPES = (DIGITAL, PHYSICAL, PERSONALIZED)


@dataclass(frozen=True)
class FeeSchedule:
    """Etsy's cut. Values from REPO_STRUCTURE_AND_CONFIG.md:135-147."""
    verified: str = "2026-01"
    listing_fee: float = 0.20          # per listing, per 4 months or per sale
    transaction_rate: float = 0.065    # 6.5% of item price + shipping
    processing_rate: float = 0.03      # payment processing, region-dependent
    processing_flat: float = 0.25
    offsite_rate_under_10k: float = 0.15
    offsite_rate_over_10k: float = 0.12


@dataclass(frozen=True)
class Operator:
    """The constraint that makes personalized goods different. GOAL.md:14-16."""
    hourly_rate: float = 25.0
    labor_hours_per_week: float = 15.0


@dataclass(frozen=True)
class MarginFloors:
    """Below these a verdict is no-go regardless of demand. D-01."""
    digital: float = 0.70
    physical: float = 0.35
    personalized: float = 0.50

    def for_type(self, product_type):
        return getattr(self, product_type)


@dataclass(frozen=True)
class ProfitConfig:
    fees: FeeSchedule = field(default_factory=FeeSchedule)
    operator: Operator = field(default_factory=Operator)
    floors: MarginFloors = field(default_factory=MarginFloors)
    # Whether a human confirmed the numbers above, or they are still this file's
    # placeholders. A verdict from guessed fees is arithmetically identical to one from
    # real fees — only this field separates them, so it rides along into the result.
    # `core.settings_store` sets it; the default is deliberately the pessimistic one.
    settings_basis: str = "default"
    unconfirmed_settings: tuple = ()


def etsy_fees(price, shipping_charged=0.0, config=None, offsite_ads=False, over_10k=False):
    """Etsy's total cut on one order. Returns a breakdown, not a single number.

    The transaction fee applies to the shipping the buyer pays as well as the item, which
    is the part most margin estimates miss.
    """
    cfg = (config or ProfitConfig()).fees
    gross = price + shipping_charged

    transaction = gross * cfg.transaction_rate
    processing = gross * cfg.processing_rate + cfg.processing_flat
    offsite = 0.0
    if offsite_ads:
        rate = cfg.offsite_rate_over_10k if over_10k else cfg.offsite_rate_under_10k
        offsite = gross * rate

    total = cfg.listing_fee + transaction + processing + offsite
    return {
        "listing": cfg.listing_fee,
        "transaction": round(transaction, 4),
        "processing": round(processing, 4),
        "offsite_ads": round(offsite, 4),
        "total": round(total, 4),
        "schedule_verified": cfg.verified,
    }


def unit_economics(price, product_type, cogs=0.0, shipping_cost=0.0, shipping_charged=0.0,
                   labor_minutes=0.0, config=None, offsite_ads=False, over_10k=False):
    """Per-unit profit and margin after fees, COGS, shipping and the operator's own time.

    Labour is costed even though it is not cash out: an hour spent on a product is an hour
    unavailable for another, and pretending it is free is exactly what makes a
    made-to-order item look as good as a download.
    """
    if product_type not in PRODUCT_TYPES:
        raise ValueError(f"unknown product_type {product_type!r}; expected one of {PRODUCT_TYPES}")

    cfg = config or ProfitConfig()
    # Digital goods have no unit cost and no shipping. Passing them is a caller error
    # worth surfacing rather than silently ignoring.
    if product_type == DIGITAL and (cogs or shipping_cost):
        raise ValueError("digital products have no COGS or shipping cost")

    fees = etsy_fees(price, shipping_charged, cfg, offsite_ads, over_10k)
    labor_cost = (labor_minutes / 60.0) * cfg.operator.hourly_rate
    shipping_gap = shipping_cost - shipping_charged   # positive = subsidised by the seller

    revenue = price + shipping_charged
    costs = fees["total"] + cogs + shipping_cost + labor_cost
    profit = revenue - costs
    margin = profit / revenue if revenue else 0.0

    return {
        "product_type": product_type,
        "revenue": round(revenue, 4),
        "fees": fees,
        "cogs": round(cogs, 4),
        "shipping_cost": round(shipping_cost, 4),
        "shipping_subsidy": round(shipping_gap, 4),
        "labor_cost": round(labor_cost, 4),
        "labor_minutes": labor_minutes,
        "total_costs": round(costs, 4),
        "profit_per_unit": round(profit, 4),
        "margin": round(margin, 4),
    }


def weekly_capacity(labor_minutes, config=None):
    """How many units the operator can physically make per week. None = unlimited.

    Digital and drop-shipped goods pass 0 minutes and are unconstrained. Anything
    made by hand is capped here, and the cap does not move with demand.
    """
    cfg = config or ProfitConfig()
    if not labor_minutes:
        return None
    return int((cfg.operator.labor_hours_per_week * 60) / labor_minutes)


def verdict(price, product_type, demand_units_per_week=0, cogs=0.0, shipping_cost=0.0,
            shipping_charged=0.0, labor_minutes=0.0, config=None,
            offsite_ads=False, over_10k=False):
    """Go / no-go for one product type, with the reason.

    Two independent ways to fail, which is the whole point:
      * MARGIN   — the unit does not clear the floor for its type
      * CAPACITY — the margin is fine but the operator cannot make enough of them

    `capped_units` is the honest weekly volume: demand, or the hands limit, whichever
    binds. Projected profit uses that, never raw demand.
    """
    cfg = config or ProfitConfig()
    econ = unit_economics(price, product_type, cogs, shipping_cost, shipping_charged,
                          labor_minutes, cfg, offsite_ads, over_10k)

    floor = cfg.floors.for_type(product_type)
    capacity = weekly_capacity(labor_minutes, cfg)
    capped_units = demand_units_per_week if capacity is None else min(demand_units_per_week, capacity)
    capacity_bound = capacity is not None and demand_units_per_week > capacity

    reasons = []
    if econ["margin"] < floor:
        reasons.append(
            f"margin {econ['margin']:.1%} is below the {product_type} floor of {floor:.0%}")
    if econ["profit_per_unit"] <= 0:
        reasons.append("profit per unit is not positive")
    if demand_units_per_week and capped_units == 0:
        reasons.append("no units can be produced within the weekly labour budget")

    go = not reasons
    if capacity_bound:
        # Not a failure — a ceiling. Worth surfacing because it changes what the number
        # means: more demand will not raise this figure.
        reasons.append(
            f"capacity-bound: demand {demand_units_per_week}/wk exceeds the "
            f"{capacity}/wk the labour budget allows")

    return {
        **econ,
        "margin_floor": floor,
        "weekly_capacity": capacity,
        "demand_units_per_week": demand_units_per_week,
        "capped_units_per_week": capped_units,
        "capacity_bound": capacity_bound,
        "weekly_profit": round(econ["profit_per_unit"] * capped_units, 4),
        "go": go,
        "reasons": reasons,
        "basis": "derived_from_config",
        "fee_schedule_verified": cfg.fees.verified,
        # A `go` resting on unconfirmed fees is provisional, and the caller must be
        # able to see that without re-deriving it.
        "settings_basis": cfg.settings_basis,
        "unconfirmed_settings": list(cfg.unconfirmed_settings),
        "provisional": cfg.settings_basis != "operator",
    }


def compare(options, config=None):
    """Rank several product-type options by achievable weekly profit, best first.

    Ranking on `weekly_profit` rather than revenue or margin is the D-01 correction made
    concrete: it is the only figure that respects both the fee model and the hands limit.
    A no-go option still appears, with its reason, so the comparison stays legible.
    """
    results = [verdict(config=config, **o) for o in options]
    return sorted(results, key=lambda r: (r["go"], r["weekly_profit"]), reverse=True)

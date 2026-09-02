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
    """Per-unit money, the way a SELLER counts it — plus what an hour of their time earns.

    ⚠️ CHANGED 2026-09-01, and it changed verdicts across the system.

    This used to subtract the operator's own labour at their hourly rate as a COST,
    and then require the remainder to clear a 35-70% margin floor. That charges the
    product a wage AND takes half of what is left. Measured on the operator's real
    "Custom sign" profile, a $45 sign taking 45 minutes:

        revenue                     $45.00
        materials                  -$12.00
        Etsy fees                   -$4.73
        their own labour           -$18.75   <- subtracted as a cost
        ------------------------------------
        "profit"                     $9.53   margin 21%  ->  BELOW the 50% floor, REJECTED

    But the seller actually takes home $9.53 + $18.75 = **$28.28 for 45 minutes**,
    which is **$37.70/hour**. The system rejected a product paying $37.70/hour. As
    the operator put it: *"i dont need this $25/hr cos am seller"*. They do not pay
    themselves a wage; they keep the profit.

    So now:
      * `profit` / `margin` are CASH — what actually reaches them, labour NOT deducted.
        The floor tests this.
      * `profit_per_hour` is what an hour of their time earns. That is the number a
        maker judges "is this worth doing" by, and it is theirs to judge.

    The old docstring's point was real — an hour on one product is an hour not on
    another — and it survives BETTER here: $/hour compares a 45-minute sign against a
    5-minute download directly, in the unit a seller already thinks in. Costing the
    wage and then flooring the remainder did not measure that trade-off, it just
    rejected everything handmade.

    `labor_cost` and `margin_after_labor` are still reported, so nothing is lost and
    an opportunity-cost view is one field away.
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
    # CASH costs only — money that actually leaves. The operator's own time is not
    # cash out, and treating it as such is what rejected a $37.70/hour product.
    cash_costs = fees["total"] + cogs + shipping_cost
    profit = revenue - cash_costs
    margin = profit / revenue if revenue else 0.0

    # The seller's real question. Reported, never used as a gate — how much an hour
    # of their own time is worth is their call, not this file's.
    hours = labor_minutes / 60.0
    profit_per_hour = (profit / hours) if hours else None
    after_labor = profit - labor_cost
    margin_after_labor = (after_labor / revenue) if revenue else 0.0

    return {
        "product_type": product_type,
        "revenue": round(revenue, 4),
        "fees": fees,
        "cogs": round(cogs, 4),
        "shipping_cost": round(shipping_cost, 4),
        "shipping_subsidy": round(shipping_gap, 4),
        "labor_cost": round(labor_cost, 4),
        "labor_minutes": labor_minutes,
        # What an hour of your time earns on this product. None for a digital item
        # with no build time — that is unmeasured, not infinite.
        "profit_per_hour": None if profit_per_hour is None else round(profit_per_hour, 2),
        # The old view, kept and clearly named: profit after charging your own wage.
        # Informational — the floor no longer tests it.
        "profit_after_labor": round(after_labor, 4),
        "margin_after_labor": round(margin_after_labor, 4),
        "margin_basis": "CASH — fees, materials and shipping only. Your own labour is "
                        "NOT deducted; see profit_per_hour for what your time earns.",
        # Cash out only. profit_after_labor carries the other view.
        "total_costs": round(cash_costs, 4),
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

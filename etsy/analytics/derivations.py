"""Pure sales/views derivations. No I/O, no imports from other layers.

Both `grid_analytics` and `single_listing_analytics` computed these inline and identically,
which meant the arithmetic could only be exercised by making live requests. Here they are
plain functions over plain numbers, so the maths is testable without a network or a
database — which matters more than usual, because this is the code that turns measured
inputs into the estimates the whole product ranks on.

Every function returns its `basis` alongside its number. A number without a basis is the
failure mode this system is built to avoid: `GOAL.md` calls it "a plausible wrong number
that looks authoritative".

Basis vocabulary (closed set — see BASIS_VALUES):
    review_ratio            lifetime estimate from the shop's sales-to-reviews ratio
    daily_badge_x30         30-day figure from a live "N bought today" badge —
                            an UPPER BOUND, see SalesEstimate
    daily_badge_x30_upper_bound   the same, used for display because nothing better
                                  exists; flagged so it is never read as a midpoint
    daily_badge_x30_clamped_to_shop  the badge implied more than the whole shop sells
                                     per day, so it was clamped to the measured rate
    daily_views_x30         30-day views from a live views badge
    sales_div_cvr_measured  views = sales / a CVR that was actually measured
    sales_div_cvr_default   views = sales / the 0.02 assumption  <- weakest input
    absent                  no basis for a figure; the value is None, not 0
"""
from dataclasses import dataclass

BASIS_VALUES = frozenset({
    "review_ratio", "daily_badge_x30", "daily_badge_x30_upper_bound",
    "daily_badge_x30_clamped_to_shop", "daily_views_x30",
    "sales_div_cvr_measured", "sales_div_cvr_default", "sales_div_cvr_unspecified",
    "absent",
})


@dataclass(frozen=True)
class SalesEstimate:
    """A sales figure plus what kind of claim it is.

    `chosen` used to be a bare number, which made a ceiling and a midpoint
    indistinguishable at every call site. The two must not be compared, averaged, or
    ranked against each other, so the distinction travels with the value.
    """
    lifetime: int = None            # ratio-derived point estimate, whole life of listing
    thirty_day: int = None          # badge-derived 30-day figure — a BOUND, not a mean
    chosen: int = 0                 # what to display
    basis: str = "absent"
    is_upper_bound: bool = False    # True when `chosen` is a ceiling
    thirty_day_is_bound: bool = False
    note: str = ""

    def __iter__(self):
        """Kept so existing 4-tuple unpacking still works during migration."""
        return iter((self.lifetime, self.thirty_day, self.chosen, self.basis))


def sales_ratio(shop_total_sales, shop_total_reviews):
    """Shop-wide sales per review, or None when it cannot be computed.

    None rather than 0.0: a shop with no reviews yields no ratio, and a 0.0 here would
    silently zero out every listing estimate that used it.
    """
    if not shop_total_reviews or not shop_total_sales:
        return None
    return shop_total_sales / shop_total_reviews


def estimate_sales(review_count, shop_total_sales=None, shop_total_reviews=None,
                   daily_sales=0, shop_sales_per_day=None):
    """Return a SalesEstimate. Lifetime and 30-day are different quantities.

    SELECTION EFFECT (bias B-03): the "N bought today" badge renders only once the count
    crosses a platform threshold, so it is observed *only on above-threshold days*.
    Multiplying it by 30 projects the best day of the month across the whole month. Worse,
    the badge is partly causal — it grants visibility, which drives the sales it appears
    to measure — so it cannot be treated as a neutral reading.
    The correct treatment is an UPPER BOUND, never a point estimate.

    This function used to return the badge figure as `chosen`, ranked above the ratio
    because it was "a measurement rather than an inference". That is right about
    provenance and wrong about selection: it is a measurement conditioned on its own
    value. The ratio estimate is now preferred for display, and the badge is carried
    alongside as a ceiling.

    `shop_sales_per_day` is the calibration B-03 asks for — the measured daily delta from
    `shop_observations`. It enforces a hard logical constraint: a single listing cannot
    sell faster than its entire shop. When the badge implies otherwise, the badge is
    wrong (or that day was exceptional) and the figure is clamped to the shop rate.
    None means unmeasured, and never clamps — an unmeasured shop is not a shop that
    sells nothing.

    A `daily_sales` of 0 means no badge was rendered far more often than it means nothing
    sold, so 0 never produces a 30-day figure.
    """
    ratio = sales_ratio(shop_total_sales, shop_total_reviews)
    lifetime = int(review_count * ratio) if ratio and review_count else None

    thirty_day = None
    thirty_basis = None
    note = ""
    if daily_sales and daily_sales > 0:
        thirty_basis = "daily_badge_x30"
        if shop_sales_per_day is not None and daily_sales > shop_sales_per_day:
            # One listing outselling its whole shop is impossible, not impressive.
            thirty_day = int(shop_sales_per_day * 30)
            thirty_basis = "daily_badge_x30_clamped_to_shop"
            note = (f"badge claimed {daily_sales}/day, which exceeds the shop's measured "
                    f"{shop_sales_per_day:g}/day — clamped to the shop rate")
        else:
            thirty_day = int(daily_sales) * 30

    # A point estimate beats a ceiling for display, even though the ceiling is derived
    # from a measurement: a bound answers "no more than", which is not what a reader of
    # a sales figure assumes they are being told.
    if lifetime is not None:
        return SalesEstimate(lifetime=lifetime, thirty_day=thirty_day, chosen=lifetime,
                             basis="review_ratio", is_upper_bound=False,
                             thirty_day_is_bound=thirty_day is not None, note=note)
    if thirty_day is not None:
        return SalesEstimate(
            lifetime=None, thirty_day=thirty_day, chosen=thirty_day,
            basis=(thirty_basis if thirty_basis == "daily_badge_x30_clamped_to_shop"
                   else "daily_badge_x30_upper_bound"),
            is_upper_bound=True, thirty_day_is_bound=True, note=note)
    return SalesEstimate(chosen=0, basis="absent")


def estimate_views(sales, daily_views=0, cvr=0.02, cvr_source="default"):
    """Return (views, basis).

    A live views badge is a measurement and wins. Otherwise views are inferred by dividing
    an already-derived sales figure by a conversion rate that may itself be an assumption —
    two layers of inference, which is why `cvr_source` is carried into the basis string
    rather than dropped.
    """
    if daily_views and daily_views > 0:
        return int(daily_views) * 30, "daily_views_x30"
    if not sales or not cvr:
        return 0, "absent"
    return int(sales / cvr), f"sales_div_cvr_{cvr_source}"


def parse_price(value):
    """Money-ish value -> float, or None when it cannot be read.

    Etsy hands prices back as `"$12.34"`, `"$1,234.56"`, the literal string `"Unknown"`,
    a bare number, or nothing at all. `private_blueprint.py:95` coerced the unreadable
    cases to **0.0**, which then flowed into the database as a real price — a $0 product
    clears no margin floor and reads as a catastrophic loss rather than as missing data.

    None is the only honest answer for "not measured". Callers must branch on it.
    """
    if value is None:
        return None
    if isinstance(value, bool):          # bool is an int subclass; never a price
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text.lower() in ("unknown", "none", "n/a", "-"):
        return None

    cleaned = "".join(c for c in text if c.isdigit() or c in ".-")
    # A stray second separator ("12.34.56") means we did not understand the format.
    if cleaned.count(".") > 1 or cleaned.count("-") > 1 or not any(c.isdigit() for c in cleaned):
        return None
    try:
        price = float(cleaned)
    except ValueError:
        return None
    return price if price >= 0 else None


def velocity_from_days(days_since_last_review):
    """Bucket review recency. Returns (label, basis).

    Kept here so the thresholds live in one place; both pipelines had their own copy of
    the same four-branch ladder.
    """
    if days_since_last_review is None or days_since_last_review < 0:
        return "DEAD 💀", "absent"
    if days_since_last_review <= 7:
        return "HOT 🔥", "review_recency"
    if days_since_last_review <= 30:
        return "STEADY 📈", "review_recency"
    return "SLOW 🐢", "review_recency"

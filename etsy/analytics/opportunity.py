"""Calendar × demand × profit — the join that turns a date into a decision.

The calendar says *when*. This says *whether it pays*, so a row reads

    🔴 thanksgiving · 1.5 weeks · "thanksgiving garland"
       2,400 searches/mo · $8.40/unit after fees · GO

rather than just a date.

**The unit trap this module exists to avoid.** `profit.verdict()` takes
`demand_units_per_week` meaning *units the operator will sell*. Etsy's search volume ×
CVR is the whole marketplace's demand, spread across every competing listing — 351,677
of them for "mom necklace". Feeding market demand into that slot produces a weekly
profit figure that assumes the operator captures the entire niche. It would be large,
specific, and pure fantasy: the single most flattering wrong number this system could
produce, on the screen the operator acts from.

So the two are kept apart:

  * **the verdict** is per-unit — margin against the floor for the product type. It
    needs no demand estimate at all, so it cannot be inflated by one.
  * **market demand** is reported beside it, labelled as the market's, never the
    operator's.
  * **weekly profit** appears only when an explicit `capture_share` is supplied, and
    carries that assumption in the result. There is no default share, because any
    default would be a guess wearing a number's clothes.
"""
WEEKS_PER_MONTH = 4.345          # 52/12 — Etsy volume is monthly, capacity is weekly


def market_demand(data):
    """volume × CVR for this term. ⚠️ NOT an order count — see the warning below.

    ⚠️ **This figure's units are UNKNOWN, and it must not be read as orders.**
    Probed 2026-08-20 against observable evidence:

        "personalized gift"  209,917 searches/mo × query_cvr 0.00018970
                             => 39.8 by this arithmetic
        ...while the #1 listing for that term carries 14,733 lifetime reviews.

    If 39.8 were the whole market's monthly orders, that single listing would have
    needed ~30 years to accumulate its reviews — against 705,767 competitors, and
    reviews are only a fraction of orders. So `volume × query_cvr` is off by at
    least two orders of magnitude, in a direction and by a factor this system has
    not established. Etsy's `query_cvr` is a rate against some denominator it does
    not publish; it is *not* the fraction of searches that become orders.

    The value is kept because it is **consistently defined across terms** — the
    comparison between two terms is meaningful even though the absolute number is
    not. `discover.confirm_intent` uses exactly that property and refuses to convert
    it into units. Nothing should threshold this figure absolutely (D-43).

    `basis` says `relative_only` for this reason: it is not a measurement of
    anything the operator can act on directly.
    """
    volume, cvr = data.get("volume"), data.get("cvr")
    if volume is None or cvr is None:
        # Absent is not zero (N-02): a term Etsy would not size is unmeasured, and
        # zero would read as "nobody buys this".
        return {"units_per_week": None, "basis": "unmeasured",
                "detail": "volume or CVR missing"}
    return {
        "units_per_week": round(volume * cvr / WEEKS_PER_MONTH, 2),
        "basis": "relative_only",
        "is_upper_bound_for_one_shop": True,
        "not_an_order_count": True,
        "supply": data.get("supply"),
        "detail": (f"{volume:,} searches/mo × CVR {cvr:.6f} — a RELATIVE index only, "
                   f"not orders (D-43); {data.get('supply') or 'unknown'} listings "
                   f"compete"),
    }


def evaluate(term, data, settings, profile_name, capture_share=None):
    """One term -> the decision, with every assumption on the surface.

    `capture_share` is the operator's estimate of the fraction of market demand this
    listing would win. Supplying it enables a weekly figure; omitting it leaves the
    verdict per-unit, which is the honest default.
    """
    from etsy.analytics import profit

    price_low, price_high = data.get("price_low"), data.get("price_high")
    if price_low is None or price_high is None:
        # Etsy declines to compute a price band for thin terms. Guessing one would set
        # the margin, which sets the verdict — the whole chain from one invention.
        return {"term": term, "verdict": None, "basis": "no_price_band",
                "reason": "Etsy returned no median price band — cannot judge, not rejected",
                "market": market_demand(data)}

    price = round((price_low + price_high) / 2, 2)
    kwargs = settings.verdict_kwargs(profile_name)
    market = market_demand(data)

    # Demand is deliberately 0: the verdict is per-unit and must not inherit a
    # marketplace-wide number as if it were ours.
    units = 0
    share_note = None
    if capture_share is not None:
        if not 0 < capture_share <= 1:
            raise ValueError("capture_share must be a fraction in (0, 1]")
        if market["units_per_week"] is None:
            share_note = "capture_share supplied but market demand is unmeasured"
        else:
            units = market["units_per_week"] * capture_share
            share_note = (f"weekly figures assume {capture_share:.0%} of a market buying "
                          f"{market['units_per_week']}/wk")

    verdict = profit.verdict(price=price, demand_units_per_week=units, **kwargs)

    return {
        "term": term,
        "price_used": price,
        "price_band": [price_low, price_high],
        "product_profile": profile_name,
        "verdict": verdict,
        "market": market,
        "capture_share": capture_share,
        "capture_note": share_note,
        # Etsy's own week-over-week momentum, free in the same response.
        "wow_change": data.get("wow_change"),
        # True until the operator confirms the fee schedule — a `go` on default fees is
        # arithmetically identical to a real one, and only this separates them.
        "provisional": verdict["provisional"],
    }


def for_calendar(rows, fetch, settings, profile_name, capture_share=None,
                 states=("list_now",)):
    """Evaluate the watched terms attached to urgent calendar rows.

    Restricted to actionable states by default: spending private-tier calls on moments
    ten weeks out wastes the one tier that authenticates as the operator's own seller
    account (D-29), and the answer would be stale by the time it mattered.

    `fetch` is injected so this stays testable offline — it takes a term and returns a
    parsed results-data dict.
    """
    out = []
    for row in rows:
        if row["state"] not in states:
            continue
        for term in row.get("terms") or []:
            data = fetch(term)
            if not data:
                out.append({"moment": row["moment"], "term": term, "verdict": None,
                            "basis": "fetch_failed"})
                continue
            result = evaluate(term, data, settings, profile_name, capture_share)
            out.append({**result, "moment": row["moment"], "list_by": row["list_by"],
                        "state": row["state"], "is_late": row.get("is_late", False)})
    return out


def render(results):
    """Terminal view of the join."""
    lines = []
    for r in results:
        head = f"{r.get('moment', '-'):<16} {r['term']:<26}"
        if not r.get("verdict"):
            lines.append(f"{head} — {r.get('reason') or r.get('basis')}")
            continue
        v = r["verdict"]
        mark = "GO " if v["go"] else "NO "
        flag = " (provisional)" if r["provisional"] else ""
        late = " ⚠️LATE" if r.get("is_late") else ""
        lines.append(f"{head} {mark} ${v['profit_per_unit']:>6.2f}/unit  "
                     f"margin {v['margin']:>5.1%} vs {v['margin_floor']:.0%}{flag}{late}")
        market = r["market"]
        if market["units_per_week"] is not None:
            lines.append(f"{'':<44} market {market['units_per_week']}/wk "
                         f"across {market.get('supply') or '?'} listings")
        if not v["go"]:
            for reason in v["reasons"][:2]:
                lines.append(f"{'':<44} ✗ {reason}")
    return "\n".join(lines)

"""The calendar — what to list this week, and by when (D-20).

The home screen. Not a niche checker: every competitor is a niche checker, and none of
them can say *when*, because that needs Pinterest's takeoff dates joined to Etsy demand
and a profit model willing to say no.

Three states, from `list_by` (takeoff minus the operator's lead time):

    🔴 LIST NOW     the deadline is here or gone, and the moment has not peaked
    🟡 LIST BY      time remains — the date is the point
    ⚪ WATCHING     too far out to act on

**Past the deadline is not the same as missed.** Halloween's `list_by` was seven weeks
ago while its peak is still two months out and Pinterest's own `phase` reads `rising`.
Calling that "missed" throws away a live opportunity; calling it "on time" pretends the
best window is still open. It is reported as late, with how late and how long until the
peak, and the operator decides.

Verified against live moments 2026-08-15: 13 moments, thanksgiving 1.5 weeks from its
deadline, halloween 7.6 weeks past it but still rising toward an October peak.
"""
from datetime import datetime, timezone

LIST_NOW = "list_now"
LIST_BY = "list_by"
WATCHING = "watching"
PASSED = "passed"

# Inside this many weeks the deadline is the news, not the date.
URGENT_WEEKS = 2.0
# Beyond this there is nothing to do yet, and showing it as actionable trains the
# operator to ignore the calendar.
HORIZON_WEEKS = 10.0


def _now():
    return datetime.now(timezone.utc)


def _days_until(iso_date, now):
    try:
        target = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (target - now).days


def classify(plan, now=None):
    """One launch plan -> its calendar state, with the reason attached.

    `weeks_left` is measured to the LISTING date, so negative means the deadline has
    gone. Whether that matters depends entirely on whether the peak has also gone,
    which is why both are considered here rather than just the deadline.
    """
    now = now or _now()
    weeks_left = plan.get("weeks_left")
    if weeks_left is None:
        return {**plan, "state": None, "reason": "no takeoff date — cannot be timed"}

    days_to_peak = _days_until(plan.get("peak"), now) if plan.get("peak") else None
    phase = (plan.get("phase") or "").lower()

    # The peak is gone: nothing to list into this cycle. `next_occurrence` is next year.
    if days_to_peak is not None and days_to_peak < 0:
        return {**plan, "state": PASSED, "days_to_peak": days_to_peak,
                "reason": f"peak was {abs(days_to_peak)} days ago — wait for next year"}

    if weeks_left <= 0:
        # Late, but the peak is ahead. A real chance, at a cost worth naming: less
        # ranking runway before the traffic arrives.
        return {**plan, "state": LIST_NOW, "days_to_peak": days_to_peak,
                "is_late": True,
                "reason": (f"deadline passed {abs(weeks_left):.1f} weeks ago, but the peak "
                           f"is {days_to_peak} days out and Pinterest reads '{phase}' — "
                           f"late, not missed")}

    if weeks_left <= URGENT_WEEKS:
        return {**plan, "state": LIST_NOW, "days_to_peak": days_to_peak, "is_late": False,
                "reason": f"list within {weeks_left:.1f} weeks to catch the ramp"}

    if weeks_left <= HORIZON_WEEKS:
        return {**plan, "state": LIST_BY, "days_to_peak": days_to_peak, "is_late": False,
                "reason": f"deadline in {weeks_left:.1f} weeks"}

    return {**plan, "state": WATCHING, "days_to_peak": days_to_peak, "is_late": False,
            "reason": f"{weeks_left:.1f} weeks out — nothing to do yet"}


def match_terms_to_moment(moment_name, terms):
    """Which watched terms belong to this moment.

    Containment on content words, the same relation `competitor_tracker` uses for
    titles: "christmas ornament" belongs to the christmas moment, "ornament" does not.
    A term matching nothing is simply not on the calendar — it is undated, not urgent.
    """
    from etsy.analytics.term_join import content_words

    needed = content_words(moment_name or "")
    if not needed:
        return []
    return [t for t in (terms or []) if needed <= content_words(t)]


def build(moments, terms=None, lead_weeks=6, now=None, include_passed=False):
    """The calendar: every timeable moment, soonest deadline first.

    Moments without a takeoff timestamp are dropped by `launch_plan` rather than
    defaulted — an undated moment cannot be scheduled, and inventing a date is the
    failure this system exists to prevent.
    """
    from pinterest.endpoints.local_math import calendar as launch_calendar

    now = now or _now()
    rows = []
    for plan in launch_calendar(moments, lead_weeks=lead_weeks, now=now):
        row = classify(plan, now)
        if row["state"] is None:
            continue
        if row["state"] == PASSED and not include_passed:
            continue
        row["terms"] = match_terms_to_moment(row["moment"], terms)
        rows.append(row)

    order = {LIST_NOW: 0, LIST_BY: 1, WATCHING: 2, PASSED: 3}
    return sorted(rows, key=lambda r: (order[r["state"]], r["list_by"]))


def render(rows):
    """Plain-text calendar — the terminal stand-in for the home screen."""
    icon = {LIST_NOW: "🔴", LIST_BY: "🟡", WATCHING: "⚪", PASSED: "⬛"}
    lines = []
    for row in rows:
        late = "  ⚠️ LATE" if row.get("is_late") else ""
        terms = f"  [{', '.join(row['terms'])}]" if row.get("terms") else ""
        lines.append(f"{icon[row['state']]} {row['moment']:<20} list by {row['list_by']}"
                     f"  peak {row['peak']}{late}{terms}")
        lines.append(f"     {row['reason']}")
    return "\n".join(lines)

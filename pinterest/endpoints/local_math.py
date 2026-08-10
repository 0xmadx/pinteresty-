"""Derivations that replace a request with arithmetic.

Everything here was verified against the live API before being written down; the negative
results are recorded too, because knowing what *cannot* be derived is what stops someone
computing a plausible-looking wrong number instead of making the call.

DERIVABLE (no request):
  * all three event summaries          — one /top/ response carries outbound_clicks,
                                         engagement AND saves for every row, so the
                                         click/save intent ratio costs 1 call, not 3
  * both order_by orderings            — percent_growth and percent_relative_volume are
                                         both present, so PCT_CHANGE_MOM vs RELATIVE_VOLUME
                                         is a local sort
  * shorter metric windows             — see series_store.slice_window (renormalized, and
                                         guarded where source rounding destroyed precision)
  * launch dates from the calendar     — takeoff_ms is a timestamp; the 6-week rule is
                                         subtraction, not an endpoint

NOT DERIVABLE (must request):
  * seasonality_score  — probed 12 terms against their 53-week series. Neither coefficient
                         of variation nor top-8-week concentration tracks it monotonically
                         (score 0.9909 at cv 2.462, score 0.9558 at cv 3.661). It uses
                         history we are not given. Read it off /top_trends_filtered/.
  * growth_rates       — the API's wow/mom/yoy do not reproduce from point-to-point deltas
                         on the returned counts (measured: api wow=5 where the naive
                         calculation gives 456). They ship inside the /metrics/ response,
                         so store them rather than recompute them.
  * demographics, forecasts, top_products — no local shortcut exists.
"""
from datetime import datetime, timedelta, timezone

EVENT_KEY = {"OUTBOUND_CLICK": "outbound_clicks",
             "ENGAGEMENT": "engagement",
             "SAVE": "saves"}


# -- shopping: one call, three events ---------------------------------------------------
def event_summary(row, event="OUTBOUND_CLICK"):
    """Pull any event's summary out of a `top_categories` row.

    A `top/` call made with event=OUTBOUND_CLICK still returns the saves and engagement
    blocks, so all three demand curves come from the single request. The event argument
    only decides which categories *rank* (44 on clicks, 35 on engagement, 18 on saves).
    """
    return (row.get("summary") or {}).get(EVENT_KEY[event], {})


def intent_ratio(row):
    """Outbound-click growth over save growth — purchase intent vs aspiration.

    >1 means people click through more than they collect; <1 is a mood board. None when
    saves are flat, because the ratio is undefined rather than infinite.
    """
    clicks = event_summary(row, "OUTBOUND_CLICK").get("percent_growth")
    saves = event_summary(row, "SAVE").get("percent_growth")
    if clicks is None or not saves:
        return None
    return clicks / saves


def resort(rows, order_by="PCT_CHANGE_MOM", event="OUTBOUND_CLICK", descending=True):
    """Re-rank categories locally. Both sort keys ship in every row, so switching order_by
    (or the event you rank on) is a sort, not a second request.

    Ties break on ascending category id — the values alone leave ~4 pairs tied in a
    44-row response, and without this the local order diverges from the API's at the first
    tie. Verified to reproduce both PCT_CHANGE_MOM and RELATIVE_VOLUME exactly.
    """
    field = "percent_growth" if order_by == "PCT_CHANGE_MOM" else "percent_relative_volume"
    sign = -1 if descending else 1
    return sorted(rows, key=lambda r: (sign * (event_summary(r, event).get(field) or 0),
                                       int(r["product_category"])))


def ranked_on(rows_by_event):
    """Which categories rank on one event but not another.

    The set difference is a signal before any ratio is taken: a category present on
    OUTBOUND_CLICK but absent from SAVE is bought without being dreamed about.
    """
    sets = {e: {r["product_category"] for r in rows} for e, rows in rows_by_event.items()}
    return {f"{a}_not_{b}": sets[a] - sets[b] for a in sets for b in sets if a != b}


# -- moments: launch timing is subtraction ----------------------------------------------
def _dt(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) if ms else None


def launch_plan(moment, lead_weeks=6, now=None):
    """Turn one `moments_calendar()` entry into dates. No request — the calendar already
    carries the timestamps, and the Etsy playbook's "list 6-8 weeks before the ramp" is
    subtraction from `takeoff_ms` rather than the eyeball estimate it is today.

    `weeks_left` is measured to the listing date, so negative means already late.
    """
    now = now or datetime.now(timezone.utc)
    takeoff, peak = _dt(moment.get("takeoff_ms")), _dt(moment.get("peak_ms"))
    if not takeoff:
        return None
    list_by = takeoff - timedelta(weeks=lead_weeks)
    last_year = _dt(moment.get("last_year_takeoff_ms"))
    return {
        "moment": moment.get("moment"),
        "phase": moment.get("phase"),
        "list_by": list_by.date().isoformat(),
        "takeoff": takeoff.date().isoformat(),
        "peak": peak.date().isoformat() if peak else None,
        "peak_length_days": moment.get("peak_length_days"),
        "weeks_left": round((list_by - now).total_seconds() / 604800, 1),
        # Drift against last year is the sanity check on the prediction — but only when
        # historical_peaks really holds a prior-year observation. For moments already past
        # this cycle Pinterest echoes the same timestamp into both blocks, and differencing
        # those reports a flat -365d "drift" that never happened.
        "takeoff_drift_days": _drift(takeoff, last_year),
    }


def _drift(takeoff, last_year):
    """Days this year's takeoff moved against last year's. None when the two timestamps are
    not a year apart — see launch_plan."""
    if not last_year:
        return None
    gap = (takeoff - last_year).days
    return gap - 365 if 300 <= gap <= 430 else None


def calendar(moments, lead_weeks=6, now=None):
    """Every moment as a launch plan, soonest deadline first, past deadlines dropped."""
    plans = [p for p in (launch_plan(m, lead_weeks, now) for m in moments or []) if p]
    return sorted(plans, key=lambda p: p["list_by"])


# -- series shape (our own, deliberately not claiming to reproduce the API's) -----------
def velocity(counts, weeks=4):
    """Recent mean over prior mean, for terms we only hold a bare `counts[]` for.

    This is OUR momentum measure, not a reconstruction of the API's growth_rates — those
    do not reproduce from the rounded counts (see module docstring). Use growth_rates when
    the term came from /metrics/; use this when it came from /prefix_match/.
    """
    if len(counts) < weeks * 2:
        return None
    recent = sum(counts[-weeks:]) / weeks
    prior = sum(counts[-weeks * 2:-weeks]) / weeks
    return None if not prior else round((recent - prior) / prior, 4)


def peak_week(counts, dates=None):
    """Index (and date, if given) of the maximum — where in the year the term fires."""
    if not counts:
        return None
    i = counts.index(max(counts))
    return {"index": i, "weeks_ago": len(counts) - 1 - i,
            "date": dates[i] if dates and i < len(dates) else None}

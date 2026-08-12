"""
freshness.py

Layer: analytics/ (pure functions — no I/O, no imports from other layers)
Purpose: propagate the age of a derived value's inputs. A composite is only as
         current as its stalest input, and that fact has to be carried, not assumed.

Key decision (bias B-10): a score built from a fresh Pinterest reading and a
month-old Etsy supply count is computed across two moments in time. Each input has
its own collected_at; the composite inherits the OLDEST — the freshness floor.
Without it, a month-old number wearing a fresh score looks as current as a reading
taken today, and the operator times a launch on data that has already moved.

A missing timestamp is unknown age — skipped from the floor, never treated as
epoch-zero (infinitely stale) or as now (infinitely fresh). All-unknown yields
None: unknown freshness is a distinct state from stale, and collapsing them is the
same measured-vs-assumed error this codebase keeps having to undo.
"""
from datetime import datetime, timezone

# Thresholds for the plain-language tag the UI shows. A weekly-batch system: a reading
# from this week is current, last week is aging, older than two weeks is stale.
AGING_DAYS = 7
STALE_DAYS = 14


def _parse(ts):
    """ISO string or datetime -> aware datetime (UTC assumed), or None."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts))
        except (ValueError, TypeError):
            return None
    # A naive timestamp is assumed UTC rather than raising — every writer in this repo
    # stamps UTC, and refusing a naive one would turn a data-quality nit into a crash.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def freshness_floor(*timestamps):
    """The oldest of several input timestamps — the age a composite inherits.

    Returns the value in its original form (so an ISO string in gives an ISO string
    out) for the min; None when nothing is known.
    """
    dated = [(ts, _parse(ts)) for ts in timestamps]
    known = [(orig, dt) for orig, dt in dated if dt is not None]
    if not known:
        return None
    return min(known, key=lambda pair: pair[1])[0]


def staleness_days(floor, now=None):
    """Whole days between the floor and now, or None when the floor is unknown."""
    dt = _parse(floor)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - dt).days


def freshness_tag(floor, now=None):
    """'fresh' | 'aging' | 'stale' | 'unknown' — the label the UI carries on a value.

    'unknown' is never silently rendered as 'fresh'. A value whose age we cannot
    establish must not look current; the B-10 skill note is explicit that low
    freshness has to read as a warning, not an absence of one.
    """
    days = staleness_days(floor, now=now)
    if days is None:
        return "unknown"
    if days <= AGING_DAYS:
        return "fresh" if days < AGING_DAYS else "aging"
    return "aging" if days <= STALE_DAYS else "stale"

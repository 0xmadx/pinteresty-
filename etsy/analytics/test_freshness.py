"""Offline tests for freshness propagation (B-10). No network, no database.

A derived record inherits the OLDEST timestamp among its inputs. A score built from a
fresh Pinterest reading and a month-old Etsy supply count is computed across two moments
in time, and is only as current as its stalest input — but nothing records that unless
the floor is carried forward explicitly.

Run:  python -m etsy.analytics.test_freshness
"""
import sys
from datetime import datetime, timedelta, timezone

from etsy.analytics.freshness import freshness_floor, freshness_tag, staleness_days

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    fresh = "2026-08-11T00:00:00+00:00"
    old = "2026-07-11T00:00:00+00:00"
    older = "2026-06-01T00:00:00+00:00"

    # --- the floor is the oldest input --------------------------------------------------
    check("the floor is the OLDEST of several timestamps",
          freshness_floor(fresh, old, older) == older, f"got {freshness_floor(fresh, old, older)}")
    check("order of arguments does not matter",
          freshness_floor(older, fresh, old) == older)
    check("a single input is its own floor", freshness_floor(fresh) == fresh)

    # --- None is not the beginning of time ----------------------------------------------
    print()
    # A missing timestamp is unknown age, not infinitely fresh and not infinitely old.
    # It is skipped, but its presence is knowable via the count of contributing inputs.
    check("None inputs are ignored, not treated as epoch-zero",
          freshness_floor(fresh, None, old) == old, f"got {freshness_floor(fresh, None, old)}")
    check("all-None yields None — unknown freshness, not a fabricated date",
          freshness_floor(None, None) is None)
    check("no inputs yields None", freshness_floor() is None)

    # --- staleness in days ----------------------------------------------------------------
    print()
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    check("staleness is measured from the floor to now",
          staleness_days(old, now=now) == 31, f"got {staleness_days(old, now=now)}")
    check("a same-day floor is zero days stale",
          staleness_days(fresh, now=now) == 0)
    check("an unknown floor has unknown staleness — None, not 0",
          staleness_days(None, now=now) is None)

    # --- naive timestamps are handled, not crashed on ------------------------------------
    print()
    check("a naive ISO string is assumed UTC rather than raising",
          staleness_days("2026-08-04T00:00:00", now=now) == 7,
          f"got {staleness_days('2026-08-04T00:00:00', now=now)}")

    # --- the tag the UI shows -------------------------------------------------------------
    print()
    check("today is 'fresh'", freshness_tag(fresh, now=now) == "fresh")
    check("a week old is 'aging'",
          freshness_tag((now - timedelta(days=8)).isoformat(), now=now) == "aging")
    check("a month old is 'stale'", freshness_tag(old, now=now) == "stale")
    check("unknown age is 'unknown', never silently 'fresh'",
          freshness_tag(None, now=now) == "unknown")

    # --- the realistic composite: fresh Pinterest + stale Etsy -----------------------------
    print()
    # This is B-10's exact example. The floor must be the Etsy count, not the Pinterest one.
    floor = freshness_floor(
        fresh,   # Pinterest momentum, read today
        old,     # Etsy supply, a month old
    )
    check("a fresh+stale composite inherits the STALE timestamp",
          floor == old, f"got {floor}")
    check("and therefore reads as stale, not fresh",
          freshness_tag(floor, now=now) == "stale")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

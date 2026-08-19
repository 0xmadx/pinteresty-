"""Offline tests for the daily sales delta. No network; a temp database.

This is meant to be the system's **one measured number** — every other sales figure is
inferred. `WHATS_ACTUALLY_THERE.md` called it "✅ the one measured number — no bias" while
it had in fact never produced one, and B-03's mitigation ("calibrate the badge against the
daily delta") depends on it existing.

The trap this guards: a "daily" delta measured across a gap of unknown length. If the
tracker runs Monday and next Friday, the difference is a **4-day** figure. Labelled and
compared as daily it inflates every downstream rate by 4x — a plausible wrong number,
which is exactly the failure mode this project is named for.

Run:  python -m etsy.analytics.test_daily_delta
"""
import os
import sys
import tempfile

from core.database import MarketDatabase

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
    tmp = tempfile.mkdtemp()
    db = MarketDatabase(db_path=os.path.join(tmp, "market.db"))

    # --- the first observation is a baseline, not a delta ---------------------------------
    r = db.record_shop_observation("ShopA", total_sales=1000, total_reviews=200,
                                   collected_at="2026-08-01T00:00:00+00:00")
    check("the first observation records a baseline, not a delta",
          r["basis"] == "baseline" and r["sales_delta"] is None, f"got {r}")
    check("a baseline has no per-day rate — nothing to divide",
          r["sales_per_day"] is None)
    check("but the absolute total is stored", r["total_sales"] == 1000)

    # --- a one-day gap is a genuine daily delta -------------------------------------------
    print()
    r = db.record_shop_observation("ShopA", total_sales=1030, total_reviews=203,
                                   collected_at="2026-08-02T00:00:00+00:00")
    check("the second observation yields a measured delta",
          r["sales_delta"] == 30 and r["basis"] == "measured_delta", f"got {r}")
    check("window_days is 1", r["window_days"] == 1.0, f"got {r['window_days']}")
    check("so the per-day rate equals the delta", r["sales_per_day"] == 30.0)

    # --- THE regression: a multi-day gap must not read as one day ---------------------------
    print()
    r = db.record_shop_observation("ShopA", total_sales=1150, total_reviews=210,
                                   collected_at="2026-08-06T00:00:00+00:00")
    check("a 4-day gap records the true window, not 1",
          r["window_days"] == 4.0, f"got {r['window_days']}")
    check("the raw delta is the full 120 across that window", r["sales_delta"] == 120)
    check("the per-day rate divides by the REAL window (30/day, not 120)",
          r["sales_per_day"] == 30.0, f"got {r['sales_per_day']}")

    # --- history is append-only ---------------------------------------------------------------
    print()
    hist = db.get_shop_history("ShopA")
    check("every observation is kept, oldest first", len(hist) == 3, f"got {len(hist)}")
    check("history is ordered by collected_at",
          [h["total_sales"] for h in hist] == [1000, 1030, 1150])

    # --- two runs at the same instant are idempotent --------------------------------------------
    print()
    db.record_shop_observation("ShopA", total_sales=1150, total_reviews=210,
                               collected_at="2026-08-06T00:00:00+00:00")
    check("re-recording the same instant does not duplicate",
          len(db.get_shop_history("ShopA")) == 3,
          f"got {len(db.get_shop_history('ShopA'))}")

    # --- a same-day second run has a zero-length window -----------------------------------------
    print()
    r = db.record_shop_observation("ShopA", total_sales=1155, total_reviews=210,
                                   collected_at="2026-08-06T06:00:00+00:00")
    check("a sub-day gap keeps its fractional window", r["window_days"] == 0.25,
          f"got {r['window_days']}")
    check("and extrapolates honestly rather than reporting 5/day",
          r["sales_per_day"] == 20.0, f"got {r['sales_per_day']}")

    # --- a counter that goes backwards is refused, not stored -------------------------------------
    print()
    r = db.record_shop_observation("ShopA", total_sales=900, total_reviews=210,
                                   collected_at="2026-08-07T00:00:00+00:00")
    check("a decreasing lifetime counter yields no delta — the number is not trustworthy",
          r["sales_delta"] is None and r["basis"] == "counter_decreased",
          f"got basis={r['basis']} delta={r['sales_delta']}")
    check("the observation is still stored, so the anomaly is visible",
          len(db.get_shop_history("ShopA")) == 5)

    # --- shops are independent -----------------------------------------------------------------
    print()
    r = db.record_shop_observation("ShopB", total_sales=50,
                                   collected_at="2026-08-02T00:00:00+00:00")
    check("a new shop starts its own baseline", r["basis"] == "baseline")
    check("and does not see ShopA's history", len(db.get_shop_history("ShopB")) == 1)

    # --- the calibration target B-03 needs -----------------------------------------------------
    print()
    rate = db.latest_shop_rate("ShopA")
    check("latest_shop_rate returns the most recent measured per-day rate",
          rate == 20.0, f"got {rate}")
    check("a shop with only a baseline has no rate yet",
          db.latest_shop_rate("ShopB") is None)
    check("an unknown shop is None, not 0.0",
          db.latest_shop_rate("NeverSeen") is None)

    # --- the tracker end to end, no network -----------------------------------------------------
    print()
    from etsy.analytics import daily_tracker

    class FakeScrape:
        """Stands in for ShopScraper via monkeypatch; None means the scrape failed."""
        def __init__(self, by_shop):
            self.by_shop = by_shop

        def get_shop_metrics(self, shop_name):
            return self.by_shop.get(shop_name)

    db2 = MarketDatabase(db_path=os.path.join(tmp, "tracker.db"))
    original = daily_tracker.ShopScraper
    daily_tracker.ShopScraper = lambda api: FakeScrape({
        "Good": {"total_sales": 500, "total_reviews": 100},
        "Broken": None,                       # scrape failed
        "NoSales": {"total_reviews": 5},      # page parsed, no sales figure
    })
    try:
        rows = daily_tracker.run_daily_tracker(
            shops_to_track=["Good", "Broken", "NoSales"], db=db2, public_api=object())
    finally:
        daily_tracker.ShopScraper = original

    check("only shops that returned a figure are recorded",
          len(rows) == 1 and rows[0]["shop_name"] == "Good", f"got {rows}")
    check("a failed scrape is NOT stored as zero sales",
          db2.get_shop_history("Broken") == [] and db2.get_shop_history("NoSales") == [])
    check("the first tracked run is a baseline", rows[0]["basis"] == "baseline")
    check("so no rate exists yet — and it reports None, not 0.0",
          db2.latest_shop_rate("Good") is None)

    # --- the shop list is config, not source ------------------------------------------------------
    print()
    saved = daily_tracker.SHOPS_FILE
    daily_tracker.SHOPS_FILE = os.path.join(tmp, "shops.json")
    try:
        check("no config file means no shops, not a crash",
              daily_tracker.load_tracked_shops() == [])
        daily_tracker.save_tracked_shops(["ShopA", "ShopB", "ShopA"])
        check("shops are de-duplicated on save",
              daily_tracker.load_tracked_shops() == ["ShopA", "ShopB"],
              f"got {daily_tracker.load_tracked_shops()}")
    finally:
        daily_tracker.SHOPS_FILE = saved

    # --- the counter's own resolution is the error bar on every delta ------------------
    # Measured live: shopflowerlane displayed 25,100 sales on 15 Aug and 25,100 on
    # 19 Aug. The old code recorded that as sales_per_day 0.0, basis measured_delta —
    # a confident claim that a 25,000-sale shop had stopped selling for five days.
    print()
    dbq = MarketDatabase(db_path=os.path.join(tmp, "quantised.db"))
    dbq.record_shop_observation("big", 25100, collected_at="2026-08-15T00:00:00+00:00")
    q = dbq.record_shop_observation("big", 25100, collected_at="2026-08-19T16:00:00+00:00")
    check("a quantised counter that did not move is NOT a measured rate",
          q["basis"] == "below_resolution", q["basis"])
    check("no rate is stored at all — 0.0/day would claim the shop sold nothing",
          q["sales_per_day"] is None, q["sales_per_day"])
    check("an upper BOUND is stored instead, never a rate",
          q["sales_per_day_upper"] is not None and q["sales_per_day_upper"] > 0,
          q["sales_per_day_upper"])
    check("the bound is (resolution - 1) / window, i.e. what is genuinely known",
          abs(q["sales_per_day_upper"] - 99 / q["window_days"]) < 0.01,
          q["sales_per_day_upper"])
    check("the resolution that produced the bound is recorded with it",
          q["counter_resolution"] == 100, q["counter_resolution"])
    check("and latest_shop_rate refuses rather than returning the bound as a rate",
          dbq.latest_shop_rate("big") is None)

    # A small shop's counter is exact, so zero really is zero.
    dbq.record_shop_observation("small", 843, collected_at="2026-08-15T00:00:00+00:00")
    e = dbq.record_shop_observation("small", 843, collected_at="2026-08-19T16:00:00+00:00")
    check("an UNROUNDED counter that did not move is a real measured zero",
          e["basis"] == "measured_delta" and e["sales_per_day"] == 0.0, e)
    check("and carries no bound, because none is needed",
          e["sales_per_day_upper"] is None)

    # A real movement is unaffected by any of this.
    dbq.record_shop_observation("mover", 25100, collected_at="2026-08-15T00:00:00+00:00")
    m = dbq.record_shop_observation("mover", 25400, collected_at="2026-08-16T00:00:00+00:00")
    check("a counter that DID move still reports a measured rate",
          m["basis"] == "measured_delta" and m["sales_per_day"] == 300.0, m)

    # A bound over a 9-minute window is arithmetically true and excludes nothing.
    short = dbq.record_shop_observation("big", 25100,
                                        collected_at="2026-08-19T16:09:00+00:00")
    check("a bound over a sub-day window is marked uninformative, not reported as a limit",
          not MarketDatabase.bound_is_informative(short["window_days"]),
          short["window_days"])
    check("a bound over several days IS informative",
          MarketDatabase.bound_is_informative(q["window_days"]), q["window_days"])
    check("informativeness needs a real window, and None is not one",
          not MarketDatabase.bound_is_informative(None))

    check("resolution is inferred from the number, not from its magnitude",
          [MarketDatabase.counter_resolution(n) for n in (843, 8143, 8100, 25000)]
          == [1, 1, 100, 1000])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

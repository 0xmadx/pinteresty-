"""
daily_tracker.py

Layer: analytics/ (I/O — scrapes shop pages, writes to the market database)
Purpose: record each tracked shop's lifetime sales counter and derive the sales
         delta between readings. This is the system's ONE measured sales number;
         every other sales figure in the repo is inferred.

Key decision: the delta and its window are computed and stored by
`MarketDatabase.record_shop_observation`, not here. The previous version printed
the delta and kept only the cumulative totals in a JSON file, so the one measured
number in the system was written to stdout and thrown away.

Four defects this replaces (all in the JSON-file version):
  1. the delta was printed, never stored — nothing could calibrate against it
  2. a gap of any length was reported as "Daily Delta"; a Monday→Friday run is a
     4-day figure and read as daily it inflates every rate 4x
  3. a second run on the same day silently moved the baseline for the next delta
  4. it was a sixth storage silo, unjoinable to anything else

See BIASES_AND_BLIND_SPOTS.md B-03: badge-derived sales ("17 bought today") are
observed only on above-threshold days and must be bounded against a measured
rate. `latest_shop_rate()` is that rate.
"""
import argparse
import json
import os

from core import runlog
from core.database import MarketDatabase
from core.runlog import logged_stage
from core.shop_scraper import ShopScraper
from etsy.api.public.api import EtsyPublicAPI

# Which shops to track. Kept as config rather than hardcoded in __main__, so a
# scheduled run does not depend on someone editing the source.
SHOPS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracked_shops.json")


def load_tracked_shops():
    """Shop names to track, or [] when none configured."""
    if not os.path.exists(SHOPS_FILE):
        return []
    with open(SHOPS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("shops", []) if isinstance(data, dict) else list(data)


def save_tracked_shops(shops):
    with open(SHOPS_FILE, "w", encoding="utf-8") as f:
        json.dump({"shops": sorted(set(shops))}, f, indent=2)
    return SHOPS_FILE


@logged_stage("daily_tracker")
def run_daily_tracker(shops_to_track=None, db=None, public_api=None):
    """Record one reading per shop. Returns the list of stored observations."""
    shops_to_track = shops_to_track if shops_to_track is not None else load_tracked_shops()
    if not shops_to_track:
        print(f"[-] No shops configured. Add them with:\n"
              f"      python -m etsy.analytics.daily_tracker --add <shop_name>\n"
              f"    Until a shop is tracked, the daily delta cannot be measured and "
              f"badge-derived sales figures have nothing to be calibrated against.")
        return []

    db = db or MarketDatabase()
    public_api = public_api or EtsyPublicAPI()
    scraper = ShopScraper(public_api)

    stored, failed = [], 0
    for shop_name in shops_to_track:
        print(f"[*] Tracking: {shop_name}")
        metrics = scraper.get_shop_metrics(shop_name)

        # No reading is not a reading of zero. Skipping keeps the gap visible in the
        # history rather than writing a fake datapoint that would produce a large
        # negative delta on the next successful run.
        if not metrics or metrics.get("total_sales") is None:
            print(f"    [-] No sales figure returned — skipped, not recorded as 0")
            failed += 1
            continue

        row = db.record_shop_observation(
            shop_name,
            total_sales=metrics["total_sales"],
            total_reviews=metrics.get("total_reviews"),
        )
        stored.append(row)

        if row["basis"] == "baseline":
            print(f"    [+] Baseline set at {row['total_sales']:,} lifetime sales. "
                  f"The first delta arrives on the next run.")
        elif row["basis"] == "counter_decreased":
            print(f"    [!] Lifetime sales went DOWN ({row['total_sales']:,}). A shop "
                  f"cannot un-sell — the scrape or the shop identity changed. "
                  f"Observation kept, delta refused.")
        else:
            print(f"    [+] +{row['sales_delta']:,} sales over {row['window_days']:g} "
                  f"day(s) = {row['sales_per_day']:,.2f}/day  "
                  f"(total {row['total_sales']:,})")

    runlog.count(rows_in=len(shops_to_track), rows_out=len(stored), errors=failed)
    measured = [r for r in stored if r["basis"] == "measured_delta"]
    print(f"\n[+] {len(stored)} observation(s) recorded, {len(measured)} with a measured "
          f"rate, {failed} failed.")
    if stored and not measured:
        print(f"[i] No rate yet — every shop is on its baseline. Run again tomorrow.")
    return stored


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record the daily sales delta.")
    parser.add_argument("--add", metavar="SHOP", nargs="+",
                        help="Add shop name(s) to the tracked list and exit")
    parser.add_argument("--list", action="store_true", help="Show tracked shops and exit")
    args = parser.parse_args(argv)

    if args.add:
        shops = load_tracked_shops() + args.add
        path = save_tracked_shops(shops)
        print(f"[+] Now tracking {len(set(shops))} shop(s). Saved to {path}")
        return 0

    if args.list:
        shops = load_tracked_shops()
        print(f"[+] {len(shops)} tracked shop(s): {', '.join(shops) or '(none)'}")
        return 0

    run_daily_tracker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

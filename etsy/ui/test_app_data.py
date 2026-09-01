"""The read layer is honest — the one seam MCP reads the database through.

Extracted from the old `test_app.py` when the UI was deleted (D-52). That file
tested two things: the read layer (`app_data`) and the page renderer (`app_page`).
The renderer is gone; the read layer is now MORE important, not less, because MCP
is its only consumer and there is no second screen to notice a wrong number.

What is asserted here is discipline, not formatting: demand stays separate from
competition, every number carries its basis, absent never becomes zero, and walls
are kept in the pool rather than filtered away at the data layer.

    .venv/Scripts/python.exe -m etsy.ui.test_app_data
"""
import os
import tempfile
from datetime import datetime, timezone

from core.database import MarketDatabase
from etsy.ui import app_data

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)

# ⚠️ Every seeded row gets an EXPLICIT collected_at, including the two trend rows.
# The old test omitted it there and let record_trend default to the wall clock —
# and `build_pinterest` returns only rows matching MAX(collected_at), so whenever
# the two inserts straddled a second boundary the moment vanished and the suite
# died on an IndexError. It passed on rerun, which is the worst kind of failure.
# Production was never affected (trends_bridge passes one shared timestamp for a
# whole run — verified: 97 rows share it), so this was a test-only race, of
# exactly the kind `etsy-pipeline-work` warns about: never mix a wall clock with
# fixed data in one test.
STAMP = "2026-08-20T00:00:00+00:00"


def seed(path):
    db = MarketDatabase(db_path=path)
    db.record_keyword("mom necklace", volume=12000, competition=350000, cvr=0.0003,
                      cvr_source="measured", price_low=17, price_high=21,
                      collected_at="2026-08-13T00:00:00+00:00")
    db.record_keyword("mom necklace", volume=13000, competition=351000, cvr=0.0003,
                      cvr_source="measured", price_low=17, price_high=21,
                      collected_at="2026-08-19T00:00:00+00:00")
    db.record_keyword("never priced", volume=500, competition=None, cvr=None,
                      cvr_source="default", collected_at="2026-08-19T00:00:00+00:00")
    db.record_discovered("custom family name necklace", seed="mom necklace",
                         volume=11642, supply=6676, demand_per_listing=1.744,
                         verdict="winnable", timing="evergreen",
                         collected_at="2026-08-20T00:00:00+00:00")
    db.record_discovered("dead wall", seed="mom necklace", demand_per_listing=0.01,
                         verdict="wall", timing="evergreen",
                         collected_at="2026-08-20T00:00:00+00:00")
    db.record_trend(trend_name="christmas", source="pinterest_moments", country="US",
                    collected_at=STAMP,
                    takeoff_timestamp="2026-10-28", peak_date="2026-12-09",
                    list_by="2026-09-16", phase="approaching", takeoff_basis="measured")
    db.record_trend(trend_name="Cottagecore", source="pinterest_featured_topics",
                    country="US", collected_at=STAMP,
                    dominant_color="#a0a060", color_share=0.3,
                    velocity=1.4, growth_mom=0.5)
    return db


def main():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "a.db")
    seed(path)

    # --- the read layer keeps demand and competition apart ----------------------------
    print()
    snap = app_data.build_snapshot(path, now=NOW)
    check("the snapshot has one object per view",
          {"meta", "keywords", "competition", "discovered", "pinterest",
           "calendar", "shops"} <= set(snap))
    check("keywords is DEMAND only — no saturation share leaks in",
          all("saturation" not in k and "decisive" not in k for k in snap["keywords"]))
    check("competition is a SEPARATE object, page-one sample",
          isinstance(snap["competition"], list))

    # --- absent is not zero -----------------------------------------------------------
    print()
    npr = next(k for k in snap["keywords"] if k["term"] == "never priced")
    check("a term with no supply has a null ratio, not 0",
          npr["demand_per_listing"] is None, npr)
    check("and is not flagged a wall on missing data",
          npr["is_wall"] is False, npr)
    check("a default CVR carries its basis, so the client can mark it a guess",
          npr["cvr_basis"] == "default")

    # --- history is carried, so a caller can see movement -----------------------------
    print()
    mn = next(k for k in snap["keywords"] if k["term"] == "mom necklace")
    check("a term's full reading history is included as a series",
          len(mn["series"]) == 2, mn["series"])
    check("the series carries volume per reading",
          mn["series"][0]["volume"] == 12000 and mn["series"][1]["volume"] == 13000)

    # --- ranked by winnability, walls kept --------------------------------------------
    print()
    check("discovered is ranked by demand-per-listing, winnable first",
          snap["discovered"][0]["term"] == "custom family name necklace")
    check("walls are kept in the pool, not filtered at the data layer",
          any(d["verdict"] == "wall" for d in snap["discovered"]))

    # --- pinterest, the underused half ------------------------------------------------
    print()
    p = snap["pinterest"]
    check("moments and topics are separate", "moments" in p and "topics" in p)
    check("a moment carries its timing",
          p["moments"] and p["moments"][0]["list_by"] is not None, p["moments"])
    check("a topic carries its colour and velocity",
          p["topics"][0]["color"] == "#a0a060" and p["topics"][0]["velocity"] == 1.4)

    # --- meta: freshness and the settings basis ---------------------------------------
    print()
    check("meta carries generated_at for freshness", snap["meta"]["generated_at"])
    check("and whether verdicts are provisional",
          "verdicts_provisional" in snap["meta"])

    # --- gather_shops: moved here from market_page, and previously untested ------------
    # It reads the operator's real settings for the shop list, so the CONTRACT is
    # what gets asserted, not the content — a shape test that holds whether or not
    # any shop is currently tracked.
    print()
    shops = app_data.gather_shops(path)
    check("gather_shops returns a list", isinstance(shops, list), type(shops))
    check("every entry carries shop, latest, rate_bound and matched",
          all({"shop", "latest", "rate_bound", "matched"} <= set(s) for s in shops),
          shops[:1])
    check("build_shops consumes it without a presentation import",
          isinstance(snap["shops"], list))

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())

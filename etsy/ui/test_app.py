"""The interactive app: the read layer is honest, and the page is self-contained.

Two things are tested. The read layer (app_data) must keep the same discipline the
screens keep — separate demand from competition, carry basis, never turn absent
into zero — because it is the single seam both the app and a future server read
through. And the page (app_page) must be genuinely self-contained: no external
script or style, valid JSON embedded, so a file opened from disk renders without a
network.

    .venv/Scripts/python.exe -m etsy.ui.test_app
"""
import json
import os
import re
import tempfile
from datetime import datetime, timezone

from core.database import MarketDatabase
from etsy.ui import app_data, app_page

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
                    takeoff_timestamp="2026-10-28", peak_date="2026-12-09",
                    list_by="2026-09-16", phase="approaching", takeoff_basis="measured")
    db.record_trend(trend_name="Cottagecore", source="pinterest_featured_topics",
                    country="US", dominant_color="#a0a060", color_share=0.3,
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

    # --- history is carried for the sparkline -----------------------------------------
    print()
    mn = next(k for k in snap["keywords"] if k["term"] == "mom necklace")
    check("a term's full reading history is included as a series",
          len(mn["series"]) == 2, mn["series"])
    check("the series carries volume per reading, for the chart",
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
    check("a moment carries its timing", p["moments"][0]["list_by"] is not None)
    check("a topic carries its colour and velocity",
          p["topics"][0]["color"] == "#a0a060" and p["topics"][0]["velocity"] == 1.4)

    # --- meta: freshness and the settings basis ---------------------------------------
    print()
    check("meta carries generated_at for freshness", snap["meta"]["generated_at"])
    check("and whether verdicts are provisional",
          "verdicts_provisional" in snap["meta"])

    # --- the page is SELF-CONTAINED ---------------------------------------------------
    print()
    h = app_page.render_html(snap, now=NOW)
    check("no external script src — nothing to fetch",
          "<script src" not in h and "src=\"http" not in h)
    check("no external stylesheet — renders offline",
          "<link" not in h and "@import" not in h)
    check("the whole dataset is embedded as JSON", 'id="data"' in h)

    embedded = re.search(r'<script id="data"[^>]*>(.*?)</script>', h, re.DOTALL)
    check("the embedded JSON parses", embedded is not None)
    parsed = json.loads(embedded.group(1).replace("<\\/", "</"))
    check("and round-trips the snapshot",
          parsed["discovered"][0]["term"] == "custom family name necklace")

    # --- the page cannot be broken by a stray </script> in the data -------------------
    print()
    nasty = app_data.build_snapshot(path, now=NOW)
    nasty["keywords"][0]["term"] = "a</script><script>alert(1)</script>"
    nh = app_page.render_html(nasty, now=NOW)
    # The escape neutralises the CLOSE tag; a bare <script> as JSON text cannot
    # execute inside a <script type="application/json"> block, only </script> can
    # end it — and every </ in the data is escaped to <\/.
    check("the </script> breakout sequence is escaped, not left intact",
          "</script><script>alert" not in nh)
    check("and the escaped form is what appears instead",
          r"<\/script>" in nh)

    # --- themes -----------------------------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))

    # --- the six views are present ----------------------------------------------------
    print()
    for view in ("dashboard", "discover", "etsy", "pinterest", "calendar", "shops"):
        check(f"the {view} view container exists", f'id="v-{view}"' in h)

    # --- determinism ------------------------------------------------------------------
    print()
    check("the same snapshot renders identically twice",
          app_page.render_html(snap, now=NOW) == app_page.render_html(snap, now=NOW))

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())

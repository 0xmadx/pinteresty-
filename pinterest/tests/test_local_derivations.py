"""Live verification that local math equals what the endpoint would have returned.

Every claim in `endpoints/local_math.py` and `endpoints/series_store.py` is checked here
against a real response. If Pinterest changes a normalization or starts omitting an event
block, this fails and names the derivation that went stale — which matters more than usual,
because a broken derivation returns a plausible number rather than an error.

    .venv/Scripts/python.exe pinterest/tests/test_local_derivations.py
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.local_math import (calendar, event_summary, intent_ratio,
                                            ranked_on, resort, velocity)
from pinterest.endpoints.series_store import SeriesStore, slice_window, window_points

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


api = PinterestTrendsAPI()
END = api.latest_available_date()
print(f"end_date={END}\n")

# -- 1. the free series that related/prefix hand back ----------------------------------
print("=== 1. harvested series vs /metrics/ ===")
seed = "cute august nails"
rel = api.related_terms(seed)
pre = api.prefix_match(seed)
rterms = [r["term"] for r in rel]
ref = {s["term"]: [p["count"] for p in s["counts"]]
       for s in api.metrics(rterms, days=365, store_bypass=True)}

exact = sum(1 for r in rel if ref.get(r["term"]) == r["counts"])
check("related_terms counts[] is byte-identical to /metrics/?days=365",
      exact == len(rel), f"{exact}/{len(rel)} matched")

pterms = [r["term"] for r in pre[:5]]
pref = {s["term"]: [p["count"] for p in s["counts"]]
        for s in api.metrics(pterms, days=365, store_bypass=True)}
worst = 0
for r in pre[:5]:
    m = pref.get(r["term"])
    if m and len(m) == len(r["counts"]) + 1:
        worst = max(worst, max(abs(a - b) for a, b in zip(r["counts"], m[1:])))
check("prefix_match counts[] == metrics[1:] within 2 units (renormalized)",
      worst <= 2, f"max deviation {worst}")

# -- 2. window slicing ------------------------------------------------------------------
print("\n=== 2. slicing a long window instead of requesting a short one ===")
check("window_points matches the API's bucket counts",
      [window_points(d) for d in (30, 90, 180, 365, 730)] == [5, 13, 26, 53, 105])

tab = api.top_trends("growing")
terms = [r["term"] for r in tab["values"]][:14]
full = {s["term"]: [p["count"] for p in s["counts"]]
        for s in api.metrics(terms, days=365, store_bypass=True)}
for days in (30, 90):
    live = {s["term"]: [p["count"] for p in s["counts"]]
            for s in api.metrics(terms, days=days, store_bypass=True)}
    ok = sum(1 for t, want in live.items() if slice_window(full[t], days) == want)
    # The known lossy case is a term whose recent weeks round to 0 inside the 365 series;
    # the store refuses to serve those, so a majority match is the correct expectation.
    check(f"slice_window reproduces days={days} for most terms",
          ok >= len(live) - 2, f"{ok}/{len(live)} exact")

store = SeriesStore()
lossy = [t for t, c in full.items() if max(c[-13:]) < 25]
refused = [t for t in lossy if store.get(t, days=90, end_date=END) is None]
check("store refuses to serve windows the source rounding destroyed",
      len(refused) == len(lossy), f"{len(refused)}/{len(lossy)} refused")

# -- 3. shopping: one call, three events ------------------------------------------------
print("\n=== 3. one /top/ call covers all three events ===")
clicks = api.top_categories(event="OUTBOUND_CLICK")
have_all = all(all(k in (r.get("summary") or {})
                   for k in ("outbound_clicks", "saves", "engagement")) for r in clicks)
check("every OUTBOUND_CLICK row carries saves and engagement too", have_all)
check("intent_ratio computes from that single response",
      any(intent_ratio(r) is not None for r in clicks))

saves = api.top_categories(event="SAVE")
diff = ranked_on({"clicks": clicks, "saves": saves})
check("the click/save ranking sets genuinely differ",
      len(diff["clicks_not_saves"]) > 0,
      f"{len(clicks)} click rows vs {len(saves)} save rows")

# -- 4. order_by is a local sort ---------------------------------------------------------
print("\n=== 4. order_by without a second request ===")
for ob in ("RELATIVE_VOLUME", "PCT_CHANGE_MOM"):
    a = [r["product_category"]
         for r in api.top_categories(event="OUTBOUND_CLICK", order_by=ob)]
    b = [r["product_category"] for r in resort(clicks, ob, "OUTBOUND_CLICK")]
    check(f"local resort reproduces the {ob} ordering exactly", a == b,
          f"first divergence at "
          f"{next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)}")

# -- 5. moments: launch dates are subtraction -------------------------------------------
print("\n=== 5. launch planning from the calendar ===")
moments = api.moments_calendar("US")
plans = calendar(moments, lead_weeks=6)
check("every moment with a takeoff yields a launch plan",
      len(plans) == len([m for m in moments if m.get("takeoff_ms")]))
check("plans carry a list_by date and weeks_left",
      all(p["list_by"] and p["weeks_left"] is not None for p in plans))
if plans:
    p = plans[0]
    print(f"     soonest: {p['moment']} — list by {p['list_by']} "
          f"({p['weeks_left']} weeks), takeoff {p['takeoff']}, phase {p['phase']}")

# -- 6. the recorded negatives -----------------------------------------------------------
print("\n=== 6. what is NOT derivable (guards against a plausible wrong number) ===")
rows = {r["term"]: r for r in api.top_trends("seasonal")["values"]}
sub = [t for t in list(rows)[:10] if t in full or True][:10]
full2 = {s["term"]: s for s in api.metrics(sub, days=365, store_bypass=True)}
naive_ok = 0
for t in sub:
    s = full2.get(t)
    if not s:
        continue
    c = [p["count"] for p in s["counts"]]
    gr = s.get("growth_rates") or {}
    if gr.get("wow_change") is not None and len(c) > 1 and c[-2]:
        naive = round((c[-1] - c[-2]) / c[-2] * 100)
        naive_ok += (naive == gr["wow_change"])
check("growth_rates do NOT reproduce from point deltas (so we store, not recompute)",
      naive_ok <= 1, f"{naive_ok} coincidental matches")
check("velocity() is available for bare prefix series",
      velocity([1] * 4 + [2] * 4) is not None)

# -- 7. end-to-end: does the store actually remove requests? -----------------------------
print("\n=== 7. end-to-end saving ===")
fresh = PinterestTrendsAPI()
before = fresh.saved_requests
out = fresh.metrics(rterms, days=365)
check("a fully-harvested term list is served with zero fetches",
      fresh.saved_requests == before + 1 and len(out) == len(rterms),
      f"saved={fresh.saved_requests - before} returned={len(out) if out else 0}")
check("locally-served series are labelled with provenance",
      all(s.get("_precision") in ("exact", "approx") for s in out))
print(f"     store now holds {SeriesStore().stats()}")
fresh.close()
api.close()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

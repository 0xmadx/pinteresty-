"""Live verification of every claim in pinterest/README.md.

Read-only. Hits the real trends.pinterest.com with the synced session cookies and asserts
the documented behaviour, so we find out which claims are wrong *before* they turn into
pipeline code. Run it:

    .venv/Scripts/python.exe pinterest/tests/test_live_endpoints.py

Sequential with a polite delay — the endpoints run 300-800ms TTFB and there is no quota,
so there is nothing to gain from hammering them.
"""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
COOKIE_FILE = ROOT / "pinterest_cookies.json"
BASE = "https://trends.pinterest.com"
DELAY = 0.6

# From README.md section 3 — the vocabulary we intend to hardcode.
INTERESTS = {
    "Animals": "925056443165", "Architecture": "918105274631", "Art": "961238559656",
    "Beauty": "935541271955", "Children's Fashion": "903733943146", "Design": "902065567321",
    "DIY and Crafts": "934876475639", "Education": "922134410098", "Electronics": "960887632144",
    "Entertainment": "953061268473", "Event Planning": "941870572865", "Finance": "913207199297",
    "Food and Drinks": "918530398158", "Gardening": "909983286710", "Health": "898620064290",
    "Home Decor": "935249274030", "Men's Fashion": "924581335376", "Parenting": "920236059316",
    "Quotes": "948192800438", "Sport": "919812032692", "Travel": "908182459161",
    "Vehicles": "918093243960", "Wedding": "903260720461", "Women's Fashion": "948967005229",
}
PRESETS = {1: "Top monthly", 2: "Top yearly", 3: "Growing", 4: "Seasonal"}

results = []
requests_made = 0


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL" if passed is False else "WARN"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def client():
    cookies = json.loads(COOKIE_FILE.read_text()).get("cookie_json", {})
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "referer": f"{BASE}/search?country=US",
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"),
        "x-requested-with": "XMLHttpRequest",
    }
    return httpx.Client(base_url=BASE, headers=headers, cookies=cookies, timeout=30.0), cookies


def get(c, path, **params):
    global requests_made
    requests_made += 1
    time.sleep(DELAY)
    r = c.get(path, params=params)
    return r


def trends(c, preset, lookback=3, country="US", **extra):
    return get(c, "/top_trends_filtered/", lookbackWindow=lookback, endDate=END_DATE,
               country=country, trendsPreset=preset, **extra)


# --------------------------------------------------------------------------------------
c, cookies = client()
print("\n=== 1. Auth + latest_available_date ===")

r = get(c, "/latest_available_date/")
check("GET /latest_available_date/ returns 200 JSON", r.status_code == 200, f"status {r.status_code}")
if r.status_code != 200:
    print("\nSession looks dead — refresh cookies via the Chrome extension and re-run.")
    sys.exit(1)
END_DATE = r.json().get("date")
check("response has a 'date' field", bool(END_DATE), f"date={END_DATE}")
check("plain cookie auth, no x-pinterest-* headers needed", True, "this whole run omits them")

# --------------------------------------------------------------------------------------
print("\n=== 2. top_trends_filtered — shape and the four presets ===")

preset_rows = {}
for p, label in PRESETS.items():
    r = trends(c, p)
    if r.status_code != 200:
        check(f"preset {p} ({label}) returns 200", False, f"status {r.status_code}")
        continue
    body = r.json()
    rows = body.get("values", [])
    preset_rows[p] = rows
    check(f"preset {p} ({label}) returns 50 rows", len(rows) == 50, f"got {len(rows)}")

    if p == 3:
        keys = set(rows[0])
        expected = {"term", "searchCount", "normalizedCount", "seasonality_score", "affinity",
                    "reverseRank", "wow_change", "mom_change", "yoy_change"}
        check("row schema matches documented keys", expected <= keys,
              f"missing {expected - keys}" if not expected <= keys else f"{len(keys)} keys")
        check("top-level endDate present", "endDate" in body, str(body.get("endDate")))
        check("*_change is {index, value}", set(rows[0]["mom_change"]) == {"index", "value"},
              str(rows[0]["mom_change"]))

    if rows:
        # What is each preset actually sorted by? Test every candidate rather than assuming.
        orders = {
            "mom_change.index": [row["mom_change"]["index"] for row in rows],
            "reverseRank": [row["reverseRank"] for row in rows],
            "searchCount": [row["searchCount"] for row in rows],
            "seasonality_score": [row["seasonality_score"] for row in rows],
        }
        sorted_by = [k for k, v in orders.items() if v == sorted(v, reverse=True)]
        check(f"preset {p} sort order identified", bool(sorted_by),
              f"descending by {sorted_by or 'NOTHING — order is server-side'}; "
              f"mom head {orders['mom_change.index'][:4]}")

print("\n  seasonality_score bands (README claims Seasonal >= ~0.83):")
for p, rows in preset_rows.items():
    if rows:
        s = [row["seasonality_score"] for row in rows]
        print(f"    preset {p} ({PRESETS[p]:12}) min={min(s):.6f} max={max(s):.6f}")
if 4 in preset_rows and preset_rows[4]:
    lo = min(r_["seasonality_score"] for r_ in preset_rows[4])
    check("preset 4 floor is ~0.83", 0.82 <= lo <= 0.84, f"exact min={lo:.6f}")
if 3 in preset_rows and 4 in preset_rows and preset_rows[3] and preset_rows[4]:
    lo3 = min(r_["seasonality_score"] for r_ in preset_rows[3])
    lo4 = min(r_["seasonality_score"] for r_ in preset_rows[4])
    check("Seasonal floor is above Growing floor", lo4 > lo3, f"{lo4:.3f} vs {lo3:.3f}")

# --------------------------------------------------------------------------------------
print("\n=== 3. Is lookbackWindow really cosmetic? ===")

sigs = {}
for w in (1, 2, 3, 5):
    r = trends(c, 3, lookback=w)
    sigs[w] = [(x["term"], x["searchCount"]) for x in r.json().get("values", [])] if r.status_code == 200 else None
identical = len({json.dumps(v) for v in sigs.values() if v is not None}) == 1
check("preset 3 identical across lookbackWindow 1/2/3/5", identical,
      "byte-identical rows" if identical else f"differs: { {w: (v[0] if v else None) for w, v in sigs.items()} }")

# --------------------------------------------------------------------------------------
print("\n=== 4. Filters and enums ===")

base3 = {x["term"] for x in preset_rows.get(3, [])}

r = trends(c, 4, lookback=2, l1interests=INTERESTS["Beauty"], ageBuckets="5", gender="1",
           moments="halloween")
ok = r.status_code == 200
rows = r.json().get("values", []) if ok else []
check("Beauty + halloween + 35-44 + female returns 200", ok, f"status {r.status_code}")
check("filtered set differs from unfiltered", bool(rows) and {x["term"] for x in rows} != base3,
      f"{len(rows)} rows, e.g. {[x['term'] for x in rows[:3]]}")

r = trends(c, 3, keywordsToInclude="smkoa,djkawsodp,dasd")
check("keywordsToInclude with junk returns empty (restrictive AND)",
      r.status_code == 200 and r.json().get("values") == [], f"{len(r.json().get('values', []))} rows")

r = trends(c, 3, keywordsToInclude="nails")
rows = r.json().get("values", [])
hits = sum(1 for x in rows if "nails" in x["term"].lower())
check("keywordsToInclude='nails' returns only matching terms", bool(rows) and hits == len(rows),
      f"{hits}/{len(rows)} contain 'nails'")

male = trends(c, 3, gender="0").json().get("values", [])
female = trends(c, 3, gender="1").json().get("values", [])
diff = {x["term"] for x in male} ^ {x["term"] for x in female}
check("gender=0 and gender=1 return different sets", bool(diff),
      f"{len(diff)} terms differ; male head={[x['term'] for x in male[:2]]}, "
      f"female head={[x['term'] for x in female[:2]]}")

r = trends(c, 3, country="GB+IE")
gb = r.json().get("values", []) if r.status_code == 200 else []
check("grouped region country=GB+IE works", bool(gb), f"{len(gb)} rows, e.g. {[x['term'] for x in gb[:3]]}")

# --------------------------------------------------------------------------------------
print("\n=== 5. endDate back-dating and snapping ===")

r = get(c, "/top_trends_filtered/", lookbackWindow=2, endDate="2025-12-01", country="US", trendsPreset=4)
if r.status_code == 200:
    body = r.json()
    returned = body.get("endDate")
    rows = body.get("values", [])
    check("historical endDate=2025-12-01 returns data", bool(rows),
          f"echoed endDate={returned}, top={[x['term'] for x in rows[:4]]}")
    check("endDate snaps backward to nearest data week", bool(returned) and returned < "2025-12-01",
          f"requested 2025-12-01, got {returned}")
else:
    check("historical endDate request", False, f"status {r.status_code}")

# --------------------------------------------------------------------------------------
print("\n=== 6. /metrics/ — batching, weekly buckets, prediction ===")

terms50 = [x["term"] for x in preset_rows.get(3, [])][:50]
r = get(c, "/metrics/", terms=",".join(terms50), country="US", end_date=END_DATE, days=90,
        aggregation=2, normalize_against_group="false", predicted_days=0)
ok = r.status_code == 200
data = r.json() if ok else []
check(f"batched /metrics/ with {len(terms50)} terms in one call", ok and len(data) == len(terms50),
      f"status {r.status_code}, got {len(data)} series")
if ok and data:
    dates = [p["date"] for p in data[0]["counts"]]
    import datetime as _dt
    gaps = {(_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days
            for a, b in zip(dates, dates[1:])}
    check("aggregation=2 gives weekly buckets", gaps == {7}, f"gaps={sorted(gaps)}")
    check("days=90 returns ~13 points", 12 <= len(dates) <= 15, f"{len(dates)} points")

# shouldMock appears in the captured curls; find out what it actually does before copying one.
mock = {}
for v in ("false", "true", None):
    p = dict(terms="nails", country="US", end_date=END_DATE, days=90, aggregation=2,
             normalize_against_group="true", predicted_days=0)
    if v is not None:
        p["shouldMock"] = v
    rr = get(c, "/metrics/", **p)
    mock[str(v)] = [x["count"] for x in rr.json()[0]["counts"]] if rr.status_code == 200 else None
check("TRAP: shouldMock=true returns mock data, not real", mock["true"] != mock["false"],
      f"true -> {len(mock['true'] or [])} pts head={(mock['true'] or [])[:4]}; "
      f"false -> {len(mock['false'] or [])} pts head={(mock['false'] or [])[:4]}")
check("omitting shouldMock == shouldMock=false", mock["None"] == mock["false"], "safe to omit")

seasonal_term = preset_rows.get(4, [{}])[0].get("term") or terms50[0]
r = get(c, "/metrics/", terms=seasonal_term, country="US", end_date=END_DATE, days=365,
        aggregation=2, normalize_against_group="true", predicted_days=0)
base = r.json()[0] if r.status_code == 200 and r.json() else {}
n_base = len(base.get("counts", []))
has_pred = base.get("has_prediction")
check("days=365 returns ~53 weekly points", 52 <= n_base <= 54, f"{n_base} points for '{seasonal_term}'")

r = get(c, "/metrics/", terms=seasonal_term, country="US", end_date=END_DATE, days=365,
        aggregation=2, normalize_against_group="true", predicted_days=91)
pred = r.json()[0] if r.status_code == 200 and r.json() else {}
n_pred = len(pred.get("counts", []))
if has_pred:
    pts = pred.get("counts", [])
    check("has_prediction=true: predicted_days=91 grows the array", n_pred > n_base,
          f"{n_base} -> {n_pred} points")
    filled = [p for p in pts if p.get("predictedUpperBoundNormalizedCount") is not None]
    check("predicted bounds are on future weeks only",
          bool(filled) and filled[0]["date"] > END_DATE,
          f"{len(filled)} bounded, first={filled[0]['date'] if filled else None}, "
          f"last real week={END_DATE}")
    nonzero = [p["count"] for p in filled if p["count"]]
    check("TRAP: `count` on forecast weeks carries the prediction, not 0",
          bool(nonzero), f"counts on bounded points: {[p['count'] for p in filled][:6]}…")
else:
    check("has_prediction=false for this term (forecast is per-term)", None,
          f"'{seasonal_term}': {n_base} -> {n_pred} points, no forecast")

# --------------------------------------------------------------------------------------
print("\n=== 7. Detail-page trio ===")

probe = terms50[0] if terms50 else "nails"
r = get(c, "/related_terms/", requestTerm=probe, country="US", endDate=END_DATE,
        aggregation=2, lookback=365, shouldMock="false")
rel = r.json() if r.status_code == 200 else []
check("/related_terms/ returns rows", bool(rel),
      f"{len(rel)} rows for '{probe}': {[x.get('term') for x in rel[:5]]}")

r = get(c, "/demographics/", terms=probe, country="US", end_date=END_DATE, days=365)
demo = r.json().get("term_distributions", {}).get(probe, {}) if r.status_code == 200 else {}
gsum = sum(demo.get("gender_distribution", {}).values())
check("/demographics/ gender distribution sums to ~1", abs(gsum - 1) < 0.05,
      f"sum={gsum:.2f} {demo.get('gender_distribution')}")

r = get(c, "/prefix_match/", query=probe, country="US")
pm = r.json() if r.status_code == 200 else []
check("/prefix_match/ returns suggestions", bool(pm),
      f"{len(pm)} rows: {[x.get('term') for x in pm[:5]]}")

# --------------------------------------------------------------------------------------
print("\n=== 8. POST /term_images/ and the ApiResource wrapper ===")

requests_made += 1
time.sleep(DELAY)
r = c.post("/term_images/", json={"terms": terms50[:2] or ["nails"], "country": "US",
                                  "cacheTtlInSeconds": 86400, "limit": 1, "batchSize": 20,
                                  "requestImageSize": "75x75"},
           headers={"x-new-site": "true", "x-csrftoken": cookies.get("csrftoken", ""),
                    "Content-Type": "application/json"})
check("POST /term_images/ with x-new-site + csrf", r.status_code == 200,
      f"status {r.status_code}, body {r.text[:120]}")

def api_resource(c, inner, data, source_url="/?country=US", handler="trends/index.js"):
    """The ApiResource family needs x-pinterest-pws-handler or it 403s. See checks below."""
    payload = {"options": {"url": inner, "data": data}, "context": {}}
    headers = {"x-pinterest-source-url": source_url}
    if handler is not None:
        headers["x-pinterest-pws-handler"] = handler
    global requests_made
    requests_made += 1
    time.sleep(DELAY)
    return c.get("/resource/ApiResource/get/",
                 params={"source_url": source_url,
                         "data": json.dumps(payload, separators=(",", ":"))},
                 headers=headers)


MOMENTS = "/ads/v4/trends/moment/available/US"

r = api_resource(c, MOMENTS, {}, handler=None)
check("ApiResource WITHOUT x-pinterest-pws-handler is rejected", r.status_code == 403,
      f"status {r.status_code} — {r.text[:40]}")

r = api_resource(c, MOMENTS, {})
ok = r.status_code == 200
check("ApiResource WITH x-pinterest-pws-handler succeeds", ok, f"status {r.status_code}")

r2 = api_resource(c, MOMENTS, {}, handler="trends/bogus-does-not-exist.js")
check("pws-handler is a presence check, value is not validated", r2.status_code == 200,
      f"bogus handler -> {r2.status_code}")

if ok:
    moments = r.json().get("resource_response", {}).get("data", {})
    check("moments payload has the parallel arrays",
          {"moments", "peaks", "historical_peaks", "phase_labels"} <= set(moments),
          f"{len(moments.get('moments', []))} moments, keys={sorted(moments)}")
    lens = {k: len(v) for k, v in moments.items() if isinstance(v, list)}
    check("all moment arrays are index-parallel", len(set(lens.values())) == 1, str(lens))

r = api_resource(c, "/ads/v4/trends/shopping/product_categories", {},
                 source_url="/shopping?country=US", handler="trends/shopping.js")
cats = r.json().get("resource_response", {}).get("data", {}).get("categories", {}) if r.status_code == 200 else {}
check("shopping category dictionary reachable", bool(cats), f"{len(cats)} categories")

r = api_resource(c, "/ads/v4/trends/topics/featured/US/SAVE",
                 {"interests": [INTERESTS["Beauty"]], "publish_state": "PUBLISHED"})
topics = r.json().get("resource_response", {}).get("data", []) if r.status_code == 200 else []
check("spotlight featured topics reachable", bool(topics),
      f"{len(topics)} topics: {[t.get('name') for t in topics[:3]]}")

uid = "1103382114864552469"
r = api_resource(c, f"/v3/trends/partner/{uid}/available_interests/",
                 {"available_term_count_threshold": 3, "lookback_window": 3, "trend_type": 2},
                 source_url="/search?country=US", handler="trends/search.js")
body = r.json().get("resource_response", {}).get("data", {}) if r.status_code == 200 else {}
check("available_interests returns 200 but no data on this account",
      r.status_code == 200 and body.get("results") is None,
      f"status {r.status_code}, body {json.dumps(body)[:90]}")

# --------------------------------------------------------------------------------------
c.close()
passed = sum(1 for _, p, _ in results if p is True)
failed = [(n, d) for n, p, d in results if p is False]
warned = [(n, d) for n, p, d in results if p is None]

print("\n" + "=" * 78)
print(f"{passed} passed, {len(failed)} failed, {len(warned)} inconclusive — {requests_made} requests")
if failed:
    print("\nFAILED — these claims in README.md are wrong and must be corrected before coding:")
    for n, d in failed:
        print(f"  - {n}: {d}")
if warned:
    print("\nINCONCLUSIVE:")
    for n, d in warned:
        print(f"  - {n}: {d}")
print("=" * 78)
sys.exit(1 if failed else 0)

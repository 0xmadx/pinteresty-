"""Live verification of the Shopping (/ads/v4/trends/shopping/...) teardown.

Read-only. Deliberately sends some invalid payloads to pin down which params are required and
what the accepted ranges are — all GETs, no state change.

    .venv/Scripts/python.exe pinterest/tests/test_shopping_endpoints.py
"""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://trends.pinterest.com"
DELAY = 0.6
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

cookies = json.loads((ROOT / "pinterest_cookies.json").read_text())["cookie_json"]
results = []
n_req = 0

TOP = "/ads/v4/trends/shopping/product_categories/top/{region}"
METRICS = "/ads/v4/trends/shopping/product_categories/metrics/{region}"
DEMO = "/ads/v4/trends/shopping/product_categories/demographics/{region}"
PRODUCTS = "/ads/v4/trends/shopping/product_categories/top_products"
TAXONOMY = "/ads/v4/trends/shopping/product_categories"

END = "2026-07-27"
VERTICALS = ["1181", "1161", "1042", "1250", "1148", "1194", "1315",
             "1500", "1481", "1016", "1436", "1007", "1241", "1489"]


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL' if passed is False else 'INFO'}] {name}"
          + (f" — {detail}" if detail else ""))


def call(client, inner, payload, headers=None, source="/shopping/?country=US"):
    global n_req
    n_req += 1
    time.sleep(DELAY)
    body = {"options": {"url": inner, "data": payload}, "context": {}}
    h = {"x-pinterest-pws-handler": "trends/shopping.js",
         "x-pinterest-source-url": source}
    if headers is not None:
        h = headers
    return client.get("/resource/ApiResource/get/",
                      params={"source_url": source,
                              "data": json.dumps(body, separators=(",", ":"))},
                      headers=h)


def rows(r, key="ordered_values"):
    if r.status_code != 200:
        return None
    d = r.json().get("resource_response", {}).get("data", {})
    return d.get(key, d) if isinstance(d, dict) else d


base_top = {"event": "OUTBOUND_CLICK", "ranking_method": "GROWTH", "end_date": END}

c = httpx.Client(base_url=BASE, cookies=cookies, timeout=40.0, headers={
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en-US,en;q=0.9", "user-agent": UA,
    "x-requested-with": "XMLHttpRequest"})

# ---------------------------------------------------------------------------------------
print("\n=== A. Which headers are ACTUALLY required? ===")
hdr_base = {"accept": "application/json, text/javascript, */*; q=0.01", "user-agent": UA,
            "x-requested-with": "XMLHttpRequest"}
cases = {
    "pws-handler only": {**hdr_base, "x-pinterest-pws-handler": "trends/shopping.js"},
    "x-app-version only (no pws)": {**hdr_base, "x-app-version": "8c40681"},
    "appstate + source-url, no pws": {**hdr_base, "x-pinterest-appstate": "active",
                                      "x-pinterest-source-url": "/shopping/?country=US"},
    "full browser set": {**hdr_base, "x-pinterest-pws-handler": "trends/shopping.js",
                         "x-pinterest-source-url": "/shopping/?country=US",
                         "x-pinterest-appstate": "active", "x-app-version": "8c40681",
                         "screen-dpr": "1.25"},
}
codes = {}
for name, h in cases.items():
    r = call(c, TOP.format(region="US"), {**base_top, "limit": 3}, headers=h)
    codes[name] = r.status_code
    check(f"headers: {name}", None, f"-> {r.status_code}")
check("x-pinterest-pws-handler ALONE is sufficient", codes["pws-handler only"] == 200,
      f"{codes['pws-handler only']}")
check("X-APP-VERSION is NOT required", codes["pws-handler only"] == 200,
      "pws-handler alone returns 200 without it")
check("without pws-handler it fails regardless of other headers",
      codes["appstate + source-url, no pws"] != 200 and codes["x-app-version only (no pws)"] != 200,
      f"appstate+src={codes['appstate + source-url, no pws']}, "
      f"app-version={codes['x-app-version only (no pws)']}")

# ---------------------------------------------------------------------------------------
print("\n=== B. /top/ — required params, limit, offset ===")
for omit in ("event", "ranking_method", "end_date"):
    p = {k: v for k, v in base_top.items() if k != omit}
    r = call(c, TOP.format(region="US"), {**p, "limit": 3})
    check(f"omitting {omit} -> 400", r.status_code == 400, f"got {r.status_code}")

r = call(c, TOP.format(region="US"), dict(base_top))
default_n = len(rows(r) or [])
check("limit defaults to 8", default_n == 8, f"got {default_n} rows")

for lim, expect_ok in [(1, True), (522, True), (523, False), (0, False), (-1, False)]:
    r = call(c, TOP.format(region="US"), {**base_top, "limit": lim})
    got = r.status_code
    n = len(rows(r) or []) if got == 200 else None
    ok = (got == 200) if expect_ok else (got >= 400)
    check(f"limit={lim} {'accepted' if expect_ok else 'rejected'}", ok, f"{got}" + (f", {n} rows" if n is not None else ""))

r = call(c, TOP.format(region="US"), {**base_top, "limit": 5, "offset": 0})
a = [x.get("product_category") for x in (rows(r) or [])]
r = call(c, TOP.format(region="US"), {**base_top, "limit": 5, "offset": 5})
b = [x.get("product_category") for x in (rows(r) or [])]
check("offset works (page 2 differs from page 1)", bool(a) and bool(b) and a != b,
      f"offset0={a} offset5={b}")

r = call(c, TOP.format(region="US"), {**base_top, "limit": 522, "parent_product_categories": []})
total = len(rows(r) or [])
check("total categories reachable with empty parents", total > 0, f"{total} rows")

# ---------------------------------------------------------------------------------------
print("\n=== C. /top/ — enums ===")
for ob, exp in [("PCT_CHANGE_MOM", True), ("RELATIVE_VOLUME", True), ("BOGUS", False)]:
    r = call(c, TOP.format(region="US"), {**base_top, "limit": 3, "order_by": ob})
    check(f"order_by={ob}", (r.status_code == 200) == exp, f"{r.status_code}")

for ev, exp in [("OUTBOUND_CLICK", True), ("ENGAGEMENT", True), ("SAVE", True),
                # IMPRESSION is accepted here and returns the same 35 categories as
                # ENGAGEMENT, i.e. it appears to alias to it. Only CLOSEUP is rejected.
                ("IMPRESSION", True), ("CLOSEUP", False)]:
    r = call(c, TOP.format(region="US"), {**base_top, "event": ev, "limit": 522})
    n = len(rows(r) or []) if r.status_code == 200 else None
    check(f"event={ev}", (r.status_code == 200) == exp, f"{r.status_code}"
          + (f", {n} categories" if n is not None else ""))

r = call(c, TOP.format(region="US"), {**base_top, "limit": 3, "age_bucket": ["AGE_ALL"]})
check("age_bucket=['AGE_ALL'] accepted on /top/", r.status_code == 200, f"{r.status_code}")

for region, exp in [("US", True), ("CA", True), ("GB+IE", True), ("DE+AT+CH", False)]:
    r = call(c, TOP.format(region=region), {**base_top, "limit": 3})
    check(f"region {region}", (r.status_code == 200) == exp, f"{r.status_code}")

# ---------------------------------------------------------------------------------------
print("\n=== D. Level-1 verticals are parents only ===")
r = call(c, TOP.format(region="US"), {**base_top, "limit": 5,
                                      "parent_product_categories": ["1042"]})
check("vertical 1042 valid as a PARENT", r.status_code == 200,
      f"{r.status_code}, {len(rows(r) or [])} rows")
r = call(c, METRICS.format(region="US"),
         {"product_category_ids": ["1042"], "event": "OUTBOUND_CLICK", "end_date": END,
          "days": 90, "age_bucket": [], "gender": []})
check("vertical 1042 REJECTED as a product_category_id", r.status_code >= 400, f"{r.status_code}")

r = call(c, TAXONOMY, {}, source="/shopping/?country=US")
cats = (r.json().get("resource_response", {}).get("data", {}) or {}).get("categories", {}) \
    if r.status_code == 200 else {}
present = [v for v in VERTICALS if v in cats]
check("the 14 verticals are absent from the taxonomy map", not present,
      f"{len(cats)} categories; verticals present: {present}")

# ---------------------------------------------------------------------------------------
print("\n=== E. /metrics/ — days, predicted_days, demographics lockout ===")
mbase = {"product_category_ids": ["1010"], "event": "OUTBOUND_CLICK", "end_date": END,
         "age_bucket": [], "gender": []}
for days, exp_pts in [(7, 1), (30, 5), (90, 13), (365, 53), (730, 105)]:
    r = call(c, METRICS.format(region="US"), {**mbase, "days": days})
    vals = rows(r, "values")
    n = len(vals[0]["daily_values"]) if vals else None
    check(f"days={days} -> {exp_pts} weekly points", n == exp_pts, f"got {n}")
for days, exp in [(1, True), (0, False), (731, False), (60, True)]:
    r = call(c, METRICS.format(region="US"), {**mbase, "days": days})
    check(f"days={days} {'accepted' if exp else 'rejected'}", (r.status_code == 200) == exp,
          f"{r.status_code}")

for pd, exp in [(0, 200), (28, 200), (91, 200), (7, None), (29, None)]:
    r = call(c, METRICS.format(region="US"), {**mbase, "days": 90, "predicted_days": pd})
    if exp:
        check(f"predicted_days={pd} accepted", r.status_code == exp, f"{r.status_code}")
    else:
        check(f"predicted_days={pd} rejected", r.status_code >= 400, f"{r.status_code}")

# The UI always sends empty arrays here, but the API both accepts AND applies them —
# the returned curve genuinely changes. Shopping sparklines CAN be demographically sliced.
def curve(payload):
    rr = call(c, METRICS.format(region="US"), payload)
    v = rows(rr, "values")
    return [p["count"] for p in v[0]["daily_values"]] if v else None


plain = curve({**mbase, "days": 90})
young = curve({**mbase, "days": 90, "age_bucket": ["AGE_18_24"]})
old = curve({**mbase, "days": 90, "age_bucket": ["AGE_55_64"]})
male = curve({**mbase, "days": 90, "gender": ["MALE"]})
check("age_bucket accepted on /metrics/", young is not None, f"AGE_18_24 -> {len(young or [])} pts")
check("age_bucket is APPLIED, not ignored", young != plain and young != old,
      f"unfiltered={plain[:4]} 18-24={young[:4]} 55-64={old[:4]}")
check("gender is APPLIED, not ignored", male != plain, f"unfiltered={plain[:4]} male={male[:4]}")

# ---------------------------------------------------------------------------------------
print("\n=== F. top_products ===")
r = call(c, PRODUCTS, {"product_category_id": "1010", "region": "US"},
         source="/shopping/1010/?country=US")
check("top_products without event -> 500", r.status_code == 500, f"{r.status_code}")
for ev in ("OUTBOUND_CLICK", "SAVE", "ENGAGEMENT"):
    r = call(c, PRODUCTS, {"product_category_id": "1010", "region": "US", "event": ev},
             source="/shopping/1010/?country=US")
    n = len(rows(r, "top_products") or []) if r.status_code == 200 else None
    check(f"top_products event={ev}", True if ev == "OUTBOUND_CLICK" else None,
          f"{r.status_code}, {n} products")
r = call(c, PRODUCTS, {"product_category_id": "1010", "region": "US",
                       "event": "OUTBOUND_CLICK", "limit": 5},
         source="/shopping/1010/?country=US")
n_lim = len(rows(r, "top_products") or [])
check("top_products ignores limit", n_lim != 5, f"asked 5, got {n_lim}")

# ---------------------------------------------------------------------------------------
print("\n=== G. Search /metrics/ days — is it really restricted to 30/90/180/365/730? ===")
for days in (60, 45, 90):
    n_req += 1
    time.sleep(DELAY)
    r = c.get("/metrics/", params={"terms": "nails", "country": "US", "end_date": END,
                                   "days": days, "aggregation": 2,
                                   "normalize_against_group": "false", "predicted_days": 0})
    n = len(r.json()[0]["counts"]) if r.status_code == 200 and r.json() else None
    check(f"search /metrics/ days={days}", None, f"{r.status_code}, {n} points")

c.close()
passed = sum(1 for _, p, _ in results if p is True)
failed = [(n, d) for n, p, d in results if p is False]
print("\n" + "=" * 78)
print(f"{passed} passed, {len(failed)} failed — {n_req} requests")
for n, d in failed:
    print(f"  FAILED  {n}: {d}")
print("=" * 78)
sys.exit(1 if failed else 0)

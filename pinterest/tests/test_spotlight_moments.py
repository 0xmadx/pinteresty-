"""Live verification of the Spotlight (topics/featured) and Moments teardown.

Read-only. Some payloads are deliberately invalid to pin down the cardinality and enum rules.

    .venv/Scripts/python.exe pinterest/tests/test_spotlight_moments.py
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
results, n_req = [], 0

FEATURED = "/ads/v4/trends/topics/featured/{region}/{event}"
MOMENTS = "/ads/v4/trends/moment/available/{region}"
FASHION_TRIPLE = ["903733943146", "924581335376", "948967005229"]
BEAUTY = "935541271955"


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL' if passed is False else 'INFO'}] {name}"
          + (f" — {detail}" if detail else ""))


def call(c, inner, payload, source="/?country=US"):
    global n_req
    n_req += 1
    time.sleep(DELAY)
    body = {"options": {"url": inner, "data": payload}, "context": {}}
    return c.get("/resource/ApiResource/get/",
                 params={"source_url": source,
                         "data": json.dumps(body, separators=(",", ":"))},
                 headers={"x-pinterest-pws-handler": "trends/index.js"})


def data_of(r):
    if r.status_code != 200:
        return None
    return r.json().get("resource_response", {}).get("data")


c = httpx.Client(base_url=BASE, cookies=cookies, timeout=40.0, headers={
    "accept": "application/json, text/javascript, */*; q=0.01", "user-agent": UA,
    "x-requested-with": "XMLHttpRequest"})

# ---------------------------------------------------------------------------------------
print("\n=== A. Spotlight: region and event are both locked down ===")
for region, exp in [("US", True), ("CA", True), ("GB+IE", True), ("us", True),
                    ("DE", False), ("JP", False), ("GB", False)]:
    r = call(c, FEATURED.format(region=region, event="SAVE"),
             {"interests": [BEAUTY], "publish_state": "PUBLISHED"})
    check(f"region {region}", (r.status_code == 200) == exp, f"{r.status_code}")

for event, exp in [("SAVE", True), ("save", True), ("OUTBOUND_CLICK", False),
                   ("ENGAGEMENT", False), ("IMPRESSION", False)]:
    r = call(c, FEATURED.format(region="US", event=event),
             {"interests": [BEAUTY], "publish_state": "PUBLISHED"})
    check(f"event {event}", (r.status_code == 200) == exp, f"{r.status_code}")

for ps, exp in [("PUBLISHED", True), ("published", True), ("DRAFT", False), ("ALL", False)]:
    r = call(c, FEATURED.format(region="US", event="SAVE"),
             {"interests": [BEAUTY], "publish_state": ps})
    check(f"publish_state {ps}", (r.status_code == 200) == exp, f"{r.status_code}")

r = call(c, FEATURED.format(region="US", event="SAVE"), {"interests": [BEAUTY]})
check("publish_state may be omitted", r.status_code == 200, f"{r.status_code}")

# ---------------------------------------------------------------------------------------
print("\n=== B. Spotlight: the interests cardinality rule ===")
r = call(c, FEATURED.format(region="US", event="SAVE"), {"publish_state": "PUBLISHED"})
n_all = len(data_of(r) or []) if r.status_code == 200 else None
check("omitting interests = 'All'", r.status_code == 200, f"{r.status_code}, {n_all} topics")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": [BEAUTY], "publish_state": "PUBLISHED"})
n_one = len(data_of(r) or []) if r.status_code == 200 else None
check("one interest -> 5 topics", n_one == 5, f"{r.status_code}, {n_one} topics")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": BEAUTY, "publish_state": "PUBLISHED"})
check("bare string tolerated like a 1-element array", r.status_code == 200, f"{r.status_code}")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": [BEAUTY, "934876475639"], "publish_state": "PUBLISHED"})
check("TWO interests -> 400", r.status_code == 400, f"{r.status_code}")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": FASHION_TRIPLE, "publish_state": "PUBLISHED"})
n_tri = len(data_of(r) or []) if r.status_code == 200 else None
check("the Fashion TRIPLE is accepted", r.status_code == 200, f"{r.status_code}, {n_tri} topics")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": list(reversed(FASHION_TRIPLE)), "publish_state": "PUBLISHED"})
check("Fashion triple order does not matter", r.status_code == 200, f"{r.status_code}")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": [BEAUTY, "934876475639", "922134410098"], "publish_state": "PUBLISHED"})
check("any OTHER triple -> 400", r.status_code == 400, f"{r.status_code}")

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": FASHION_TRIPLE + [BEAUTY], "publish_state": "PUBLISHED"})
check("four interests -> 400", r.status_code == 400, f"{r.status_code}")

print("\n  the nine ids that exist on /search/ but not in the spotlight dropdown:")
for name, iid in [("Sport", "919812032692"), ("Finance", "913207199297"),
                  ("Vehicles", "918093243960"), ("Design", "902065567321"),
                  ("Men's Fashion", "924581335376"), ("unknown '123'", "123")]:
    r = call(c, FEATURED.format(region="US", event="SAVE"),
             {"interests": [iid], "publish_state": "PUBLISHED"})
    d = data_of(r)
    check(f"    {name}", None, f"{r.status_code}"
          + (f", {len(d)} topics" if isinstance(d, list) else ""))

r = call(c, FEATURED.format(region="US", event="SAVE"),
         {"interests": [BEAUTY], "publish_state": "PUBLISHED", "limit": 2, "offset": 3,
          "end_date": "2026-07-27", "age_bucket": ["AGE_18_24"], "junk_key": "x"})
n_ign = len(data_of(r) or []) if r.status_code == 200 else None
check("limit/offset/end_date/age_bucket are accepted and IGNORED", n_ign == 5,
      f"{r.status_code}, still {n_ign} topics")

# ---------------------------------------------------------------------------------------
print("\n=== C. Moments: region coverage is much wider than the spotlight ===")
moment_sets = {}
for region in ["US", "CA", "GB+IE", "DE", "DE+AT+CH", "FR", "MX+AR+CO+CL", "JP", "ZZ"]:
    r = call(c, MOMENTS.format(region=region), {})
    d = data_of(r)
    ms = (d or {}).get("moments") if isinstance(d, dict) else None
    moment_sets[region] = ms
    check(f"moments {region}", None, f"{r.status_code}"
          + (f", {len(ms)} moments" if ms is not None else ""))

check("moments is NOT limited to US/CA/GB+IE",
      moment_sets.get("DE") is not None and moment_sets.get("FR") is not None,
      "DE and FR both return data")
check("ZZ is rejected", moment_sets.get("ZZ") is None, "")
check("JP returns an empty list, not an error", moment_sets.get("JP") == [],
      f"{moment_sets.get('JP')}")
check("moment sets differ per region",
      moment_sets.get("US") != moment_sets.get("CA"),
      f"US-only: {sorted(set(moment_sets.get('US') or []) - set(moment_sets.get('CA') or []))}")
if moment_sets.get("CA"):
    check("CA carries Canada-specific moments",
          {"canada day", "superbowl"} & set(moment_sets["CA"]) != set(),
          f"{sorted(moment_sets['CA'])}")
if moment_sets.get("DE"):
    check("DE carries oktoberfest/karneval",
          {"oktoberfest", "karneval"} & set(moment_sets["DE"]) != set(),
          f"{sorted(moment_sets['DE'])}")
check("DE and DE+AT+CH hold the same moments",
      set(moment_sets.get("DE") or []) == set(moment_sets.get("DE+AT+CH") or []), "")
check("...but grouped regions come back alphabetised and singles do not",
      moment_sets.get("DE") != moment_sets.get("DE+AT+CH")
      and moment_sets.get("DE+AT+CH") == sorted(moment_sets.get("DE+AT+CH") or []),
      "order differs — zip the parallel arrays on index, never re-sort one alone")

r = call(c, MOMENTS.format(region="US"),
         {"end_date": "2026-01-01", "limit": 3, "phase": "approaching", "junk": 1})
d = data_of(r)
check("moments payload keys are ignored",
      isinstance(d, dict) and len(d.get("moments", [])) == len(moment_sets["US"]),
      f"still {len(d.get('moments', [])) if isinstance(d, dict) else None} moments")

d = data_of(call(c, MOMENTS.format(region="US"), {}))
check("phase_labels uses exactly approaching/cooldown/ended",
      set(d.get("phase_labels", [])) <= {"approaching", "cooldown", "ended"},
      f"{sorted(set(d.get('phase_labels', [])))}")

# ---------------------------------------------------------------------------------------
print("\n=== D. Do region-specific moments work as a /top_trends_filtered/ filter? ===")


def trends(country, moments=None, preset=4):
    global n_req
    n_req += 1
    time.sleep(DELAY)
    p = {"lookbackWindow": 2, "endDate": "2026-07-27", "country": country,
         "trendsPreset": preset}
    if moments:
        p["moments"] = moments
    return c.get("/top_trends_filtered/", params=p)


counts = {}
for country, moment in [("US", None), ("US", "halloween"), ("US", "christmas"),
                        ("US", "summer"), ("CA", "canada day"),
                        ("DE+AT+CH", "oktoberfest"), ("US", "oktoberfest"),
                        ("US", "not a real moment")]:
    r = trends(country, moment)
    vals = r.json().get("values", []) if r.status_code == 200 else None
    counts[(country, moment)] = (r.status_code, len(vals) if vals is not None else None)
    check(f"moments={moment!r} on country={country}", None,
          f"{r.status_code}" + (f", {len(vals)} rows"
                                f", e.g. {[v['term'] for v in vals[:3]]}" if vals else ", 0 rows"))

check("a moment from another region is REJECTED, not ignored",
      counts[("US", "oktoberfest")][0] == 400 and counts[("US", "not a real moment")][0] == 400,
      "moment/available is the authoritative per-region enum for the moments= filter")
check("TRAP: a moment filter can return FEWER than 50 rows",
      counts[("US", None)][1] == 50 and counts[("US", "christmas")][1] < 50,
      f"unfiltered=50, christmas={counts[('US', 'christmas')][1]}, "
      f"summer={counts[('US', 'summer')][1]}, "
      f"oktoberfest(DACH)={counts[('DE+AT+CH', 'oktoberfest')][1]}")
check("a valid in-region moment can still return zero rows off-season",
      counts[("CA", "canada day")] == (200, 0), "CA/canada day -> 200 with 0 rows")

c.close()
passed = sum(1 for _, p, _ in results if p is True)
failed = [(n, d) for n, p, d in results if p is False]
print("\n" + "=" * 78)
print(f"{passed} passed, {len(failed)} failed — {n_req} requests")
for n, d in failed:
    print(f"  FAILED  {n}: {d}")
print("=" * 78)
sys.exit(1 if failed else 0)

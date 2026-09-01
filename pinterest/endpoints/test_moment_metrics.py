"""moment_metrics: the guards fire before the wire, and the series comes back forward.

OFFLINE. `_api_resource` is stubbed, so nothing here touches Pinterest or the vault.

Two properties are worth pinning and neither is about the happy path:

**The wire returns this series NEWEST-FIRST.** Measured live 2026-09-01 on
`halloween`: `[0]` was 2026-11-23 and `[-1]` was 2025-08-25. Every other series in
this system is oldest-first, so a consumer looping forward reads every trend
backwards. The method reverses at the wire boundary; this asserts it stays
reversed. The fixture below is deliberately built DESCENDING, like the real wire.

**The guards must refuse before spending a request.** Every one of these is a
real 400/500 the apify wire reference measured, and the point of catching them
here is that a refusal costs nothing while a 400 costs a round trip and returns
None — which is indistinguishable from "no data" (N-02).

    .venv/Scripts/python.exe -m pinterest.endpoints.test_moment_metrics
"""
from pinterest.endpoints.api import PinterestTrendsAPI

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


# A descending series, exactly as the wire ships it: newest first. Three forecast
# points at the head (they are the FUTURE, so they sort first in a descending
# series) and three observed behind them.
WIRE = {
    "moments": [{
        "name": "halloween",
        "moment": {
            "daily_values": [
                # newest -> oldest, forecast first
                {"timestamp": 1795392000000, "normal_counts": 79,
                 "predicted_normalized_upper_bound_count": 84,
                 "predicted_normalized_lower_bound_count": 71},
                {"timestamp": 1794787200000, "normal_counts": 60,
                 "predicted_normalized_upper_bound_count": 66,
                 "predicted_normalized_lower_bound_count": 55},
                {"timestamp": 1794182400000, "normal_counts": 40,
                 "predicted_normalized_upper_bound_count": 45,
                 "predicted_normalized_lower_bound_count": 35},
                {"timestamp": 1761436800000, "normal_counts": 61,
                 "predicted_normalized_upper_bound_count": None,
                 "predicted_normalized_lower_bound_count": None},
                {"timestamp": 1760832000000, "normal_counts": 30,
                 "predicted_normalized_upper_bound_count": None,
                 "predicted_normalized_lower_bound_count": None},
                {"timestamp": 1760227200000, "normal_counts": 12,
                 "predicted_normalized_upper_bound_count": None,
                 "predicted_normalized_lower_bound_count": None},
            ],
            "peaks": [{"peak_timestamp_millis": "1792368000000",
                       "takeoff_timestamp_millis": "1785715200000",
                       "peak_length_in_days": 84}],
        },
        "moment_interests": {"941870572865": {}, "934876475639": {}},
    }]
}


def api_stub(payload=None):
    """A client that never touches the vault, the wire, or the series store."""
    api = PinterestTrendsAPI(cache=False, store=False, cookies={"_pinterest_sess": "x"})
    api._end_date = "2026-08-24"                       # skip latest_available_date()
    sent = {}

    def fake_resource(path, body=None, **kw):
        sent["path"] = path
        sent["body"] = body
        return WIRE if payload is None else payload

    api._api_resource = fake_resource
    api._store = lambda key, data: data                # do not write a cache row
    return api, sent


print()
api, sent = api_stub()
rows = api.moment_metrics("Halloween", aggregation="daily", lookback_days=365)
row = rows[0]
pts = row["points"]

# --- the trap: the wire is descending, we must hand back ascending ----------------
ts = [p["timestamp"] for p in pts]
check("the fixture really is descending, like the wire",
      [p["timestamp"] for p in WIRE["moments"][0]["moment"]["daily_values"]]
      == sorted(ts, reverse=True))
check("points come back ASCENDING (oldest first)", ts == sorted(ts), ts)
check("so points[0] is the OLDEST reading, not the far tail",
      pts[0]["timestamp"] == min(ts))

# --- forecast is tagged per point, never mixed into observed ----------------------
print()
check("every forecast point is flagged",
      all(p["is_forecast"] for p in pts if p["predicted_upper"] is not None))
check("every observed point is not",
      all(not p["is_forecast"] for p in pts if p["predicted_upper"] is None))
check("observed_points counts only measured", row["observed_points"] == 3)
check("forecast_points counts only predicted", row["forecast_points"] == 3)
check("and the two partition the series",
      row["observed_points"] + row["forecast_points"] == len(pts))

# --- the reading a naive consumer would get wrong ---------------------------------
print()
observed = [p for p in pts if not p["is_forecast"]]
forecast = [p for p in pts if p["is_forecast"]]
check("observed max is readable without touching forecast points",
      max(p["count"] for p in observed) == 61)
check("forecast max is separately readable",
      max(p["count"] for p in forecast) == 79)
check("basis says plainly that flagged points are predictions",
      "PREDICTED" in row["basis"], row["basis"])
check("series_order records the reversal, so a reader knows it happened",
      "ascending" in row["series_order"], row["series_order"])

# --- the slug the wire actually wants ---------------------------------------------
print()
api2, sent2 = api_stub()
api2.moment_metrics("Mother's Day")
check("moment names are slugged for the wire (apostrophes stripped)",
      sent2["body"]["moments"] == ["mothers day"], sent2["body"]["moments"])
check("a list of moments is accepted too",
      api_stub()[0].moment_metrics(["halloween", "christmas"]) is not None)

# --- refusals happen BEFORE the request, not after a 400 ---------------------------
print()
REFUSALS = [
    ("hourly aggregation (400 on the wire)", dict(aggregation="hourly")),
    ("lookback_days over 730", dict(lookback_days=1095)),
    ("predicted_days over 91", dict(predicted_days=180)),
    ("interest_limit over 24", dict(interest_limit=50)),
    ("monthly + 91 (does not divide evenly)",
     dict(aggregation="monthly", predicted_days=91)),
]
for label, kwargs in REFUSALS:
    a, s = api_stub()
    try:
        a.moment_metrics("halloween", **kwargs)
        check(f"refuses {label}", False, "no ValueError raised")
    except ValueError:
        check(f"refuses {label} without spending a request", "path" not in s)

# a valid monthly call must still be allowed through
a, s = api_stub()
a.moment_metrics("halloween", aggregation="monthly", predicted_days=0)
check("but monthly with predicted_days=0 is allowed", s.get("path", "").endswith("/US"))

# --- an empty wire response is not an exception -----------------------------------
print()
a, s = api_stub(payload=None)
a._api_resource = lambda *args, **kw: None
check("a failed fetch returns None, not a crash",
      a.moment_metrics("halloween") is None)

print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)

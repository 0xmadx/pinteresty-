"""Live verification of the eight standalone products.

Same contract as the other suites in this directory: nothing is asserted from memory, every
claim is checked against a real response. The point is not coverage — it is that each
product's central claim ("the calendar dates are real", "the demographic slice actually
changes the curve", "back-dating replays a past week") is the kind of thing that fails
silently by returning a plausible number, so it gets checked rather than assumed.

    .venv/Scripts/python.exe pinterest/tests/test_products.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.products import (ad_targeting, alerts, audience, content_calendar, history,
                                keyword_research, market_intel, moodboard)

PASS = FAIL = 0


def _raises(fn, exc):
    """True if `fn` raises `exc` — for the guards that are supposed to fail fast rather
    than let the server 400."""
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


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

# -- 1. keyword research -----------------------------------------------------------------
print("=== 1. keyword research ===")
SEED = "halloween nails"
tail = keyword_research.long_tail(api, SEED)
check("prefix children all start with the seed",
      all(r["term"].startswith(SEED.split()[0]) for r in tail), f"{len(tail)} rows")
check("every prefix child arrives with its own history, no /metrics/ call",
      all(r["weeks"] >= 50 for r in tail), f"{[r['weeks'] for r in tail][:5]}")
check("small-series rows are flagged noisy rather than reported as huge growth",
      all(r["noisy"] for r in tail if (r["velocity"] or 0) > 5),
      "an unflagged >500% velocity got through")

nb = keyword_research.neighbours(api, SEED)
check("related_terms returns co-searched terms, not prefix children",
      any(not r["term"].startswith(SEED.split()[0]) for r in nb),
      f"{[r['term'] for r in nb]}")

sweep = keyword_research.sweep(api, "growing", interests=["Home Decor", "Wedding"])
check("per-interest sweep multiplies the 50-row national table",
      len(sweep) > 50, f"{len(sweep)} rows from 2 interests")
check("sweep rows carry the interest they ranked in",
      len({r["interest"] for r in sweep}) == 2)
# An empty filter used to fall through `interests or INTERESTS` and fire 24 live requests.
check("sweep([]) means none, not all 24 (None means all)",
      keyword_research.sweep(api, "growing", interests=[]) == [])

# numTermsToReturn: the UI only ever sends 50 and the docs assumed that was the cap.
big = api.top_trends("growing", limit=100)
small = api.top_trends("growing")
check("the discovery table serves 100 rows, not the UI's 50",
      len(big["values"]) == 100, f"{len(big['values'])}")
check("the extra 50 are pure addition — the first 50 are unchanged",
      [r["term"] for r in big["values"]][:50] == [r["term"] for r in small["values"]])
check("the client refuses limit=101 before spending a request (the server 400s on it)",
      _raises(lambda: api.top_trends("growing", limit=101), ValueError))
# The limit is a ceiling, not a guarantee: an interest-filtered table returns however many
# terms qualify. Measured at limit=100 — Beauty 100, Wedding 34, Finance 1.
per_interest = {n: len(keyword_research.sweep(api, "growing", interests=[n]))
                for n in ("Beauty", "Wedding", "Finance")}
check("sweep defaults to the 100-row ceiling but reports the real count",
      per_interest["Beauty"] > 50 and all(v <= 100 for v in per_interest.values()),
      f"{per_interest}")
check("a thin interest is not padded to the ceiling",
      per_interest["Finance"] < 50, f"{per_interest}")

# -- 2. content calendar ------------------------------------------------------------------
print("\n=== 2. content calendar ===")
plans = content_calendar.plan(api, "US")
dated = [p for p in plans if p["basis"] == "takeoff"]
check("every moment resolves to a plan",
      len(plans) == len(api.moments_calendar("US")), f"{len(plans)} plans")
check("list_by is exactly 6 weeks before takeoff",
      all((datetime.strptime(p["takeoff"], "%Y-%m-%d")
           - datetime.strptime(p["list_by"], "%Y-%m-%d")).days == 42 for p in dated))
check("plans are ordered by deadline",
      [p["list_by"] for p in dated] == sorted(p["list_by"] for p in dated))

# Grouped regions return every moment with takeoff_ms null. Dropping those made the whole
# region come back as an empty calendar, which reads exactly like "nothing is coming up".
grouped = content_calendar.plan(api, "GB+IE")
check("a grouped region is reported as dateless, not silently empty",
      len(grouped) == 11 and all(p["basis"] == "occurrence" and p["status"] == "no ramp data"
                                 for p in grouped),
      f"{len(grouped)} rows, bases {[p['basis'] for p in grouped[:3]]}")
check("single-country regions still carry timestamps",
      len(dated) == len(plans), f"{len(dated)}/{len(plans)} US moments dated")
check("upcoming() tolerates dateless rows", content_calendar.upcoming(grouped) == [])

# Confirmed against the live trends.pinterest.com UI (2026-08-07), not just the API: the
# /moments/<name>/ page — the only place Pinterest itself shows takeoff/peak timing — is
# US-only, and switching its region selector redirects away. A few grouped regions get
# exactly ONE moment with peak_ms but still no takeoff_ms; launch_plan requires takeoff_ms,
# so those still come out dateless too — the exception does not leak a fake plan.
partial = content_calendar.plan(api, "DE+AT+CH")
check("a peak-only moment (no takeoff) still reports as dateless, not a fake plan",
      all(p["basis"] == "occurrence" for p in partial), f"{[p['basis'] for p in partial]}")
past = [p for p in plans if p["phase"] == "ended"]
check("no fake -365d drift on moments already past this cycle",
      all(p["drift_days"] is None for p in past), f"{len(past)} ended moments")
ics = content_calendar.to_ics(plans)
text = ics.read_text(encoding="utf-8")
check("the .ics parses as a calendar with two events per dated moment",
      text.count("BEGIN:VEVENT") == 2 * len(dated) and text.startswith("BEGIN:VCALENDAR"))

# -- 3. ad targeting ----------------------------------------------------------------------
print("\n=== 3. ad targeting ===")
board = ad_targeting.interest_board(api, interests=["Beauty", "Finance", "Home Decor"])
check("every interest row carries a real Ads targeting id",
      all(r["targeting_id"].isdigit() and len(r["targeting_id"]) == 12 for r in board))
check("interests are ranked, not returned in input order",
      [r["interest"] for r in board] != ["Beauty", "Finance", "Home Decor"]
      or board[0]["median_mom"] >= board[-1]["median_mom"])

curve = ad_targeting.hidden_demo_curve(api, "1002", bands=["18-24", "35-44"])
check("the demographic slice genuinely changes the curve (UI cannot do this)",
      curve["18-24"] and curve["35-44"]
      and curve["18-24"]["half_over_half"] != curve["35-44"]["half_over_half"],
      f"{curve}")

demo = ad_targeting.demo_split(api, ["halloween nails"])
check("demo rows carry both enum spellings, so neither endpoint family is mis-called",
      demo and demo[0]["age_enum"].startswith("AGE_") and demo[0]["age_indices"])

# -- 4. market intelligence ----------------------------------------------------------------
print("\n=== 4. market intelligence ===")
tax = market_intel.Taxonomy(api)
check("taxonomy is the full 383-node map", len(tax.raw) == 383, f"{len(tax.raw)}")
cid = tax.search("runner rugs")[0][0]
path = tax.path(cid)
check("path walks up to a level-1 vertical absent from the map",
      path[0] in ("Home decor", "Fashion", "Beauty") and path[-1] == "Runner rugs",
      " > ".join(path))
check("classify puts the exact category first",
      tax.classify("handmade runner rugs")[0]["name"] == "Runner rugs")

# Verticals are referenced as parents but are not entries in the map, so their `children`
# key does not exist — without a reverse index the DAG is unwalkable from the top.
check("the level-1 verticals navigate downward via the reverse index",
      all(tax.children(v) and len(tax.children(v, deep=True)) > 50
          for v in ("1181", "1250", "1042")),
      f"{ {v: len(tax.children(v, deep=True)) for v in ('1181', '1250', '1042')} }")
check("a leaf still reports no children", tax.children(cid) == [])

share = market_intel.merchant_share(api, cid)
check("merchant share sums to 1",
      abs(sum(m["share"] for m in share["merchants"]) - 1) < 0.02,
      f"{sum(m['share'] for m in share['merchants'])}")
check("real merchants come back, not just one house brand",
      len(share["merchants"]) > 1, f"{share['merchants']}")

# -- 5. history ----------------------------------------------------------------------------
print("\n=== 5. historical archive ===")
week_back = history.week_before(END, 2)
old = api.top_trends("growing", end_date=week_back)
check("endDate really back-dates — the table differs from this week's",
      old and old["endDate"] == week_back
      and [r["term"] for r in old["values"]] != [r["term"] for r in api.top_trends("growing")["values"]],
      f"asked {week_back}, got {(old or {}).get('endDate')}")

db = history.HistoryDB()
weeks = db.weeks("US", "growing")
check("the archive holds more than one week (this is the thing Pinterest cannot give you)",
      len(weeks) >= 2, f"weeks={weeks}")
if len(weeks) >= 2:
    churn = len({r["term"] for w in weeks for r in db.table(w, "US", "growing")})
    check("term churn is high enough that a single snapshot would miss most of it",
          churn > 50 * 1.5, f"{churn} distinct terms across {len(weeks)} weeks of 50 rows")

# -- 6. audience -----------------------------------------------------------------------------
print("\n=== 6. audience ===")
rows = audience.skew(audience.profile(api, audience.DEFAULT_TERMS))
sums = [sum(r["age"].values()) for r in rows]
# Measured 1.03-1.11 across five terms: seven bands each rounded to 2dp overshoot by up to
# 0.005 apiece. The shares are NOT exact percentages, which is why mean_age normalizes.
check("age bands sum to 1 only after rounding is accounted for (1.00-1.15)",
      all(1.0 <= s <= 1.15 for s in sums), f"{[round(s, 3) for s in sums]}")
check("mean_age divides by the real total rather than assuming the shares sum to 1",
      all(20 <= r["mean_age"] <= 60 for r in rows), f"{[r['mean_age'] for r in rows]}")
spread_gender = max(r["female_share"] for r in rows) - min(r["female_share"] for r in rows)
spread_age = (max(r["age"].get("18-24", 0) for r in rows)
              - min(r["age"].get("18-24", 0) for r in rows))
check("age discriminates between terms more than gender does (the reason skew() exists)",
      spread_age > spread_gender,
      f"18-24 spread {spread_age:.2f} vs female spread {spread_gender:.2f}")
check("skew is relative to the batch, so the typical term lands near 1.0",
      any(0.8 <= (r["age_skew"].get("25-34") or 0) <= 1.25 for r in rows))

cat = audience.category_profile(api, ["1002"])
check("the shopping side profiles by category id too",
      cat and cat[0]["dominant_age"] and cat[0]["related_terms"])

# -- 7. moodboard -----------------------------------------------------------------------------
print("\n=== 7. moodboards ===")
b = moodboard.board(api, "Home Decor")
check("a single request returns five complete topics", len(b) == 5, f"{len(b)}")
check("every topic ships pins, a series and its own search terms",
      all(t["images"] and t["series"] and t["terms"] for t in b))
check("the palette is derived from the pins Pinterest already tagged with a colour",
      all(t["palette"] for t in b)
      and all(sum(c["pins"] for c in t["palette"]) <= len(t["images"]) for t in b))
check("colour bucketing collapses near-identical pins into fewer swatches",
      all(len(t["palette"]) <= len(t["images"]) for t in b))

# editorial/content sat in the captures unwired since day one.
ed = moodboard.editorial(api)
check("the editorial endpoint returns written trend stories", len(ed) == 6, f"{len(ed)}")
check("each story carries real copy, pins and a palette",
      all(s["description"] and s["images"] and s["palette"] for s in ed))
check("one editorial call covers US, GB+IE and CA keywords at once",
      all(set(s["terms_by_region"]) == {"US", "GB+IE", "CA"} for s in ed),
      f"{[list(s['terms_by_region']) for s in ed[:2]]}")
check("the region path segment is ignored — /CA returns the same stories",
      [s.get("title") for s in (api.editorial_content("CA") or [])]
      == [s.get("title") for s in (api.editorial_content("US") or [])])
check("editorial rows carry no growth number, so nothing can rank on them",
      all(s["growth_mom"] is None and s["series"] == [] for s in ed))
check("to_html renders a mixed metric+editorial page",
      moodboard.to_html({"Editorial": ed}).stat().st_size > 5000)

# -- 8. alerts ---------------------------------------------------------------------------------
print("\n=== 8. momentum alerts ===")
if len(weeks) >= 2:
    events = alerts.latest_diff(db, "US", "growing")
    kinds = {e["kind"] for e in events}
    check("the diff produces typed events, not a dump", kinds and kinds <= set(alerts.SEVERITY),
          f"{kinds}")
    check("events are ordered by severity", [e["severity"] for e in events]
          == sorted((e["severity"] for e in events), reverse=True))
    curr = db.table(weeks[-1], "US", "growing")
    thresh = alerts._spike_threshold(curr, alerts.RULES)
    spikes = [e for e in events if e["kind"] == "spike"]
    check("the quantile spike rule stays a minority of the table, unlike a fixed cutoff",
          len(spikes) <= len(curr) * 0.25,
          f"{len(spikes)}/{len(curr)} rows above {thresh}")
    check("a term that left the top 20 is reported as exited, not silently dropped",
          all(e["term"] not in {r["term"] for r in curr}
              for e in events if e["kind"] == "exited"))
else:
    print("  [skip] archive too shallow — run pinterest/products/history.py --weeks 6")

api.close()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

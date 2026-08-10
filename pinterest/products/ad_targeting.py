"""3. Ad targeting research — the surface is Pinterest's own advertiser tooling.

`x-pinterest-pws-handler: trends/index.js` and the `/ads/v4/` path prefix are not
decoration: these are advertiser-scoped endpoints, so the vocabulary they take is the same
vocabulary the Ads campaign builder takes. The 24 `l1interests` ids ARE targeting ids, and
the age/gender enums ARE the targeting bands. That makes every row here directly
actionable: "target interest 935249274030, women 25-34" is a campaign setting, not an
analogy.

Two capabilities the Pinterest UI does not expose:

  * `hidden_demo_curve()` — the shopping category metrics endpoint accepts `age_bucket`
    and `gender` and genuinely APPLIES them (the curve changes), but the UI always sends
    empty arrays. There is no way to see this in the product. Measured on category 1002
    (Accent tables), 180 days to 2026-07-27: the category as a whole is shrinking
    (second half / first half = 0.94, peak back in February) while 18-24 is growing
    (1.14) and peaked in July. Same category, opposite conclusion, invisible in the UI.
  * `interest_board()` — the discovery table re-ranked per interest, aggregated into one
    momentum number per interest, which the UI never aggregates.

    .venv/Scripts/python.exe pinterest/products/ad_targeting.py
"""
import statistics
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import AGE, AGE_ADS, GENDER_ADS, INTERESTS, clamp_change

# Bands worth probing by default. All seven are accepted; each is a request, and the three
# below carry the overwhelming majority of Pinterest's shopping audience.
DEFAULT_BANDS = ["18-24", "25-34", "35-44"]


def interest_board(api, country="US", preset="growing", interests=None):
    """One momentum score per targetable interest. 24 requests, cached thereafter.

    Median rather than mean: `mom_change` carries a 10,000%+ sentinel (clamped to None
    here) and a long tail of small terms that took off from nothing, so a mean is decided
    by two rows out of fifty.
    """
    rows = []
    for name in (interests or list(INTERESTS)):
        table = api.top_trends(preset, country=country, interests=[INTERESTS[name]])
        values = (table or {}).get("values", [])
        moms = [m for m in (clamp_change((v.get("mom_change") or {}).get("value"))
                            for v in values) if m is not None]
        yoys = [y for y in (clamp_change((v.get("yoy_change") or {}).get("value"))
                            for v in values) if y is not None]
        seas = [v.get("seasonality_score") for v in values if v.get("seasonality_score")]
        rows.append({
            "interest": name,
            "targeting_id": INTERESTS[name],      # paste straight into the campaign builder
            "terms": len(values),
            "capped": sum(1 for v in values
                          if (v.get("mom_change") or {}).get("value") == 100.01),
            "median_mom": round(statistics.median(moms), 2) if moms else None,
            "median_yoy": round(statistics.median(yoys), 2) if yoys else None,
            "median_seasonality": round(statistics.median(seas), 3) if seas else None,
            "top_terms": [v["term"] for v in values[:5]],
        })
    return sorted(rows, key=lambda r: -(r["median_mom"] or 0))


def demo_split(api, terms, country="US"):
    """Who searches these terms. One request for the whole batch.

    Returned as targeting-ready rows: the winning age band and gender per term, with the
    Ads enum spelling alongside the human one, because the flat endpoints and the /ads/v4
    ones disagree on spelling (indices vs AGE_25_34) and mixing them up is a silent
    mis-target rather than an error.
    """
    if isinstance(terms, str):
        terms = [terms]
    data = api.demographics(terms, country=country) or {}
    out = []
    for term, dist in (data.get("term_distributions") or {}).items():
        age = dist.get("age_distribution") or {}
        gender = dist.get("gender_distribution") or {}
        best_age = max(age, key=age.get) if age else None
        best_gender = max(gender, key=gender.get) if gender else None
        out.append({
            "term": term,
            "age": best_age,
            "age_share": age.get(best_age),
            "age_enum": AGE_ADS.get(best_age),
            "age_indices": AGE.get(best_age),          # flat REST endpoints want these
            "gender": best_gender,
            "gender_share": gender.get(best_gender),
            "gender_enum": GENDER_ADS.get(best_gender),
            "age_distribution": age,
            "gender_distribution": gender,
        })
    return out


def hidden_demo_curve(api, category_id, country="US", bands=None, days=180,
                      event="OUTBOUND_CLICK"):
    """Shopping demand for one category, sliced by age band. One request per band.

    The UI has no control for this. The endpoint accepts the filter and the curve genuinely
    changes, so this answers "is this category growing because of 25-34s or in spite of
    them" — which decides the bid, and which no Pinterest advertiser can otherwise see.
    """
    out = {}
    base = api.category_metrics(category_id, country=country, event=event, days=days) or []
    out["all"] = _curve(base)
    for band in (bands or DEFAULT_BANDS):
        sliced = api.category_metrics(category_id, country=country, event=event, days=days,
                                      age=[AGE_ADS[band]]) or []
        out[band] = _curve(sliced)
    return out


def _curve(values):
    """`category_metrics` returns one entry per requested id.

    The points live under `daily_values` — the name is wrong, they are weekly buckets with
    a `date` each, the same cadence as the search /metrics/ series.
    """
    if not values:
        return None
    pts = values[0].get("daily_values") or []
    counts = [p.get("count") for p in pts if isinstance(p, dict) and p.get("count") is not None]
    if not counts:
        return None
    half = len(counts) // 2
    first, second = counts[:half], counts[half:]
    lift = (statistics.mean(second) / statistics.mean(first)
            if first and statistics.mean(first) else None)
    return {"n": len(counts), "last": counts[-1], "peak": max(counts),
            "peak_week": pts[counts.index(max(counts))].get("date"),
            "half_over_half": round(lift, 3) if lift else None}


def brief(api, country="US", preset="growing", top_interests=5):
    """A ready-to-read targeting brief: the fastest-moving interests, and for each one the
    audience actually searching its top terms."""
    board = interest_board(api, country, preset)[:top_interests]
    for row in board:
        row["audience"] = demo_split(api, row["top_terms"][:5], country)
    return board


def report(country="US"):
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}  |  region {country}\n")
        board = interest_board(api, country)
        print(f"{'interest':20} {'targeting id':14} {'MoM':>7} {'YoY':>7} {'seas':>6} "
              f"{'cap':>4}")
        for r in board:
            mom = f"{r['median_mom']:.2f}" if r["median_mom"] is not None else "   n/a"
            yoy = f"{r['median_yoy']:.2f}" if r["median_yoy"] is not None else "   n/a"
            print(f"{r['interest']:20} {r['targeting_id']:14} {mom:>7} {yoy:>7} "
                  f"{r['median_seasonality'] or 0:>6.3f} {r['capped']:>4}")

        top = board[0]
        print(f"\n=== audience for the leader: {top['interest']} ===")
        for a in demo_split(api, top["top_terms"], country):
            print(f"  {a['term']:34} {a['age']:>6} ({a['age_share']:.0%}) "
                  f"{a['gender']:>11} ({a['gender_share']:.0%})  "
                  f"-> {a['age_enum']}, {a['gender_enum']}")
        return board


if __name__ == "__main__":
    report(sys.argv[1] if len(sys.argv) > 1 else "US")

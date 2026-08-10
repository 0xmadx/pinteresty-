"""6. Audience research — who searches for a thing, by age and gender.

`/demographics/` takes a batch of terms in one request and returns two distributions per
term. The shopping side has its own version keyed by category id. That is the whole
endpoint; everything below is about making it readable.

The shares are rounded to two decimals server-side, so seven age bands sum to between 1.00
and 1.15 (measured 1.03-1.11 across five terms) rather than exactly 1. They are therefore
not usable as exact percentages — `mean_age` divides by the observed total instead of
assuming 1.0, and anything comparing across terms should go through `skew()`.

The number that matters is not the raw share, it is the SKEW. Pinterest's audience is
roughly 90% female across the board, so "91% female" says nothing — every term says that.
`skew()` divides each term's distribution by the baseline built from the same batch, so
what surfaces is the term that is unusually male, or unusually 55+, relative to its peers.
Measured on a Beauty batch: female share ranged 88-95% (nearly flat), while the 18-24
share ranged 24-68% — a 2.8x spread. Age is where the signal is.

    .venv/Scripts/python.exe pinterest/products/audience.py "halloween nails" "grill recipes"
"""
import statistics
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI

AGE_BANDS = ["18-24", "25-34", "35-44", "45-49", "50-54", "55-64", "65+"]
# Midpoints for a single-number age summary. 65+ is open-ended; 70 is the conventional
# stand-in and only ever shifts the mean by a fraction of a year at these shares.
AGE_MIDPOINT = {"18-24": 21, "25-34": 29.5, "35-44": 39.5, "45-49": 47,
                "50-54": 52, "55-64": 59.5, "65+": 70}


def profile(api, terms, country="US"):
    """One row per term: distributions, the dominant band, and a mean age.

    Mean age is the compact comparator — two terms can share a dominant band and still sit
    six years apart once the tails are counted.
    """
    if isinstance(terms, str):
        terms = [terms]
    data = api.demographics(terms, country=country) or {}
    out = []
    for term, dist in (data.get("term_distributions") or {}).items():
        age = dist.get("age_distribution") or {}
        gender = dist.get("gender_distribution") or {}
        total = sum(age.values()) or 1
        out.append({
            "term": term,
            "age": age,
            "gender": gender,
            "dominant_age": max(age, key=age.get) if age else None,
            "mean_age": round(sum(AGE_MIDPOINT[b] * s for b, s in age.items()
                                  if b in AGE_MIDPOINT) / total, 1) if age else None,
            "female_share": gender.get("female"),
            "male_share": gender.get("male"),
            "under_35": round(age.get("18-24", 0) + age.get("25-34", 0), 3),
            "over_55": round(age.get("55-64", 0) + age.get("65+", 0), 3),
        })
    return out


def baseline(rows):
    """Median share per band across the batch. Median, not mean, so one wildly skewed term
    does not become the yardstick everything else is measured against."""
    if not rows:
        return {}, {}
    ages = {b: statistics.median([r["age"].get(b, 0) for r in rows]) for b in AGE_BANDS}
    genders = {g: statistics.median([r["gender"].get(g, 0) for r in rows])
               for g in ("male", "female", "unspecified")}
    return ages, genders


def skew(rows, against=None):
    """Each term's shares as a multiple of the baseline.

    1.0 is "exactly typical". 2.0 on 18-24 means twice the share of that band the median
    term in this batch has — which is the only reading that survives Pinterest's very
    lopsided overall audience.
    """
    base_age, base_gender = against or baseline(rows)
    for r in rows:
        r["age_skew"] = {b: round(r["age"].get(b, 0) / base_age[b], 2)
                         for b in AGE_BANDS if base_age.get(b)}
        r["gender_skew"] = {g: round(r["gender"].get(g, 0) / base_gender[g], 2)
                            for g in base_gender if base_gender.get(g)}
        r["most_distinctive"] = (max(r["age_skew"], key=r["age_skew"].get)
                                 if r["age_skew"] else None)
    return rows


def category_profile(api, category_ids, country="US", event="OUTBOUND_CLICK"):
    """The shopping-side equivalent, keyed by category id.

    Same two distributions, plus the category's own related search terms — so this answers
    "who buys in this category AND what do they call it", in one request. One invalid or
    level-1 id fails the whole call, so ids are validated by the client before it goes out.
    """
    data = api.category_demographics(category_ids, country=country, event=event) or {}
    out = []
    for cid, block in (data.get("product_category_distributions") or {}).items():
        demo = (block.get("demographics") or [{}])[0]
        out.append({
            "category_id": cid,
            "age": demo.get("age_distribution") or {},
            "gender": demo.get("gender_distribution") or {},
            "related_terms": (block.get("related_search_trends") or [])[:10],
        })
    for r in out:
        age = r["age"]
        r["dominant_age"] = max(age, key=age.get) if age else None
        r["female_share"] = (r["gender"] or {}).get("female")
    return out


DEFAULT_TERMS = ["halloween nails", "grill recipes", "retirement party", "nursery decor",
                 "deltarune"]


def report(terms=None, country="US"):
    terms = terms or DEFAULT_TERMS
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}\n")
        rows = skew(profile(api, terms, country))
        base_age, base_gender = baseline(rows)
        print(f"baseline (median of this batch): "
              f"{', '.join(f'{b} {s:.0%}' for b, s in base_age.items() if s)}  |  "
              f"female {base_gender.get('female', 0):.0%}\n")
        print(f"{'term':34} {'mean age':>8} {'<35':>6} {'55+':>6} {'female':>7}  most distinctive")
        for r in rows:
            print(f"{r['term'][:34]:34} {r['mean_age'] or 0:>8.1f} {r['under_35']:>6.0%} "
                  f"{r['over_55']:>6.0%} {r['female_share'] or 0:>7.0%}  "
                  f"{r['most_distinctive']} ({r['age_skew'].get(r['most_distinctive'], 0):.1f}x)")
        return rows


if __name__ == "__main__":
    report(sys.argv[1:] or None)

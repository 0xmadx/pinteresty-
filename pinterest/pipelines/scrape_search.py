"""Keyword search engine pipeline: discovery -> curves -> demographics -> expansion.

Ported onto the cache-first PinterestTrendsAPI. Dates come from /latest_available_date/
rather than being hardcoded, and the raw dump is stripped of `client_context`.
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI


def run(preset="growing", n_terms=5, country="US"):
    with PinterestTrendsAPI() as api:
        end_date = api.latest_available_date()
        print(f"Data week: {end_date}")

        print(f"\n[1] Discovery — preset '{preset}'...")
        table = api.top_trends(preset, country=country)
        rows = table["values"]
        top = [r["term"] for r in rows[:n_terms]]
        print(f"    {len(rows)} rows; top {n_terms}: {top}")

        print("\n[2] Curves — all terms in ONE batched call...")
        all_terms = [r["term"] for r in rows]
        metrics = api.metrics(all_terms, days=90)
        print(f"    {len(metrics)} series")

        primary = top[0]
        print(f"\n[3] Demographics for '{primary}'...")
        demo = api.demographics(primary)
        dist = demo["term_distributions"][primary]
        print(f"    {dist['gender_distribution']}")

        print(f"\n[4] Expansion on '{primary}'...")
        variants = api.prefix_match(primary) or []
        related = api.related_terms(primary) or []
        print(f"    prefix:  {[v['term'] for v in variants][:5]}")
        print(f"    related: {[v['term'] for v in related]}")

        out = {
            "metadata": {"preset": preset, "end_date": end_date, "country": country,
                         "top_terms": top},
            "discovery": rows,
            "metrics": metrics,
            "demographics": demo,
            "expansion_prefix": variants,
            "expansion_related": related,
        }
        path = Path(__file__).resolve().parents[1] / "data" / "search_pipeline_output.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nSaved {path}")
        return out


if __name__ == "__main__":
    run()

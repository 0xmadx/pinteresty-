"""Spotlight pipeline: editorial macro trends across every dropdown interest.

Ported onto PinterestTrendsAPI. Sweeps all 15 dropdown options rather than one hardcoded id;
the API class enforces the one-id-or-Fashion-triple rule so nothing 400s or 500s.
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import SPOTLIGHT_INTERESTS


def run(country="US"):
    out = {}
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}")
        print(f"\nSweeping {len(SPOTLIGHT_INTERESTS)} spotlight options...\n")
        for label, ids in SPOTLIGHT_INTERESTS.items():
            topics = api.featured_topics(ids, country=country) or []
            out[label] = topics
            print(f"  {label:18} {len(topics)} topics")
            for t in topics[:2]:
                print(f"     {t['name'][:44]:46} +{t['pct_growth_mom']} MoM | "
                      f"{', '.join(t['related_search_trends'][:3])}")

    path = Path(__file__).resolve().parents[1] / "data" / "spotlight_pipeline_output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved {path}")
    return out


if __name__ == "__main__":
    run()

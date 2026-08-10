"""Shopping pipeline: taxonomy -> full category ranking -> curves -> Etsy competitor scan.

Ported onto PinterestTrendsAPI. Fetches the ENTIRE ranking in one call (44 categories on
OUTBOUND_CLICK) instead of the UI's 20, and reports the click/save split per category.
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI


def run(country="US", event="OUTBOUND_CLICK", scan_etsy=5):
    with PinterestTrendsAPI() as api:
        end_date = api.latest_available_date()
        print(f"Data week: {end_date}")

        print("\n[1] Taxonomy...")
        cats = api.product_categories(country)
        name = lambda cid: cats.get(str(cid), {}).get("friendly_name", f"?{cid}")
        print(f"    {len(cats)} categories")

        print(f"\n[2] Full ranking on {event} (one call, not the UI's 20)...")
        top = api.top_categories(country=country, event=event)
        print(f"    {len(top)} categories ranked")
        for c in top[:8]:
            s = c["summary"]
            print(f"      {name(c['product_category'])[:30]:32} "
                  f"clicks {s['outbound_clicks']['percent_growth']:+.2f}  "
                  f"saves {s['saves']['percent_growth']:+.2f}")

        ids = [c["product_category"] for c in top[:20]]
        print(f"\n[3] Curves for the top {len(ids)}...")
        metrics = api.category_metrics(ids, country=country, event=event, days=180)
        print(f"    {len(metrics)} series")

        print(f"\n[4] Etsy competitor scan over the top {scan_etsy}...")
        etsy = {}
        for c in top[:scan_etsy]:
            cid = c["product_category"]
            hits = api.etsy_competitors(cid, country=country)
            etsy[cid] = hits
            print(f"      {name(cid)[:30]:32} {len(hits)} Etsy listings")
            for p in hits[:2]:
                print(f"         {p['title'][:78]}")

        out = {
            "metadata": {"end_date": end_date, "country": country, "event": event,
                         "total_categories": len(cats), "ranked": len(top)},
            "ranking": top,
            "metrics": metrics,
            "etsy_competitors": etsy,
        }
        path = Path(__file__).resolve().parents[1] / "data" / "shopping_pipeline_output.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nSaved {path}")
        return out


if __name__ == "__main__":
    run()

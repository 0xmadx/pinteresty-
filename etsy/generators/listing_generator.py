import argparse
import json
import os
from typing import List, Dict
import statistics
from datetime import datetime, timezone

from etsy.api.private.api import EtsyPrivateAPI, edge_term, parse_results_data
from etsy.api.public.api import EtsyPublicAPI
from etsy.analytics.tag_mining import mine_consensus


def _utcnow():
    return datetime.now(timezone.utc).isoformat()

class ListingGenerator:
    def __init__(self):
        self.private_api = EtsyPrivateAPI()
        self.public_api = EtsyPublicAPI()
        
    def analyze_gap(self, seed: str) -> dict:
        """Analyzes the master payload to find the SERP Gap."""
        print(f"[*] Fetching Master Payload for '{seed}'...")
        data = self.private_api.get_results_data(seed)
        if not data:
            print("[-] Failed to fetch master payload.")
            return None
            
        # parse_results_data reads the real snake_case fields and normalises the cards
        # (string review counts -> int, nested price -> float). Reading the camelCase
        # spelling returned zero listings and a volume of 0 on every run.
        parsed = parse_results_data(data)
        listings = parsed["listings"][:10]

        # 1. Supply and Demand
        volume = parsed["volume"] or 0
        supply = parsed["supply"] or 0

        # 2. SERP Strength (Median Reviews of top 10)
        reviews = []
        exact_matches = 0

        for item in listings:
            rev = item.get("review_count")
            reviews.append(rev if rev is not None else 0)
            
            # 3. Gap Detection (Exact phrase match in title)
            title = item.get("title", "").lower()
            if seed.lower() in title:
                exact_matches += 1
                
        median_reviews = statistics.median(reviews) if reviews else 0
        
        # Scoring
        gap_score = "GREEN" if exact_matches <= 2 else "YELLOW" if exact_matches <= 6 else "KILL"
        serp_score = "GREEN" if median_reviews < 200 else "YELLOW" if median_reviews < 1000 else "KILL"
        
        print("\n=== SERP GAP ANALYSIS ===")
        print(f"Volume: {volume} | Supply: {supply}")
        print(f"Exact Matches in Top 10 Titles: {exact_matches}/10 [{gap_score}]")
        print(f"Top 10 Median Reviews: {median_reviews} [{serp_score}]")
        
        return {
            "volume": volume,
            "supply": supply,
            "exact_matches": exact_matches,
            "median_reviews": median_reviews,
            "gap_score": gap_score,
            "serp_score": serp_score,
            "top_listings": listings
        }

    def fetch_variants(self, seed: str) -> List[Dict]:
        """Fetches the 180 long-tail variants to build the title and tags."""
        print(f"\n[*] Fetching LLM Edge Variants for '{seed}'...")
        results = self.private_api.get_similar_keywords(seed)
        if not results:
            return []
            
        variants = []
        for r in results:
            # We want terms that are different from the seed but relevant
            term = (edge_term(r) or "").lower()
            if term != seed.lower():
                variants.append({
                    "term": term,
                    "volume": r.get("search_volume", r.get("searchVolume", 0))
                })
                
        # Sort by volume descending
        variants.sort(key=lambda x: x["volume"], reverse=True)
        return variants
        
    def _fetch_consensus_from_listings(self, listings: List[Dict], title: str) -> dict:
        print(f"\n[*] Extracting Public Listing Data for {title}...")
        # B-02: keep each listing's tags WITH its age/review evidence, instead of pooling
        # all tags into one flat list. Pooling gave a 4,000-review veteran the same vote
        # as a six-month-old shop that outranks it — which copies the symptom of ranking
        # (tenure) rather than the cause (tags). mine_consensus weights the vote by how
        # much the ranking was earned.
        mined = []
        all_breadcrumbs = []

        # Scrape top 5 competitors to save time
        count = 0
        for listing in listings:
            if count >= 5:
                break

            # Private API listings use 'id', Public API cards use 'listing_id'
            listing_id = listing.get("id") or listing.get("listing_id")
            if not listing_id:
                continue

            data = self.public_api.get_listing_data(listing_id)
            if data:
                mined.append({
                    "tags": data.get("tags", []),
                    # Public cards: review_count + shop_years_on_etsy. Private cards:
                    # numberOfReviews, no age. Pass whatever exists; earned_weight uses
                    # the axes it has and stays neutral on the ones it doesn't.
                    "review_count": listing.get("review_count",
                                                listing.get("numberOfReviews")),
                    "shop_years": listing.get("shop_years_on_etsy"),
                })
                bc = data.get("breadcrumb", [])
                if bc:
                    all_breadcrumbs.append(" > ".join(bc))
                count += 1

        consensus = mine_consensus(mined, limit=10, min_listings=2)
        if consensus["all_confounded"] and consensus["consensus_tags"]:
            print(f"    [!] Every competitor sampled is established (old or heavily "
                  f"reviewed). These tags may reflect tenure, not SEO — treat as a "
                  f"weaker signal.")

        from collections import Counter
        bc_counts = Counter(all_breadcrumbs)
        consensus_category = bc_counts.most_common(1)[0][0] if bc_counts else "Unknown Category"

        return {
            "consensus_tags": consensus["consensus_tags"],
            "consensus_category": consensus_category,
            "tag_support": consensus["support"],
            "all_confounded": consensus["all_confounded"],
            "all_tags": [t for m in mined for t in m["tags"]],
        }

    def fetch_evergreen_consensus(self, top_listings: List[Dict]) -> dict:
        """Hits the Public API for the top RELEVANT competitors to extract their tags."""
        return self._fetch_consensus_from_listings(top_listings, "Evergreen (Most Relevant)")
        
    def fetch_trending_consensus(self, seed: str) -> dict:
        """Hits the Public API sorted by NEWEST to extract trending tags."""
        print(f"\n[*] Fetching Trending Competitors for '{seed}' (Sort by Newest)...")
        data = self.public_api.get_public_search(seed, filters={"order": "date_desc"})
        if not data or not data.get("cards"):
            return {"consensus_tags": [], "consensus_category": "Unknown", "all_tags": []}
            
        trending_listings = data["cards"]
        return self._fetch_consensus_from_listings(trending_listings, "Trending (Newest)")
        
    def fetch_top_rated_consensus(self, seed: str) -> dict:
        """Hits the Public API sorted by HIGHEST REVIEWS to extract top-rated tags."""
        print(f"\n[*] Fetching Top-Rated Competitors for '{seed}' (Sort by Highest Reviews)...")
        data = self.public_api.get_public_search(seed, filters={"order": "highest_reviews"})
        if not data or not data.get("cards"):
            return {"consensus_tags": [], "consensus_category": "Unknown", "all_tags": []}
            
        top_rated_listings = data["cards"]
        return self._fetch_consensus_from_listings(top_rated_listings, "Top Rated (Highest Reviews)")
        
    def generate_listing(self, seed: str, variants: List[Dict], evergreen: dict, trending: dict, top_rated: dict, gap: dict = None):
        """Generates the Listing Brief based on Claude's formula, blending Evergreen, Trending, and Top Rated."""
        print("\n=== CLAUDE'S LISTING BRIEF ===")
        
        # --- TITLE GENERATION ---
        title_segments = [seed.title()]
        used_terms = set([seed.lower()])
        
        for v in variants:
            t = v["term"].title()
            if t.lower() not in used_terms and len(" , ".join(title_segments) + " , " + t) <= 140:
                title_segments.append(t)
                used_terms.add(t.lower())
            if len(title_segments) >= 5:
                break
                
        final_title = " , ".join(title_segments)
        print("\n[TITLE] (Max 140 chars):")
        print(final_title)
        
        # --- TAGS GENERATION ---
        print("\n[TAGS] (13 Slots, Max 20 chars per tag):")
        tags = []
        
        # Core Target (Slot 1)
        tags.append(seed[:20].lower())
        
        # Evergreen Slots (Slots 2-4)
        for tag in evergreen.get("consensus_tags", []):
            t = tag[:20].lower()
            if t not in tags and len(tags) < 4:
                tags.append(t)
                
        # Trending Slots (Slots 5-7)
        for tag in trending.get("consensus_tags", []):
            t = tag[:20].lower()
            if t not in tags and len(tags) < 7:
                tags.append(t)
                
        # Top Rated Slots (Slots 8-10)
        for tag in top_rated.get("consensus_tags", []):
            t = tag[:20].lower()
            if t not in tags and len(tags) < 10:
                tags.append(t)
                
        # Occasion & Differentiator Slots (Slots 11-13)
        occasion_words = ["gift", "present", "day", "anniversary", "birthday", "mom", "dad", "wedding", "halloween", "christmas"]
        for v in variants:
            if len(tags) >= 13:
                break
            t = v["term"]
            if any(w in t.lower() for w in occasion_words) and t[:20].lower() not in tags:
                tags.append(t[:20].lower())
                
        # Fill any remaining slots with long-tail variants
        v_idx = 0
        while len(tags) < 13 and v_idx < len(variants):
            t = variants[v_idx]["term"][:20].lower()
            if t not in tags:
                tags.append(t)
            v_idx += 1
                
        for i, tag in enumerate(tags):
            print(f"{i+1}. {tag}")
            
        # --- CATEGORY ---
        print("\n[CATEGORY PLACEMENT]:")
        category = evergreen.get("consensus_category", "Unknown")
        print(category)
        
        # --- SAVE OUTPUT ---
        output_file = f"etsy/data/outputs/{seed.replace(' ', '_')}.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("=== CLAUDE'S LISTING BRIEF ===\n\n")
            f.write(f"[CATEGORY PLACEMENT]\n{category}\n\n")
            f.write(f"[TITLE]\n{final_title}\n\n")
            f.write("[TAGS]\n")
            for i, tag in enumerate(tags):
                f.write(f"{i+1}. {tag}\n")
            f.write(f"\n[DESCRIPTION]\n1. Snippet: ...\n2. Connection: ...\n3. Specs: ...\n4. Long-tails: {', '.join([t['term'] for t in variants[:3]])}\n")
            
        print(f"\n[+] Saved listing brief to: {output_file}")

        # --- PREDICTION SNAPSHOT (M-3) ---
        # The launch itself happens outside this system: the operator lists the product
        # on Etsy and only then does a listing_id exist. But the *prediction* exists
        # now, and after the fact it is unrecoverable — volume, supply and the SERP
        # readings all move. So it is written beside the brief, and
        # `python -m etsy.analytics.launch` picks it up once there is an id to attach.
        prediction = {
            "term_id": seed,
            "generated_at": _utcnow(),
            "volume": (gap or {}).get("volume"),
            "supply": (gap or {}).get("supply"),
            "exact_matches": (gap or {}).get("exact_matches"),
            "median_reviews": (gap or {}).get("median_reviews"),
            "gap_score": (gap or {}).get("gap_score"),
            "serp_score": (gap or {}).get("serp_score"),
            "title": final_title,
            "tags": tags,
        }
        prediction_file = f"etsy/data/outputs/{seed.replace(' ', '_')}.prediction.json"
        with open(prediction_file, "w", encoding="utf-8") as f:
            json.dump(prediction, f, indent=2)
        print(f"[+] Saved prediction snapshot to: {prediction_file}")
        print(f"    After you list it, record the launch:\n"
              f"      python -m etsy.analytics.launch --seed \"{seed}\" --listing-id <ID>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=str, required=True, help="The seed keyword to generate a listing for")
    args = parser.parse_args()

    # No single run() method here — the stage is the whole six-call sequence, which is
    # what the operator actually invokes.
    from core import runlog
    from core.runlog import stage

    with stage("listing_generator", seed=args.seed):
        gen = ListingGenerator()
        gap = gen.analyze_gap(args.seed)
        if gap:
            variants = gen.fetch_variants(args.seed)
            evergreen = gen.fetch_evergreen_consensus(gap.get("top_listings", []))
            trending = gen.fetch_trending_consensus(args.seed)
            top_rated = gen.fetch_top_rated_consensus(args.seed)
            gen.generate_listing(args.seed, variants, evergreen, trending, top_rated, gap=gap)
            runlog.count(rows_out=1)
        else:
            # A seed with no gap is a legitimate answer, but it produces no listing —
            # recorded so a run that generated nothing is distinguishable from one that
            # never got that far.
            runlog.count(rows_out=0)
            print("[-] No gap found for this seed — no listing generated.")

import json
import os
import time
from collections import deque
from etsy.api.private.api import EtsyPrivateAPI
from etsy.analytics.derivations import parse_price
from etsy.analytics.profit import DIGITAL, verdict
from etsy.analytics.scoring import (PoolTooSmall, can_discriminate, score_pool,
                                    shortlist)
from core.runlog import logged_stage

# What the operator would actually make if they entered this niche. Profit cannot be
# computed without it — a keyword has no COGS or build time, a *product* does. The
# default is a digital download: no unit cost, no shipping, no labour, so its economics
# follow from the measured price alone and need no guesses from the operator.
DEFAULT_PROFILE = {"product_type": DIGITAL}


class MasterNicheFinder:
    def __init__(self, seed_keyword, max_depth=2, max_nodes=50, product_profile=None):
        """
        The Hyper-Optimized Batch Engine.
        Crawls sub-keywords deeply, batches them to the comparison endpoint for speed,
        and only uses the deep-dive endpoint on the absolute winners.

        `product_profile` describes the product the operator would list, and is what
        makes the STEP 5 profit gate possible. Accepts any keyword of `profit.verdict()`
        except `price` (measured per niche): `product_type`, `cogs`, `shipping_cost`,
        `shipping_charged`, `labor_minutes`, `demand_units_per_week`, `offsite_ads`.
        """
        self.seed = seed_keyword
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.profile = dict(product_profile or DEFAULT_PROFILE)
        self.api = EtsyPrivateAPI()

    @logged_stage("niche_finder")
    def run(self):
        print(f"\n[MASTER ENGINE] Initializing Hyper-Optimized Spider for seed: '{self.seed}'")
        print(f"[MASTER ENGINE] Max Depth: {self.max_depth} | Max Nodes: {self.max_nodes}")
        
        # STEP 1: DEEP RECURSIVE CRAWL (BFS)
        print(f"\n  [1] Executing Deep Crawl...")
        keywords_to_analyze = set([self.seed])
        queue = deque([(self.seed, 0)])
        
        while queue and len(keywords_to_analyze) < self.max_nodes:
            current_keyword, current_depth = queue.popleft()
            
            print(f"      🕸️ [Depth {current_depth}] Mapping node '{current_keyword}'...")
            
            if current_depth < self.max_depth:
                edges = self.api.get_similar_keywords(current_keyword, iterations=2)
                if edges:
                    for e in edges:
                        term = e.get("searchTerm")
                        if term and term not in keywords_to_analyze:
                            keywords_to_analyze.add(term)
                            queue.append((term, current_depth + 1))
                            if len(keywords_to_analyze) >= self.max_nodes:
                                break
                                
        kw_list = list(keywords_to_analyze)
        print(f"\n      [+] Crawl Complete! Discovered {len(kw_list)} unique micro-niches.")
        
        # STEP 2: BATCH METRIC EXTRACTION (The Optimization)
        print(f"\n  [2] Fast-Extracting Metrics via Batched Comparison Payloads...")
        scored_niches = []
        
        # Split into chunks of 3 for the chart-series-data endpoint
        chunks = [kw_list[i:i + 3] for i in range(0, len(kw_list), 3)]
        
        for idx, chunk in enumerate(chunks):
            print(f"      -> Batch processing chunk {idx+1}/{len(chunks)}: {chunk}")
            time.sleep(0.5) # Be polite
            
            chart = self.api.get_chart_series(chunk, days=365)
            if chart and "termSummaries" in chart:
                for s in chart["termSummaries"]:
                    term = s.get("searchTerm")
                    vol = s.get("searchVolume", 0)
                    listings = s.get("avgTotalListings", 0)
                    
                    # Base Mathematical Scoring
                    opportunity_score = round((vol / listings) * 1000, 2) if listings > 0 else 0
                    
                    scored_niches.append({
                        "keyword": term,
                        "volume": vol,
                        "competition": listings,
                        "base_opportunity_score": opportunity_score
                    })
                    
        # STEP 3: SHORTLIST FOR THE DEEP DIVE — a filter, not a ranking (N-01)
        #
        # Only demand and supply exist at this stage, and they cannot rank anything.
        # Percentile ranks of rank-correlated inputs are p and (1-p); with one dimension
        # inverted the weighted sum is exactly 0.500 for every candidate at ANY pool
        # size. Etsy data has that shape by nature — popular keywords carry more
        # listings — so this is the normal case, not an edge case.
        #
        # can_discriminate() asks before scoring rather than annotating afterwards,
        # because by the time score_pool flags a flat result the caller already holds an
        # ordered list and will treat it as a judgement. The real ranking happens in
        # STEP 6, once the deep dive has supplied intent and profit.
        pool = [{"key": n["keyword"], "demand": n["volume"], "supply": n["competition"]}
                for n in scored_niches]
        weights = {"demand": 0.5, "supply": 0.5}
        verdict = can_discriminate(pool, weights)

        if verdict.ok:
            ranked = score_pool(pool, weights=weights,
                                pool_id=f"niche_finder:{self.seed}")
            by_key = {r.key: r for r in ranked}
            for n in scored_niches:
                r = by_key.get(n["keyword"])
                if r:
                    n["base_opportunity_score"] = r.score
                    n["score_confidence"] = r.confidence
                    n["score_reasons"] = list(r.reasons)
            scored_niches = sorted(scored_niches,
                                   key=lambda x: x.get("base_opportunity_score", 0),
                                   reverse=True)
            top_3 = scored_niches[:3]
            print(f"\n  [3] Shortlist (ranked — {verdict.reason}):")
            for idx, niche in enumerate(top_3):
                print(f"      #{idx+1} '{niche['keyword']}': "
                      f"{niche['base_opportunity_score']:.3f} "
                      f"(Vol: {niche['volume']}, Comp: {niche['competition']})")
        else:
            picks = shortlist(pool, limit=3)
            chosen = {p.key: p for p in picks}
            for n in scored_niches:
                # No score is written. A number here would be read as merit, and there
                # is none to report — that is the whole finding.
                n["shortlist_reason"] = (chosen[n["keyword"]].reason
                                         if n["keyword"] in chosen else None)
                n["selection"] = "filter"
            top_3 = [n for n in scored_niches if n["keyword"] in chosen]
            print(f"\n  [3] Shortlist (FILTER, not a ranking):")
            print(f"      [!] {verdict.reason}")
            print(f"      [!] These {len(top_3)} are selected as worth a metered "
                  f"deep-dive call. Their ORDER means nothing. Ranking happens in "
                  f"step 6, once intent and profit exist.")
            for niche in top_3:
                print(f"      · '{niche['keyword']}' — {niche['shortlist_reason']}")
            
        # STEP 4: SINGLE DEEP DIVE ON WINNERS
        print(f"\n  [4] Executing Deep-Dive on Winners to Extract True Pricing & CVR...")
        final_winners = []
        
        for niche in top_3:
            kw = niche["keyword"]
            print(f"      -> Extracting Absolute Truth for '{kw}'...")
            time.sleep(1)
            
            data = self.api.get_results_data(kw)
            if data and "stats" in data:
                cvr = data["stats"].get("cvr", 0)
                prices = data.get("competitivePriceData", {}).get("searchTermMedianPrice", {})
                low_price = prices.get("medianPriceLow", "Unknown")
                high_price = prices.get("medianPriceHigh", "Unknown")
                
                niche["cvr_bucket"] = cvr
                niche["pricing_band"] = f"{low_price} to {high_price}"
                niche["median_price_low"] = parse_price(low_price)
                niche["median_price_high"] = parse_price(high_price)
                final_winners.append(niche)

                print(f"         [!] Verified: CVR={cvr} | Buyer Pays: {niche['pricing_band']}")

        # STEP 5: PROFIT GATE (D-01)
        #
        # Everything above ranks on demand and supply — how many people want it and how
        # many sellers there are. Neither says whether the operator makes any money, and
        # GOAL.md:104-120 is explicit that ranking on demand is what made the original
        # design pick the wrong products. This is the first step that can say no.
        #
        # A gate, not a weighted term: a product below its margin floor is not "a lower
        # score", it is not worth listing. Nothing is silently dropped — rejects keep
        # their verdict and reasons and are reported.
        print(f"\n  [5] Applying Profit Gate ({self.profile.get('product_type', DIGITAL)} "
              f"product, ${self.profile.get('labor_minutes', 0)} min build)...")
        passed, rejected, unjudged = [], [], []

        for niche in final_winners:
            # The LOW end of the median band: if it clears there it clears across the
            # band. Using the high end would flatter every candidate.
            price = niche.get("median_price_low")
            if price is None:
                # No measured price means no verdict. Excluding it here would be
                # indistinguishable from judging it unprofitable, so it is carried
                # through separately and labelled.
                niche["profit_verdict"] = None
                niche["profit_basis"] = "unjudged: no median price in the API response"
                unjudged.append(niche)
                print(f"      ❔ '{niche['keyword']}': no price returned — cannot judge, not rejected")
                continue

            v = verdict(price=price, **self.profile)
            niche["profit_verdict"] = v
            niche["profit_basis"] = "derived_from_measured_price_and_operator_profile"

            if v["go"]:
                passed.append(niche)
                print(f"      ✅ '{niche['keyword']}': ${v['profit_per_unit']:.2f}/unit at "
                      f"{v['margin']:.1%} margin (floor {v['margin_floor']:.0%})")
            else:
                rejected.append(niche)
                print(f"      ❌ '{niche['keyword']}': ${v['profit_per_unit']:.2f}/unit at "
                      f"{v['margin']:.1%} margin — REJECTED")
            for reason in v["reasons"]:
                print(f"           ! {reason}")

        judged = passed + rejected
        fee_date = judged[0]["profit_verdict"]["fee_schedule_verified"] if judged else "n/a"
        print(f"\n      [+] {len(passed)} passed, {len(rejected)} rejected, "
              f"{len(unjudged)} unjudged (fee schedule verified {fee_date}).")

        # STEP 6: THE ACTUAL RANKING (N-01)
        #
        # This is the first point where a ranking can carry information. The deep dive
        # supplied intent (CVR) and the profit gate supplied weekly profit, so the pool
        # now has four dimensions instead of two — and unlike demand/supply, intent and
        # profit are not rank-correlated with volume. can_discriminate() is asked again
        # rather than assumed: four dimensions CAN separate a pool, but this particular
        # pool still might not, and finding that out afterwards is too late.
        if len(passed) >= 2:
            final_pool = [{
                "key": n["keyword"],
                "demand": n["volume"],
                "supply": n["competition"],
                "intent": n.get("cvr_bucket"),
                "profit": n["profit_verdict"]["profit_per_unit"],
            } for n in passed]
            final_weights = {"demand": 0.2, "supply": 0.15, "intent": 0.25, "profit": 0.4}
            final_verdict = can_discriminate(final_pool, final_weights)

            print(f"\n  [6] Ranking the {len(passed)} profitable niche(s)...")
            if final_verdict.ok:
                try:
                    ranked = score_pool(final_pool, weights=final_weights,
                                        pool_id=f"niche_finder_final:{self.seed}")
                    by_key = {r.key: r for r in ranked}
                    for n in passed:
                        r = by_key[n["keyword"]]
                        n["final_score"] = r.score
                        n["final_confidence"] = r.confidence
                        n["final_reasons"] = list(r.reasons)
                    passed.sort(key=lambda n: n["final_score"], reverse=True)
                    for idx, n in enumerate(passed):
                        print(f"      #{idx+1} '{n['keyword']}': {n['final_score']:.3f} "
                              f"(confidence {n['final_confidence']:.0%})")
                except PoolTooSmall as e:
                    print(f"      [!] {e} — left unranked rather than ordered arbitrarily.")
            else:
                print(f"      [!] Still cannot rank: {final_verdict.reason}")
                print(f"      [!] Left in shortlist order. Do not read it as merit.")
        elif passed:
            print(f"\n  [6] One niche passed the profit gate — nothing to rank against.")
        if not passed and rejected:
            print(f"      [!] Every candidate failed the profit gate. Demand is real; the "
                  f"margin is not. Try a different product profile or a different seed.")

        # FINAL OUTPUT
        final_report = {
            "seed": self.seed,
            "max_depth_scanned": self.max_depth,
            "total_niches_analyzed": len(kw_list),
            "product_profile": self.profile,
            # top_3_deep_dive keeps its meaning for existing consumers (master_arbitrage
            # reads it); the profit split is additive so nothing downstream breaks.
            "top_3_deep_dive": final_winners,
            "profitable": passed,
            "rejected_on_profit": rejected,
            "unjudged_no_price": unjudged,
            "all_scored_niches": scored_niches
        }
        
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/hyper_master_niche_{self.seed.replace(' ', '_')}.json"
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=4)
            
        print(f"\n[+] Master Engine Complete! Final Blueprint saved to: {report_path}")
        return final_report

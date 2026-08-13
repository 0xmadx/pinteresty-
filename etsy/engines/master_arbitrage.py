import json
import os
import time


from etsy.engines.master_niche_finder import MasterNicheFinder
from etsy.api.public.api import EtsyPublicAPI
from etsy.analytics.gaps import PHYSICAL, find_gaps, summarise
from core.database import MarketDatabase
from core.guards import report_failures, reset_failures
from core.runlog import stage

class HybridArbitrageEngine:
    def __init__(self, seed_keyword, max_depth=1, max_nodes=10, product_type=PHYSICAL,
                 product_profile=None):
        """
        The Ultimate Hybrid Engine.
        1. Uses Private API (Master Niche Finder) to find Global Demand winners.
        2. Uses Public API (Grid Search) to analyze Geographic & Format Arbitrage loops.

        `product_type` gates which of the seven dimensions can produce a meaningful
        bracket (DECISION_LOG.md D-10): shipping speed on a digital download is 0%
        by structure, not by opportunity. Pass gaps.DIGITAL / gaps.PERSONALIZED when
        the seed is known to be one.

        `product_profile` is handed to MasterNicheFinder's profit gate. It defaults to
        the same product_type with no costs — which is only realistic for a digital
        download, so pass real `cogs` / `shipping_cost` / `labor_minutes` for anything
        physical or made to order, otherwise the gate flatters every candidate.
        """
        self.seed = seed_keyword
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.product_type = product_type
        self.product_profile = product_profile or {"product_type": product_type}
        self.public_api = EtsyPublicAPI()
        self.db = MarketDatabase()
        
    def run(self):
        print("\n==========================================================")
        print("          STARTING HYBRID ARBITRAGE ENGINE")
        print("==========================================================")
        # Counts describe this run only; the summary prints at the end.
        reset_failures()

        # STEP 1: PRIVATE DEMAND DISCOVERY
        print("\n[PHASE 1] Discovering Global Demand (Private API)...")
        with stage("discover", seed=self.seed, max_nodes=self.max_nodes) as st:
            master_engine = MasterNicheFinder(self.seed, self.max_depth, self.max_nodes,
                                              product_profile=self.product_profile)
            private_report = master_engine.run()
            st.count(rows_out=len(private_report.get("all_scored_niches", []))
                     if private_report else 0)

        if not private_report or not private_report.get("top_3_deep_dive"):
            print("[-] No winners found in Private Phase. Exiting.")
            return

        # Arbitrage only what cleared the profit gate. Slicing an unprofitable keyword
        # seven ways costs ~20 public requests and cannot change the verdict — the gap
        # analysis answers "where is there room", never "is this worth making".
        # Unjudged candidates (no price returned) are included: not judged is not failed.
        winners = private_report.get("profitable", []) + private_report.get("unjudged_no_price", [])
        rejected = private_report.get("rejected_on_profit", [])
        if rejected:
            print(f"[+] Skipping {len(rejected)} niche(s) that failed the profit gate: "
                  f"{', '.join(n['keyword'] for n in rejected)}")
        if not winners:
            print("[-] No niche cleared the profit gate. Nothing to arbitrage — a real "
                  "answer, not a failure. Try a different product profile or seed.")
            return

        print(f"\n[+] Private Discovery Complete. Proceeding to Arbitrage on {len(winners)} profitable niches.")
        
        # STEP 2: PUBLIC ARBITRAGE LOOP
        print("\n[PHASE 2] Executing Geographic & Format Arbitrage (Public API)...")
        
        # Arbitrage Locales to Test (using Etsy's GeoNames IDs for locationQuery)
        locales = {
            "USA (Domestic)": "6252001",
            "United Kingdom": "2635167",
            "Germany": "2921044",
            "Australia": "2077456",
            "Canada": "6251999"
        }
        
        arbitrage_results = []
        # ~24 public requests per niche. Recorded so question 4 — "what did the budget
        # cost?" — has a real number rather than an estimate.
        public_calls = 0
        # Guard counts from here on belong to the arbitrage stage, whose record is
        # written after the loop (reset=False there).
        reset_failures()

        for niche in winners:
            keyword = niche["keyword"]
            global_demand = niche["volume"]
            print(f"\n  🎯 Arbitraging: '{keyword}' (Global Searches: {global_demand})")
            
            niche_report = {
                "keyword": keyword,
                "private_demand": global_demand,
                "private_cvr": niche.get("cvr_bucket"),
                "format_arbitrage": {},
                "geo_arbitrage": {}
            }

            # Every measured bracket lands here as (dimension, value) -> listing count,
            # then is classified ONCE by find_gaps() at the end — raw percentages are
            # recorded but never turned into verdicts inline.
            bracket_counts = {}

            # --- A. FORMAT ARBITRAGE (Digital vs Physical) ---
            print(f"      -> Checking Format Saturation (Digital vs Physical)...")
            time.sleep(1)
            
            # Search Digital
            digital_data = self.public_api.get_public_search(keyword, filters={"is_digital": 1})
            dig_total = digital_data.get("total_results", 0) if digital_data else 0
            
            # Search General (Assume mostly physical if we subtract digital, but we can't perfectly subtract because some tags overlap, but it's a good proxy)
            general_data = self.public_api.get_public_search(keyword)
            gen_total = general_data.get("total_results", 0) if general_data else 0
            
            niche_report["format_arbitrage"] = {
                "total_listings": gen_total,
                "digital_listings": dig_total,
                "digital_saturation_percent": round((dig_total / gen_total * 100) if gen_total > 0 else 0, 2)
            }
            bracket_counts[("format", "digital")] = dig_total
            print(f"         [!] Digital Saturation: {niche_report['format_arbitrage']['digital_saturation_percent']}% ({dig_total} digital items)")
            
            # --- B. GEOGRAPHIC ARBITRAGE (Shop Location / Local Monopoly) ---
            print(f"      -> Checking Geographic Loopholes (Shop Located In)...")
            
            for country_name, country_code in locales.items():
                time.sleep(1)
                geo_data = self.public_api.get_public_search(keyword, filters={"locationQuery": country_code})
                geo_total = geo_data.get("total_results", 0) if geo_data else 0
                
                niche_report["geo_arbitrage"][country_name] = geo_total
                bracket_counts[("geographic", country_name)] = geo_total

                # No verdict here: a low count is only a gap if demand holds inside the
                # bracket — that judgement is made once, by find_gaps(), below.
                print(f"         [{country_code}] Shops located in {country_name}: {geo_total}")
                
            # --- C. QUALITY ARBITRAGE (Star Seller, Etsy's Pick, 5-Star Reviews) ---
            print(f"      -> Checking Quality Saturation (Star Seller, Etsy's Pick, 5-Star Reviews)...")
            time.sleep(1)
            
            pro_data = self.public_api.get_public_search(keyword, filters={"is_star_seller": "1"})
            pro_total = pro_data.get("total_results", 0) if pro_data else 0
            
            time.sleep(1)
            pick_data = self.public_api.get_public_search(keyword, filters={"best_by_etsy": "1"})
            pick_total = pick_data.get("total_results", 0) if pick_data else 0
            
            time.sleep(1)
            review_data = self.public_api.get_public_search(keyword, filters={"min_rating": "5"})
            review_total = review_data.get("total_results", 0) if review_data else 0
            
            niche_report["quality_arbitrage"] = {
                "star_seller_listings": pro_total,
                "etsys_pick_listings": pick_total,
                "5_star_listings": review_total,
                "star_seller_percent": round((pro_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "etsys_pick_percent": round((pick_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "5_star_percent": round((review_total / gen_total * 100) if gen_total > 0 else 0, 2)
            }
            bracket_counts[("quality", "star_seller")] = pro_total
            bracket_counts[("quality", "etsys_pick")] = pick_total
            bracket_counts[("quality", "5_star")] = review_total
            print(f"         [!] Star Seller Saturation: {niche_report['quality_arbitrage']['star_seller_percent']}% ({pro_total} items)")
            print(f"         [!] Etsy's Pick Saturation: {niche_report['quality_arbitrage']['etsys_pick_percent']}% ({pick_total} items)")
            print(f"         [!] 5-Star Review Saturation: {niche_report['quality_arbitrage']['5_star_percent']}% ({review_total} items)")
            
            # --- D. OCCASION ARBITRAGE (Holiday / Event Filter) ---
            # You can inject any specific holiday or occasion here (e.g., 'halloween', 'christmas', 'wedding')
            target_holiday = "halloween"
            print(f"      -> Checking Occasion Arbitrage ({target_holiday})...")
            time.sleep(1)
            
            holiday_data = self.public_api.get_public_search(keyword, filters={"holiday": target_holiday})
            holiday_total = holiday_data.get("total_results", 0) if holiday_data else 0
            
            niche_report["occasion_arbitrage"] = {
                "target_holiday": target_holiday,
                "holiday_listings": holiday_total
            }
            bracket_counts[("occasion", target_holiday)] = holiday_total
            # --- E. SPECIAL OFFERS ARBITRAGE (Personalization & Discounts) ---
            print(f"      -> Checking Feature Arbitrage (Personalization, Free Shipping, Discounts)...")
            time.sleep(1)
            
            # Personalizable Saturation
            pers_data = self.public_api.get_public_search(keyword, filters={"is_personalizable": "true"})
            pers_total = pers_data.get("total_results", 0) if pers_data else 0
            
            # Discount / Sale Saturation
            time.sleep(1)
            disc_data = self.public_api.get_public_search(keyword, filters={"is_discounted": "true"})
            disc_total = disc_data.get("total_results", 0) if disc_data else 0
            
            # Free Shipping Saturation
            time.sleep(1)
            free_data = self.public_api.get_public_search(keyword, filters={"free_shipping": "true"})
            free_total = free_data.get("total_results", 0) if free_data else 0
            
            # Gift Wrapping Saturation
            time.sleep(1)
            gift_wrap_data = self.public_api.get_public_search(keyword, filters={"gift_wrap": "true"})
            gift_wrap_total = gift_wrap_data.get("total_results", 0) if gift_wrap_data else 0
            
            niche_report["feature_arbitrage"] = {
                "personalizable_listings": pers_total,
                "discounted_listings": disc_total,
                "free_shipping_listings": free_total,
                "gift_wrap_listings": gift_wrap_total,
                "personalizable_percent": round((pers_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "discounted_percent": round((disc_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "free_shipping_percent": round((free_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "gift_wrap_percent": round((gift_wrap_total / gen_total * 100) if gen_total > 0 else 0, 2)
            }
            bracket_counts[("personalizable", "true")] = pers_total
            bracket_counts[("discount", "true")] = disc_total
            bracket_counts[("free_shipping", "true")] = free_total
            bracket_counts[("gift_wrap", "true")] = gift_wrap_total
            
            print(f"         [!] Personalization Saturation: {niche_report['feature_arbitrage']['personalizable_percent']}%")
            print(f"         [!] Discount/Sale Saturation: {niche_report['feature_arbitrage']['discounted_percent']}%")
            print(f"         [!] Free Shipping Saturation: {niche_report['feature_arbitrage']['free_shipping_percent']}%")
            print(f"         [!] Gift Wrapping Saturation: {niche_report['feature_arbitrage']['gift_wrap_percent']}%")
            
            # --- F. SHIPPING SPEED ARBITRAGE (Delivery Days) ---
            print(f"      -> Checking Shipping Speed Arbitrage (Delivery within 7 vs 14 days)...")
            time.sleep(1)
            
            fast_ship_data = self.public_api.get_public_search(keyword, filters={"delivery_days": "7"})
            fast_ship_total = fast_ship_data.get("total_results", 0) if fast_ship_data else 0
            
            time.sleep(1)
            std_ship_data = self.public_api.get_public_search(keyword, filters={"delivery_days": "14"})
            std_ship_total = std_ship_data.get("total_results", 0) if std_ship_data else 0
            
            niche_report["shipping_arbitrage"] = {
                "fast_shipping_listings": fast_ship_total,
                "standard_shipping_listings": std_ship_total,
                "fast_shipping_percent": round((fast_ship_total / gen_total * 100) if gen_total > 0 else 0, 2),
                "standard_shipping_percent": round((std_ship_total / gen_total * 100) if gen_total > 0 else 0, 2)
            }
            bracket_counts[("shipping_speed", "7_days")] = fast_ship_total
            bracket_counts[("shipping_speed", "14_days")] = std_ship_total
            
            print(f"         [!] Fast Shipping (7 Days) Saturation: {niche_report['shipping_arbitrage']['fast_shipping_percent']}% ({fast_ship_total} items)")
            print(f"         [!] Standard Shipping (14 Days) Saturation: {niche_report['shipping_arbitrage']['standard_shipping_percent']}% ({std_ship_total} items)")
            
            # --- G. COLOR ARBITRAGE (attr_1) ---
            print(f"      -> Measuring Color Bracket Saturation...")
            
            color_map = {
                "black": "1",
                "white": "10",
                "red": "9",
                "blue": "2",
                "pink": "7",
                "gold": "1220",
                "silver": "8"
            }
            
            niche_report["color_arbitrage"] = {}
            for color_name, color_id in color_map.items():
                time.sleep(1)
                color_data = self.public_api.get_public_search(keyword, filters={"attr_1": color_id})
                color_total = color_data.get("total_results", 0) if color_data else 0
                niche_report["color_arbitrage"][color_name] = color_total
                bracket_counts[("color", color_name)] = color_total

                percent = round((color_total / gen_total * 100) if gen_total > 0 else 0, 2)
                print(f"         [{color_name.title()}] Saturation: {percent}% ({color_total} items)")

            # --- H. MASTER DATABASE INTELLIGENCE ---
            print(f"      -> Pulling Master State Intelligence from Database...")
            db_keyword = self.db.get_keyword(keyword)
            db_trend = self.db.get_trend(keyword)
            
            niche_report["database_intelligence"] = {
                "private_api_cvr": db_keyword.get("query_cvr") if db_keyword else None,
                "private_api_price_low": db_keyword.get("median_price_low") if db_keyword else None,
                "private_api_price_high": db_keyword.get("median_price_high") if db_keyword else None,
                "pinterest_trend_color": db_trend.get("dominant_color") if db_trend else None,
                "pinterest_takeoff": db_trend.get("takeoff_timestamp") if db_trend else None
            }

            # --- I. GAP CLASSIFICATION (D-10: the empty-bracket gate) ---
            # The one place a bracket may be called an opportunity. Nothing above this
            # measures demand *inside* any bracket, so demand_by_bracket is empty and no
            # bracket can classify as "gap" yet — thin ones come back "thin_but_unproven",
            # which is the honest reading. When per-bracket demand exists (e.g. bracket-
            # filtered search volume from the private API), wire it in here.
            print(f"      -> Classifying brackets ({self.product_type} product rules)...")
            classified = find_gaps(bracket_counts, self.product_type,
                                   total_listings=gen_total, demand_by_bracket={})
            niche_report["gap_analysis"] = {
                "product_type": self.product_type,
                "summary": summarise(classified),
                "brackets": [
                    {"dimension": b.dimension, "value": b.value, "listings": b.listings,
                     "share": round(b.share, 4), "status": b.status,
                     "demand_evidence": b.demand_evidence, "note": b.note}
                    for b in classified
                ],
            }
            for b in classified:
                if b.status in ("gap", "thin_but_unproven", "not_applicable"):
                    print(f"         [{b.status}] {b.dimension}={b.value} "
                          f"({b.share:.1%}){' - ' + b.note if b.note else ''}")

            # Every get_public_search above: format 2, geo 5, quality 3, occasion 1,
            # feature 4, shipping 2, colour 7.
            public_calls += 24
            arbitrage_results.append(niche_report)

        # STEP 3: SAVE MASTER REPORT
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/arbitrage_{self.seed.replace(' ', '_')}.json"
        
        final_payload = {
            "seed": self.seed,
            "product_profile": self.product_profile,
            "arbitrage_analysis": arbitrage_results
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4)

        print(f"\n[+] Hybrid Engine Complete! Arbitrage Blueprint saved to: {report_path}")

        # Anything the parsers tolerated along the way. Silence here means a clean run —
        # which is only meaningful because a dirty one now says so.
        if report_failures():
            print("      [!] Fields above that came back empty may be unmeasured rather "
                  "than absent. Check the selectors before trusting this report.")

        # The arbitrage phase as one stage record. reset=False so it captures the guard
        # failures accumulated across the loop above, which was reset before it started.
        with stage("arbitrage", seed=self.seed, product_type=self.product_type,
                   quiet=True, reset=False) as st:
            st.count(rows_in=len(winners), rows_out=len(arbitrage_results),
                     cache_misses=public_calls)
            st.note(f"report: {report_path}")
        print(f"[+] Run health: python -m core.runlog")

if __name__ == "__main__":
    engine = HybridArbitrageEngine(seed_keyword="mom necklace", max_depth=1, max_nodes=5)
    engine.run()

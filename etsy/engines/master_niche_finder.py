import json
import os
import time
from collections import deque
from etsy.api.private.api import EtsyPrivateAPI
from etsy.analytics.derivations import parse_price
from etsy.analytics.profit import DIGITAL, verdict
from etsy.analytics.scoring import (PoolTooSmall, can_discriminate, score_pool,
                                    shortlist)
from etsy.analytics.survivorship import describe, survivor_bound
from core import runlog
from core.database import MarketDatabase
from core.runlog import logged_stage

# What the operator would actually make if they entered this niche. Profit cannot be
# computed without it — a keyword has no COGS or build time, a *product* does. The
# default is a digital download: no unit cost, no shipping, no labour, so its economics
# follow from the measured price alone and need no guesses from the operator.
DEFAULT_PROFILE = {"product_type": DIGITAL}

# NOTE — the "15 analyses per period" in REPO_STRUCTURE_AND_CONFIG.md:115 and
# pinterest/endpoints/overviews.md:10 was never observed by this system and has been
# tested against directly by the operator, who found no limit. No budget constant is
# enforced here as a result; SessionManager.rate_limited is the live check that would
# prove otherwise.


class MasterNicheFinder:
    def __init__(self, seed_keyword, max_depth=2, max_nodes=50, product_profile=None,
                 deep_dive_limit=None, edges_per_node=10):
        """
        The Hyper-Optimized Batch Engine.
        Crawls sub-keywords deeply, batches them to the comparison endpoint for speed,
        and deep-dives the shortlist.

        `product_profile` describes the product the operator would list, and is what
        makes the STEP 5 profit gate possible. Accepts any keyword of `profit.verdict()`
        except `price` (measured per niche): `product_type`, `cogs`, `shipping_cost`,
        `shipping_charged`, `labor_minutes`, `demand_units_per_week`, `offsite_ads`.

        `deep_dive_limit` — how many crawled keywords get `get_results_data`.
        **None (the default) means no limit: deep-dive every candidate.**

        History, because this number shaped the whole engine. It was hardcoded to 3 to
        ration a documented quota (`REPO_STRUCTURE_AND_CONFIG.md:115`
        `demand_calls_per_day: 15`; `pinterest/endpoints/overviews.md:10` "15 analyses
        per period"). The operator has since tested the endpoint directly and found no
        limit, and nothing in this system has ever recorded one — so the ceiling is
        treated as folklore inherited from the docs rather than a measured constraint.

        That changes the engine's shape. With only 3 deep dives, 47 of 50 candidates were
        discarded by a demand/supply score that N-01 proves cannot discriminate, and
        intent (CVR) and profit — the dimensions that CAN rank — only ever existed for
        the 3 survivors. Covering the whole pool removes the arbitrary cut entirely:
        STEP 3 stops filtering, and STEP 6 ranks everything on measured intent and profit.

        The safety net is still live rather than removed: `SessionManager.rate_limited`
        counts 429s, and every run reports analyses spent. If a limit does exist, it
        will now announce itself instead of being silently absorbed — set an integer
        here to cap the run if that happens.
        """
        self.seed = seed_keyword
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        # None = no cap. max_nodes already bounds the crawl, so this covers everything
        # the crawl found rather than introducing a second, arbitrary limit.
        self.deep_dive_limit = max_nodes if deep_dive_limit is None else deep_dive_limit
        # How many distinct sub-keywords to pull from each node. get_similar_keywords is
        # an LLM endpoint that returns DIFFERENT terms on each call, so this is the number
        # of enqueue+poll rounds it runs and de-dupes. The crawl loop overrode the
        # method's own default of 10 down to 2 — a frugality hack for a quota that does
        # not exist. Restored to 10: each node now offers up to ~5x more real candidates,
        # so the shared max_nodes bucket fills with denser, closer-to-seed suggestions
        # rather than a thin scattering forced wide. It is slower on a cold crawl (10
        # rounds x 1.5s poll each, per node) but get_similar_keywords is cached, so that
        # cost is paid once per keyword and every re-run is instant.
        self.edges_per_node = edges_per_node
        self.profile = dict(product_profile or DEFAULT_PROFILE)
        self.api = EtsyPrivateAPI()
        # Read-only here: the Pinterest bridge writes trend_observations, this joins
        # against it for momentum. Nothing in this engine writes trends.
        self.db = MarketDatabase()

    @logged_stage("niche_finder")
    def run(self):
        print(f"\n[MASTER ENGINE] Initializing Hyper-Optimized Spider for seed: '{self.seed}'")
        print(f"[MASTER ENGINE] Max Depth: {self.max_depth} | Max Nodes: {self.max_nodes} "
              f"| Edges/node: {self.edges_per_node}")
        
        # STEP 1: DEEP RECURSIVE CRAWL (BFS)
        print(f"\n  [1] Executing Deep Crawl...")
        keywords_to_analyze = set([self.seed])
        queue = deque([(self.seed, 0)])
        
        while queue and len(keywords_to_analyze) < self.max_nodes:
            current_keyword, current_depth = queue.popleft()
            
            print(f"      🕸️ [Depth {current_depth}] Mapping node '{current_keyword}'...")
            
            if current_depth < self.max_depth:
                edges = self.api.get_similar_keywords(current_keyword,
                                                      iterations=self.edges_per_node)
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

        # The best outcome is not to shortlist at all. Every candidate discarded here is
        # discarded on demand+supply alone, which cannot discriminate — so when the deep
        # dive can cover the whole pool, skipping this step removes the arbitrary cut
        # entirely and lets STEP 6 rank on real dimensions (intent, profit) instead.
        if self.deep_dive_limit >= len(scored_niches):
            top_3 = scored_niches
            for n in scored_niches:
                n["selection"] = "no_filter_applied"
            print(f"\n  [3] No shortlist needed — deep-diving all "
                  f"{len(scored_niches)} candidate(s).")
            print(f"      [+] Nothing is discarded on a demand/supply score that cannot "
                  f"discriminate. Ranking happens in step 6 on measured intent and profit.")
        elif verdict.ok:
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
            top_3 = scored_niches[:self.deep_dive_limit]
            print(f"\n  [3] Shortlist (ranked — {verdict.reason}):")
            for idx, niche in enumerate(top_3):
                print(f"      #{idx+1} '{niche['keyword']}': "
                      f"{niche['base_opportunity_score']:.3f} "
                      f"(Vol: {niche['volume']}, Comp: {niche['competition']})")
        else:
            picks = shortlist(pool, limit=self.deep_dive_limit)
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

                # The same call already returned the top listings for this keyword —
                # title, price, shop, rating and numberOfReviews each. This step used to
                # take cvr and prices and DISCARD the cards, after which the arbitrage
                # engine made ~24 public requests per niche to rebuild a thinner version
                # of them. numberOfReviews is exactly what the survivor bound needs, so
                # B-01 is now answerable from data already paid for, with no extra call.
                cards = data.get("competitiveResearchListingCards") or []
                if isinstance(cards, dict):
                    cards = cards.get("listingCards", [])
                niche["competitor_listings"] = cards

                if cards:
                    bound = survivor_bound(
                        [{"listing_id": c.get("listingId") or c.get("listingUrl"),
                          # Private field name; survivorship speaks review_count.
                          "review_count": c.get("numberOfReviews")}
                         for c in cards],
                        total_supply=niche.get("competition"))
                    niche["survivorship"] = {
                        "verdict": bound.verdict,
                        "reviewed_share": bound.reviewed_share,
                        "sample_size": bound.sample_size,
                        "total_supply": bound.total_supply,
                        "is_upper_bound": bound.is_upper_bound,
                        "note": bound.note,
                    }

                final_winners.append(niche)

                print(f"         [!] Verified: CVR={cvr} | Buyer Pays: {niche['pricing_band']}"
                      f" | {len(cards)} competitor listing(s)")
                if niche.get("survivorship"):
                    print(f"             {describe(bound)}")

        # STEP 4b: PINTEREST SIGNALS (the join)
        #
        # overviews.md §6 specifies the scoring model and where each variable comes
        # from. Momentum is Pinterest's mom_change, and it is FREE — but nothing ever
        # read it into the Etsy scorer, which is the deeper cause of N-01: the pool
        # collapsed to 0.500 because it had only demand and supply, two rank-correlated
        # dimensions, while a third independent one sat in the database unused.
        #
        # find_trend joins across the wording gap ("Mom Necklaces" vs "mom necklace");
        # a miss leaves momentum as None, which score_pool excludes from the weighting
        # rather than scoring as zero.
        matched = 0
        for niche in final_winners:
            trend = self.db.find_trend(niche["keyword"])
            if not trend:
                continue
            niche["pinterest"] = {
                "momentum": trend.get("growth_mom"),
                "velocity": trend.get("velocity"),
                "dominant_color": trend.get("dominant_color"),
                "demographic": trend.get("demographic"),
                "takeoff": trend.get("takeoff_timestamp"),
                "list_by": trend.get("list_by"),
                "matched_as": trend.get("trend_name"),
                "collected_at": trend.get("collected_at"),
            }
            matched += 1
            print(f"      🔗 '{niche['keyword']}' ← Pinterest '{trend.get('trend_name')}': "
                  f"momentum={trend.get('growth_mom')}"
                  + (f", list by {trend['list_by']}" if trend.get("list_by") else ""))

        if final_winners:
            print(f"      [+] {matched}/{len(final_winners)} joined to Pinterest data."
                  + ("" if matched else "  Run the Pinterest bridge to populate momentum "
                                        "— without it the ranking has one fewer dimension."))

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

        # The evidence that settles the quota question. Every deep dive is one metered
        # call; rate_limited counts 429s the session actually saw. If this run raised
        # deep_dive_limit and rate_limited is still 0, the rationing was unnecessary.
        # Budget accounting. The documented allowance is 15 analyses per period
        # (REPO_STRUCTURE_AND_CONFIG.md:115), and each deep dive spends one — so a run
        # says what it cost rather than leaving the operator to guess.
        throttled = getattr(self.api.session, "rate_limited", 0)
        runlog.count(metered_calls=len(final_winners))
        print(f"\n      [i] {len(final_winners)} analysis call(s), "
              f"{throttled} rate-limit response(s).")
        if throttled:
            # The one case that would overturn the operator's finding. Loud, because a
            # throttle silently absorbed is how the original folklore survived.
            print(f"      [!] Etsy throttled this run — a limit DOES exist after all. "
                  f"Pass deep_dive_limit=<n> to cap it, and tell the docs.")

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
            # Momentum is Pinterest's free contribution and the dimension that breaks
            # the demand/supply correlation — it is None when the join missed, and
            # score_pool excludes a None from the weighting instead of scoring it zero.
            final_pool = [{
                "key": n["keyword"],
                "demand": n["volume"],
                "supply": n["competition"],
                "intent": n.get("cvr_bucket"),
                "profit": n["profit_verdict"]["profit_per_unit"],
                "momentum": (n.get("pinterest") or {}).get("momentum"),
                # B-10: the score inherits the age of its oldest input. The Pinterest
                # reading can be weeks older than the Etsy call made moments ago.
                "freshness": {"momentum": (n.get("pinterest") or {}).get("collected_at")},
            } for n in passed]
            final_weights = {"demand": 0.2, "supply": 0.1, "intent": 0.2,
                             "profit": 0.35, "momentum": 0.15}
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
            "deep_dive_limit": self.deep_dive_limit,
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

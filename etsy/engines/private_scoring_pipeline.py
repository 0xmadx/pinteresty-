"""
private_scoring_pipeline.py

Layer: engines/ (I/O — private API in, market database out)
Purpose: discover keywords from a seed, score them, and PERSIST the demand data
         (volume, CVR, supply) to the keywords table.

Repaired 2026-08-12. It previously imported `src.services.executor`, a module that
exists nowhere in this repo or its history, so it raised ModuleNotFoundError on
import and could never run. It also globbed `inputs/curl_commands/private/*.py`,
a directory that does not exist, to rebuild request definitions from saved cURL
text.

Neither is restorable and neither is needed: `EtsyPrivateAPI` already wraps both
endpoints this module used — `req_1` (the LLM enqueue) is `get_similar_keywords`,
and `req_3` (the 365-day chart) is `get_chart_series`. The repair replaces the
cURL-registry machinery with those typed methods, which also brings the shared
request cache, the session handling and the rate-limit detection with them.

⚠️ Note on what this module did NOT do: even when it ran, it wrote only JSON files
and never touched the database. The keywords table was never its output. It writes
`record_keyword` now, with real provenance (cvr_source measured vs default), which
is the thing that was actually wanted from it.
"""
import json
import os

from core import runlog
from core.database import MarketDatabase
from core.runlog import logged_stage
from etsy.analytics.scoring import PoolTooSmall, can_discriminate, score_pool
from etsy.api.private.api import EtsyPrivateAPI, edge_term

# Etsy returns CVR as an ordinal bucket, not a rate. 2 is "Typical"; below that the
# keyword converts poorly regardless of how much volume it has.
MIN_CVR_BUCKET = 2


class PrivateScoringPipeline:
    def __init__(self, api=None, db=None):
        print("Initializing Private Scoring Pipeline...")
        self.api = api or EtsyPrivateAPI()
        self.db = db or MarketDatabase()

    @logged_stage("private_scoring")
    def run_scoring(self, seed_keyword, iterations=10):
        """Discover → score → persist. Returns the ranked candidates."""
        base_dir = os.path.join("etsy", "data", "reports", "scoring_runs",
                                seed_keyword.replace(" ", "_"))
        os.makedirs(base_dir, exist_ok=True)

        # --- Phase 1: discovery ------------------------------------------------------
        print(f"\n--- Phase 1: Discovery for '{seed_keyword}' ---")
        edges = self.api.get_similar_keywords(seed_keyword, iterations=iterations) or []
        terms = [t for t in (edge_term(e) for e in edges) if t]
        if seed_keyword not in terms:
            terms.insert(0, seed_keyword)

        if not terms:
            print("[-] No keywords discovered. Nothing to score.")
            return []
        print(f"[+] Discovered {len(terms)} keywords.")

        # --- Phase 2: measure them in bulk -------------------------------------------
        # get_chart_series takes a batch, so the whole corpus costs a handful of calls.
        print(f"\n--- Phase 2: Measuring demand and supply ---")
        measured = []
        for i in range(0, len(terms), 3):
            chunk = terms[i:i + 3]
            chart = self.api.get_chart_series(chunk, days=365)
            for s in (chart or {}).get("termSummaries", []) or []:
                measured.append({
                    "keyword": s.get("searchTerm"),
                    "volume": s.get("searchVolume"),
                    "supply": s.get("avgTotalListings"),
                    "cvr": s.get("cvr"),
                })

        # --- Phase 3: gate, then persist ---------------------------------------------
        # The gates are the module's original ones. What is new is that everything
        # measured is WRITTEN, gated or not: a keyword rejected today is still a real
        # observation, and discarding it would lose history that cannot be re-created.
        print(f"\n--- Phase 3: Persisting {len(measured)} observations ---")
        candidates, written, skipped = [], 0, 0
        for m in measured:
            if not m["keyword"]:
                continue
            cvr = m.get("cvr")
            # cvr_source records whether Etsy returned a bucket or we fell back — a
            # defaulted value must never be stored looking like a measured one (P-3).
            cvr_measured = cvr is not None
            try:
                self.db.record_keyword(
                    keyword=m["keyword"], source="etsy_private",
                    volume=m.get("volume"), competition=m.get("supply"),
                    cvr=cvr if cvr_measured else 0.02,
                    cvr_source="measured" if cvr_measured else "default",
                    price_basis="absent")
                written += 1
            except Exception as e:
                print(f"[-] Failed to record '{m['keyword']}': {e}")

            if m.get("volume") is None or not m.get("supply") or m["supply"] <= 0:
                skipped += 1
                continue
            if cvr_measured and cvr < MIN_CVR_BUCKET:
                skipped += 1
                continue
            candidates.append(m)

        runlog.count(rows_in=len(terms), rows_out=written, errors=skipped)
        print(f"[+] {written} keyword observations written, "
              f"{len(candidates)} passed the CVR/supply gates.")

        # --- Phase 4: rank ------------------------------------------------------------
        if not candidates:
            print("[-] No candidate passed the gates.")
            return []

        pool = [{"key": c["keyword"], "demand": c["volume"],
                 "supply": c["supply"], "intent": c.get("cvr")} for c in candidates]
        weights = {"demand": 0.4, "supply": 0.3, "intent": 0.3}
        verdict = can_discriminate(pool, weights)

        if verdict.ok:
            try:
                ranked = score_pool(pool, weights=weights,
                                    pool_id=f"private_scoring:{seed_keyword}")
                by_key = {r.key: r for r in ranked}
                for c in candidates:
                    r = by_key.get(c["keyword"])
                    if r:
                        c["score"], c["confidence"] = r.score, r.confidence
                        c["reasons"] = list(r.reasons)
                candidates.sort(key=lambda c: c.get("score", 0), reverse=True)
            except PoolTooSmall as e:
                print(f"[!] {e} — left unranked rather than ordered arbitrarily.")
        else:
            # N-01: refuse to present an order that carries no information.
            print(f"[!] Not ranked: {verdict.reason}")

        out_path = os.path.join(base_dir, "ranked_candidates.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2)
        print(f"[+] Saved to {out_path}")

        for c in candidates[:5]:
            score = f"{c['score']:.3f}" if "score" in c else "unranked"
            print(f"    {c['keyword']}: {score}  "
                  f"(vol {c['volume']}, supply {c['supply']}, cvr {c.get('cvr')})")
        return candidates


if __name__ == "__main__":
    import sys
    seed = sys.argv[1] if len(sys.argv) > 1 else "anniversary gift"
    PrivateScoringPipeline().run_scoring(seed)

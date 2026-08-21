"""DISCOVER — the front door, and the selection effect baked into it.

Etsy's trending list is *Etsy's picks*, by criteria it does not publish. Treating it as
"what is trending" rather than "what Etsy is promoting" inherits someone else's agenda
as market truth — the B-01 failure applied to candidate generation rather than to
survivors.

Offline: a fake API.

    .venv/Scripts/python.exe -m etsy.analytics.test_discover
"""
from etsy.analytics.discover import attach_moments, trending_candidates

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


class FakeAPI:
    def __init__(self, by_id):
        self.by_id = by_id
        self.calls = []

    def get_trending_terms(self, taxonomy_id=199):
        self.calls.append(taxonomy_id)
        return self.by_id.get(taxonomy_id)


def payload(name, *terms):
    return {"category_name": name,
            "search_terms": [{"search_term": t, "search_volume": v} for t, v in terms]}


# --- gathering ---------------------------------------------------------------------
api = FakeAPI({
    1: payload("Accessories", ("keychain", 116288), ("bag charm", 81565)),
    891: payload("Home & Living", ("home decor", 310467), ("keychain", 90000)),
})
cands = trending_candidates(api, [1, 891])
check("terms are gathered across categories", len(cands) == 3, [c["term"] for c in cands])
check("sorted by volume, highest first",
      [c["term"] for c in cands][0] == "home decor", cands[0])

keychain = next(c for c in cands if c["term"] == "keychain")
check("a duplicate term is merged", len(cands) == 3, cands)
check("keeping the higher volume", keychain["volume"] == 116288, keychain)
check("and recording both categories",
      set(keychain["categories"]) == {"Accessories", "Home & Living"}, keychain)
# Breadth across categories is itself a signal, so it is kept rather than collapsed.

check("every candidate carries the curation bias",
      all(c["basis"] == "etsy_curated" for c in cands), cands)
# The whole list is Etsy's selection, not the top of the market by volume.

# --- absent volume is not zero -----------------------------------------------------
api = FakeAPI({1: {"category_name": "A",
                   "search_terms": [{"search_term": "mystery"},
                                    {"search_term": "known", "search_volume": 100}]}})
cands = trending_candidates(api, [1])
mystery = next(c for c in cands if c["term"] == "mystery")
check("a missing volume stays None", mystery["volume"] is None, mystery)
check("and does not sort as zero", cands[0]["term"] == "known", [c["term"] for c in cands])
# Sorting None as 0 would bury an unmeasured term below terms known to be tiny.

# --- empty and failed categories ----------------------------------------------------
api = FakeAPI({1: None, 66: payload("Art", ("fall png", 44409))})
cands = trending_candidates(api, [1, 66])
check("a category returning nothing is skipped, not fatal",
      [c["term"] for c in cands] == ["fall png"], cands)
check("both categories were still attempted", api.calls == [1, 66], api.calls)

# --- the seasonal join ---------------------------------------------------------------
rows = [{"moment": "christmas", "list_by": "2026-09-16", "state": "list_by"},
        {"moment": "halloween", "list_by": "2026-06-23", "state": "list_now",
         "is_late": True}]
tagged = attach_moments([
    {"term": "christmas ornament", "volume": 5000, "categories": ["Home"], "basis": "etsy_curated"},
    {"term": "halloween decor", "volume": 4000, "categories": ["Home"], "basis": "etsy_curated"},
    {"term": "keychain", "volume": 3000, "categories": ["Acc"], "basis": "etsy_curated"},
], rows)

by_term = {c["term"]: c for c in tagged}
check("a seasonal candidate gets its deadline",
      by_term["christmas ornament"]["list_by"] == "2026-09-16", by_term["christmas ornament"])
check("and is marked seasonal", by_term["christmas ornament"]["timing"] == "seasonal")
check("lateness carries through", by_term["halloween decor"]["is_late"] is True)

check("an evergreen term is labelled, not left blank",
      by_term["keychain"]["timing"] == "evergreen", by_term["keychain"])
check("and has no invented deadline", by_term["keychain"]["list_by"] is None)
# Blank would read as "not checked"; evergreen is a fact about the term.

# Measured live 2026-08-15: none of Etsy's 28 trending terms matched any of
# Pinterest's 13 moments. "back to school" and "fall png" are plainly seasonal but
# Pinterest's calendar is holiday-centric and has no moment for either. The join
# must therefore return evergreen rather than reach for the nearest holiday.
tagged = attach_moments(
    [{"term": "back to school", "volume": 211400, "categories": ["Art"],
      "basis": "etsy_curated"}], rows)
check("a seasonal term with no matching moment stays evergreen",
      tagged[0]["timing"] == "evergreen", tagged[0])
check("rather than being attached to an unrelated holiday",
      tagged[0]["moment"] is None, tagged[0])

check("no moments at all does not crash the join",
      attach_moments([{"term": "x", "volume": 1, "categories": [], "basis": "etsy_curated"}],
                     [])[0]["timing"] == "evergreen")

# --- winnability: market size is not opportunity -----------------------------------
from etsy.analytics.discover import rank_by_opportunity, winnability  # noqa: E402

# The exact numbers that exposed the flaw, measured live 2026-08-15.
home = winnability({"volume": 310467, "supply": 2160627, "cvr": 0.00005})
tag = winnability({"volume": 69874, "supply": 25031, "cvr": 0.00279})
check("a 2.1M-listing term is a wall", home["verdict"] == "wall", home)
check("and the reason quotes both numbers", "2,160,627 listings" in home["reason"], home)
check("a term with more searches than listings is winnable",
      tag["verdict"] == "winnable", tag)
check("the ratio is exposed, not just a rank",
      tag["demand_per_listing"] == 2.791, tag)
# A composite score would rank the list just as well and tell the operator nothing —
# "you cannot rank here" has to be checkable.

check("the middle ground is named contested",
      winnability({"volume": 1000, "supply": 2000, "cvr": 0.01})["verdict"] == "contested")

u = winnability({"volume": None, "supply": 5000})
check("an unsized term is unmeasured, not a wall", u["demand_per_listing"] is None, u)
check("and does not claim a verdict", "verdict" not in u, u)
# A 0 ratio would sort it beside terms measured to be hopeless (N-02).

# --- ranking flips the list ---------------------------------------------------------
data = {"home decor": {"volume": 310467, "supply": 2160627, "cvr": 0.00005},
        "backpack name tag": {"volume": 69874, "supply": 25031, "cvr": 0.00279},
        "unknown term": None}
ranked = rank_by_opportunity(
    [{"term": t, "volume": 0, "categories": [], "basis": "etsy_curated"} for t in data],
    lambda t: data[t])
check("the winnable term ranks first, despite 4x less volume",
      ranked[0]["term"] == "backpack name tag", [r["term"] for r in ranked])
check("the head term is demoted", ranked[1]["term"] == "home decor", ranked)
check("an unsized term is kept, at the end",
      ranked[-1]["term"] == "unknown term", ranked)
check("and records why it could not be ranked",
      ranked[-1]["winnability"]["basis"] == "fetch_failed", ranked[-1])
# Dropping it would hide a term merely because Etsy declined to size it.

# CVR breaks ties: of two equally crowded terms, the one whose searchers buy wins.
tied = {"a": {"volume": 100, "supply": 100, "cvr": 0.001},
        "b": {"volume": 100, "supply": 100, "cvr": 0.02}}
ranked = rank_by_opportunity(
    [{"term": t, "volume": 0, "categories": [], "basis": "etsy_curated"} for t in tied],
    lambda t: tied[t])
check("CVR breaks a tie on crowding", ranked[0]["term"] == "b", [r["term"] for r in ranked])

# --- seed expansion: the long tail, sized inline -----------------------------------
from etsy.analytics.discover import expand_seed, rank_expanded  # noqa: E402


class FakeSeedAPI:
    def __init__(self, edges):
        self.edges = edges

    def get_similar_keywords(self, seed):
        return self.edges


# The real edge shape: search_term (snake), plus volume and supply inline.
edges = [
    {"search_term": "felt ball garland", "search_volume": 693, "avg_total_listings": 11100},
    {"search_term": "felt banner", "search_volume": 2179, "avg_total_listings": 29606},
    {"search_term": "felt garland", "search_volume": 300, "avg_total_listings": 5000},  # the seed itself
    {"search_term": "", "search_volume": 5, "avg_total_listings": 10},                  # junk
]
cands = expand_seed(FakeSeedAPI(edges), "felt garland")
check("expansion drops the seed and the blank", len(cands) == 2, [c["term"] for c in cands])
check("each edge keeps its inline volume",
      next(c for c in cands if c["term"] == "felt banner")["volume"] == 2179, cands)
check("and its inline supply",
      next(c for c in cands if c["term"] == "felt banner")["supply"] == 29606, cands)
check("basis is seed_expansion, not etsy_curated",
      all(c["basis"] == "seed_expansion" for c in cands), cands)
# The curation here is ours (we chose the seed), not Etsy's promotional agenda.

ranked = rank_expanded(cands)
# felt banner 2179/29606 = 0.074 beats felt ball garland 693/11100 = 0.062.
check("ranked without any extra fetch (inline metrics)",
      ranked[0]["term"] == "felt banner", [r["term"] for r in ranked])
check("higher demand-per-listing ranks first",
      ranked[0]["winnability"]["demand_per_listing"]
      >= ranked[1]["winnability"]["demand_per_listing"], ranked)

check("an empty expansion is not fatal", expand_seed(FakeSeedAPI(None), "x") == [])
check("a seed that returns nothing yields nothing",
      expand_seed(FakeSeedAPI([]), "x") == [])

# --- the intent gate: rankable is not the same as bought (D-43) ---------------------
from etsy.analytics.discover import (MIN_POOL_FOR_INTENT, apply_intent,  # noqa: E402
                                     combined_verdict, confirm_intent)

# The reported failure, in numbers measured live 2026-08-20. Every one of these is a
# real term from the operator's own discovered pool, with its real query_cvr.
POOL_CVRS = {
    "custom family name necklace": 5.786e-05,   # the term the system ranked FIRST
    "nana necklace": 1.172e-04,
    "personalized gift": 1.897e-04,
    "self watering planter": 4.633e-04,
    "christmas eve box": 5.889e-04,
    "macrame plant hanger": 9.695e-04,
    "backpack name tag": 2.79e-03,
    "felt garland": 3.1e-04,
}
median_cvr = sorted(POOL_CVRS.values())[len(POOL_CVRS) // 2 - 1:][0]

# The headline case: a high ratio and a CVR a fifth of its peers'.
aspirational = {"volume": 11642, "supply": 6675, "cvr": 5.786e-05}
win = winnability(aspirational)
check("the ratio gate alone calls the aspirational term winnable",
      win["verdict"] == "winnable", win)
intent = confirm_intent(aspirational, median_cvr)
check("the intent gate sees it converting far below its peers",
      intent["cvr_vs_pool"] < 0.5, intent)
check("and calls it weak", intent["verdict"] == "weak", intent)
verdict, reason = combined_verdict(win, intent)
check("so the headline verdict is weak_intent, not winnable",
      verdict == "weak_intent", verdict)

# The claim is relative and says so — it must never read as an order count.
check("the reading is labelled a comparison, not a rate",
      "not a conversion rate" in intent["note"], intent)
check("and its basis names the comparison",
      intent["basis"] == "measured_relative", intent)
# volume x query_cvr was tried as an absolute order count first and thrown away:
# it implies 39.8 orders/month market-wide for "personalized gift", whose #1
# listing carries 14,733 reviews. See confirm_intent's docstring.

# weak_intent is a DISTINCT verdict from wall — they fail for opposite reasons.
crowded = {"volume": 310467, "supply": 2160627, "cvr": 0.00005}
wv, _ = combined_verdict(winnability(crowded), confirm_intent(crowded, median_cvr))
check("a crowded term is still a wall, not weak_intent", wv == "wall", wv)
# A wall has too many competitors; a weak-intent term has searchers who do not buy.

# A term that converts well keeps its verdict.
real = {"volume": 69874, "supply": 25031, "cvr": 2.79e-03}
ri = confirm_intent(real, median_cvr)
check("a well-converting term is measured strong", ri["verdict"] == "strong", ri)
check("and keeps its ratio verdict",
      combined_verdict(winnability(real), ri)[0] == "winnable")

# --- the gate REFUSES rather than judging against noise (D-15's discipline) --------
tiny = confirm_intent(aspirational, None)
check("with no pool median the gate refuses to judge",
      tiny["verdict"] == "unmeasured", tiny)
check("and names the pool as the reason", tiny["basis"] == "pool_too_small", tiny)
check("so the term keeps its ratio verdict rather than being rejected",
      combined_verdict(win, tiny)[0] == "winnable")

# --- absent is not zero, in the direction that matters (N-02) ----------------------
unsized = confirm_intent({"volume": 50000, "supply": 5000, "cvr": None}, median_cvr)
check("a term with no CVR is unmeasured, NOT weak",
      unsized["verdict"] == "unmeasured", unsized)
check("and claims no comparison", unsized["cvr_vs_pool"] is None, unsized)
uv, _ = combined_verdict(winnability({"volume": 50000, "supply": 5000, "cvr": None}),
                         unsized)
check("so it keeps its ratio verdict rather than being rejected", uv == "winnable", uv)
# Branding an unmeasured term weak would reject real niches on a missing field —
# the same error as calling an aspirational one winnable, in the other direction.

# --- apply_intent spends calls only where they can change the answer ---------------
calls = []
DATA = {t: {"volume": 10000, "supply": 5000, "cvr": c} for t, c in POOL_CVRS.items()}


def counting_fetch(term):
    calls.append(term)
    return DATA.get(term)


pool = [{"term": t, "volume": 10000,
         "winnability": winnability({"volume": 10000, "supply": 5000, "cvr": None})}
        for t in POOL_CVRS]
pool.append({"term": "a wall", "volume": 310467, "winnability": winnability(
    {"volume": 310467, "supply": 2160627, "cvr": None})})

checked = apply_intent(pool, counting_fetch, top_n=25)
check("no private call is spent on a term already rejected on supply",
      "a wall" not in calls, calls)
check("but every rankable candidate is checked",
      set(calls) == set(POOL_CVRS), calls)

by_term = {c["term"]: c for c in checked}
check("the weakest converter is re-labelled weak_intent",
      by_term["custom family name necklace"]["verdict"] == "weak_intent",
      by_term["custom family name necklace"])
check("the wall keeps its own verdict", by_term["a wall"]["verdict"] == "wall")
check("and the unchecked wall is marked not_checked, not 'checked and empty'",
      by_term["a wall"]["intent"]["basis"] == "not_checked", by_term["a wall"])

order = [c["term"] for c in checked]
weak = [c["term"] for c in checked if c["intent"].get("verdict") == "weak"]
check("a weak-intent term loses the seat its ratio won",
      "custom family name necklace" in weak, weak)
check("and every weak term sorts below every strong one",
      max(order.index(t) for t in ["backpack name tag", "macrame plant hanger"])
      < min(order.index(t) for t in weak), order)
# Every term here has an identical 2.0 ratio, so winnability alone cannot separate
# them at all — the CVR comparison is doing all the work, which is the point.

# The pool median is carried, so a reader can check the comparison themselves.
check("the reference used is exposed on every row",
      by_term["personalized gift"]["pool_median_cvr"] is not None, by_term)

# --- a pool too small to have a reference refuses, rather than guessing ------------
calls.clear()
small = apply_intent(pool[:3], counting_fetch, top_n=25)
check("below the minimum pool, no term is judged on intent",
      all((c["intent"]["verdict"] in (None, "unmeasured")) for c in small), small)
check("and the reason is the pool, named",
      any(c["intent"].get("basis") == "pool_too_small" for c in small), small)
check(f"the minimum is stated, not implicit", MIN_POOL_FOR_INTENT >= 8)

# --- the reference can be POOLED across seeds and across time ----------------------
from etsy.analytics.discover import (judge_intent, measure_intent,  # noqa: E402
                                     reference_median)

# Measured live 2026-08-20: a real sweep produced 9 seeds, 1,359 candidates and only
# SEVEN rankable terms in the whole pool. Judging per seed therefore refused on every
# one and graded nothing — the reference has to span the run, not one seed.
tiny_seed = pool[:3]
m1 = measure_intent(tiny_seed, counting_fetch, top_n=25)
check("one small seed cannot reach a reference alone",
      reference_median(m1.values()) is None, m1)

# Prior measured CVRs are already in the database and cost nothing to reuse.
prior = [9.119e-05, 2.561e-04, 2.703e-04, 4.212e-04, 8.439e-04, 1.089e-03]
ref = reference_median(m1.values(), extra_cvrs=prior)
check("but pooled with CVRs measured earlier, it does",
      ref is not None, ref)
check("and the pooled reference is a real median of everything given",
      0 < ref < 1e-2, ref)

judged = judge_intent(tiny_seed, m1, ref)
check("so terms in a small seed CAN now be judged",
      any(c["intent"].get("basis") == "measured_relative" for c in judged), judged)

# Only MEASURED CVRs belong in the reference — a default would drag the median
# toward a number nobody observed. (Enforced in MarketDatabase.measured_cvrs.)
check("a None or zero prior is ignored rather than counted as a data point",
      reference_median([], extra_cvrs=[None, 0] + prior) == reference_median(
          [], extra_cvrs=prior), "falsy CVRs must not enter the median")

# top_n bounds the spend on the private tier (D-29).
calls.clear()
apply_intent(pool, counting_fetch, top_n=2)
check("top_n bounds how many private calls the gate spends", len(calls) == 2, calls)

# A failed fetch is unmeasured, never weak.
no_data = apply_intent([pool[0]], lambda t: None, top_n=25)[0]
check("a failed fetch leaves intent unmeasured, not weak",
      no_data["intent"]["verdict"] == "unmeasured", no_data["intent"])
check("and the term keeps its ratio verdict", no_data["verdict"] == "winnable", no_data)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

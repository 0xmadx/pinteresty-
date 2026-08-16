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

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

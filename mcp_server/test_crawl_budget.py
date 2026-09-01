"""The crawl budget: a wall an agent cannot argue past. OFFLINE.

This is the only tool on the surface that spends `etsy_private` — the operator's
own seller account, which cannot be replaced (D-29) — and it spends it
recursively. Everything asserted here is about containment, not features.

The failure this prevents is specific and quiet: an agent exploring casually
passes `max_nodes=5000`, the tool clamps to 200 without saying so, and the agent
reports "I searched the whole neighbourhood" having seen 4% of it. A refusal is
noisy and correct; a silent clamp is a plausible wrong answer.

    .venv/Scripts/python.exe -m mcp_server.test_crawl_budget
"""
from mcp_server import tools_crawl as tc

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


fn = tc.keyword_crawl.__wrapped__


# --- the ceiling REFUSES, and refuses before touching anything --------------------
print()
r = fn(operation="crawl", seed="mom necklace", max_nodes=5000)
check("an over-cap max_nodes is refused, not clamped",
      r.get("ok") is False and str(tc.MAX_NODES) in r.get("error", ""), r.get("error"))
check("the refusal explains WHY the ceiling exists (the seller account)",
      "SELLER" in (r.get("fix") or "").upper(), r.get("fix"))

r = fn(operation="crawl", seed="mom necklace", max_depth=9)
check("an over-cap max_depth is refused",
      r.get("ok") is False and str(tc.MAX_DEPTH) in r.get("error", ""), r.get("error"))
check("and it says why depth specifically is dangerous",
      "cost" in (r.get("fix") or "").lower(), r.get("fix"))

r = fn(operation="crawl", seed="   ")
check("an empty seed is refused before any session work",
      r.get("ok") is False and "seed" in r.get("error", ""), r.get("error"))


# --- the budget proxy actually stops the crawl -------------------------------------
# A fake client that would happily return children for ever. If the proxy did not
# stop it, this test would hang or run away rather than fail politely — which is
# exactly the production failure mode being prevented.
print()


class RunawayAPI:
    """Returns a fresh batch of children for any term, without end."""

    def __init__(self):
        self.calls = 0

    def get_similar_keywords(self, term, iterations=10):
        self.calls += 1
        return [{"search_term": f"{term} {self.calls}-{i}",
                 "search_volume": 5000, "avg_total_listings": 100}
                for i in range(20)]


runaway = RunawayAPI()
proxy = tc._Budgeted(runaway, max_expansions=3, iterations=3)
spent = 0
try:
    for _ in range(50):
        proxy.get_similar_keywords("x")
        spent += 1
except tc._BudgetSpent:
    pass
check("the proxy raises once the expansion ceiling is hit", spent == 3, spent)
check("and the underlying client was called exactly that many times",
      runaway.calls == 3, runaway.calls)

check("the proxy forces the cheaper agent iteration count, not the CLI's 10",
      tc.AGENT_ITERATIONS < 10, tc.AGENT_ITERATIONS)


class RecordingAPI(RunawayAPI):
    def get_similar_keywords(self, term, iterations=10):
        self.seen_iterations = iterations
        return super().get_similar_keywords(term, iterations)


rec = RecordingAPI()
tc._Budgeted(rec, 5, tc.AGENT_ITERATIONS).get_similar_keywords("x")
check("and it passes that count through to the real call",
      rec.seen_iterations == tc.AGENT_ITERATIONS, rec.seen_iterations)

check("attribute access falls through to the wrapped client",
      tc._Budgeted(rec, 5, 3).calls == rec.calls)


# --- a real crawl under the proxy stops and still returns what it found ------------
print()
from etsy.analytics import keyword_crawl as kc  # noqa: E402

collected = []
budget = tc._Budgeted(RunawayAPI(), max_expansions=2, iterations=3)
try:
    kc.crawl(budget, "seed term", max_nodes=10_000, max_depth=5,
             on_node=collected.append)
    stopped = False
except tc._BudgetSpent:
    stopped = True

check("an unbounded crawl IS stopped by the budget", stopped)
check("and the nodes found before the stop survive via on_node",
      len(collected) > 0, len(collected))
check("the expansion count is exact, not estimated", budget.expansions == 2,
      budget.expansions)


# --- the request figure is a BOUND, and says so -----------------------------------
# Observed live: a 40-term crawl of `felt garland` returned in under a second and
# spent ZERO network requests, because get_similar_keywords is cached for 30 days.
# Reporting the derived per-expansion figure as a measurement would have been a
# plausible wrong number of exactly the kind this project exists to prevent.
print()
src = open(tc.__file__, encoding="utf-8").read()
check("the request figure is named as a bound, not a count",
      "private_requests_upper_bound" in src and
      "estimated_private_requests" not in src)
check("and its basis says a cached expansion spends nothing",
      "cached expansion spends 0" in src)
check("while the expansion count itself is still MEASURED",
      "expansions are MEASURED exactly" in src)


# --- the ceilings are real constants, not arguments --------------------------------
print()
check("MAX_EXPANSIONS is small enough to bound the seller spend",
      tc.MAX_EXPANSIONS * tc.REQUESTS_PER_EXPANSION <= 60,
      f"{tc.MAX_EXPANSIONS} x {tc.REQUESTS_PER_EXPANSION}")
check("MAX_NODES bounds what is RECORDED, which is free",
      tc.MAX_NODES >= tc.MAX_EXPANSIONS, (tc.MAX_NODES, tc.MAX_EXPANSIONS))
check("the module refuses rather than clamps — no min() on the caps at the gate",
      "return _fail(" in open(tc.__file__, encoding="utf-8").read().split(
          "max_nodes > MAX_NODES")[1][:200])


# --- drill: sub-niches as rows, and no silent slice --------------------------------
#
# `expand_seed` fetched exactly this data and returned `all_terms` — a flat list of
# bare strings — so the sub-niches could not be read, ranked, or chosen between,
# while the volume and supply for every one had already been paid for.
#
# The cap bug this pins: a drill pays for ONE expansion and every child arrives in
# that same response, so a node cap buys nothing and costs coverage. At the old
# default of 60 a live drill of `badge reel` kept 59 of the 173 edges Etsy returned
# and reported 59 as if that were the neighbourhood — a slice shown as the answer.
print()
src = open(tc.__file__, encoding="utf-8").read()
decide = open("mcp_server/tools_decide.py", encoding="utf-8").read()
drill_block = src.split(chr(39) + "drill" + chr(39))[0]
drill_block = src[src.index("if operation == " + chr(34) + "drill" + chr(34)):][:5200]
check("drill is a registered operation", chr(34) + "drill" + chr(34) in src)
check("drill expands exactly ONE level, like expand_seed",
      "(" + chr(34) + "expand_seed" + chr(34) + ", " + chr(34) + "drill" + chr(34) + ")" in src)
check("drill ignores the node cap - children are free once the expansion is bought",
      "MAX_NODES if operation ==" in src)
check("it reports what Etsy OFFERED, not just what it showed",
      "truncated_by_limit" in src and "children_found" in src)
check("and flags when the ceiling itself was reached", "hit_node_ceiling" in src)
check("rows are sorted by demand-per-listing, never volume (D-31)",
      "demand_per_listing" in drill_block)
check("an unsized child sorts LAST rather than as zero (N-02)",
      "is None," in drill_block and "or 0)" in drill_block)
check("the spend is a BOUND, since a re-drill hits the 30-day cache",
      "BOUND" in drill_block)
check("drill tells the reader the rows can be drilled again",
      "drill_next" in drill_block)
check("and compare points at drill, so every row in a comparison is a door",
      "operation=" + chr(39) + "drill" + chr(39) in decide)

print(f"\n{PASS} passed, {FAIL} failed")
raise SystemExit(1 if FAIL else 0)

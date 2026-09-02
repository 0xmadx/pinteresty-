"""Recursive keyword discovery — the expensive one, on a budget it cannot exceed.

This is the operator's stated need ("finding winning products"): one seed in, the
whole long-tail neighbourhood out, each term sized for winnability. It is also
**the single riskiest tool on this surface**, and the two facts are related.

WHY THIS NEEDS A CEILING AND NOTHING ELSE DOES
----------------------------------------------
The crawl spends `etsy_private` — the operator's OWN seller account, the one
asset here that cannot be replaced (D-29). A burned buyer session costs a
re-login; a burned seller account costs the business.

And the cost compounds three levels deep. Measured:

    get_similar_keywords(iterations=10)   10 enqueue rounds per keyword
      x each round polls until ready      ~2-3 typical, up to 10
      x crawl calls it once per node      1 per expanded node
    = ~35 private requests and ~90 SECONDS per keyword expanded

At the CLI's defaults (`max_nodes=150, max_depth=3`) a deep crawl runs to
hundreds of requests. That is a fine thing for a human to type deliberately and a
terrible thing for an agent to reach for while exploring.

HOW THE BUDGET WORKS — "let the MCP decide", inside a wall it cannot pass
------------------------------------------------------------------------
* A **hard ceiling** the tool REFUSES to exceed. An over-cap argument gets a
  `_fail` naming the limit — never a silent clamp, because an agent that asked
  for 5,000 nodes and got 200 without being told will believe it saw 5,000.
* **Inside** the ceiling the tool decides for itself: it stops early when the
  neighbourhood is exhausted, or when it has already found enough winnable
  pockets to answer the question.
* Every result carries `spent`, `remaining` and `stopped_because`, so going
  deeper is an explicit second call rather than an automatic escalation.
* `iterations` drops 10 -> 3 on the agent path. Each iteration asks Etsy's LLM
  again and gets DIFFERENT edges, so this trades some edge diversity for a ~3.5x
  cost cut — and the 30-day cache makes a repeat crawl of the same neighbourhood
  free.
"""
from typing import Annotated

from pydantic import Field

from mcp_server._ops import CrawlOp
from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp

# The wall. Deliberately module-level constants so they are greppable, testable,
# and cannot be raised by an argument.
MAX_EXPANSIONS = 4          # keywords whose children we fetch. ~10 requests each.
MAX_NODES = 200             # terms recorded (recording is free; expanding is not)
MAX_DEPTH = 2
AGENT_ITERATIONS = 3        # vs the CLI's 10
REQUESTS_PER_EXPANSION = 10  # 3 enqueues + ~2.3 polls each, measured


class _BudgetSpent(Exception):
    """Raised to unwind the crawl when the ceiling is reached. Not an error."""


class _EnoughFound(Exception):
    """Raised when the crawl has already answered the question. Not an error."""


class _Budgeted:
    """Wraps the private client, counts expansions, and stops the crawl dead.

    A proxy rather than a patched `crawl()`: the crawl's own logic — the
    best-first frontier, the cycle dedupe, the top-k pruning — is worth keeping
    exactly as the CLI runs it. All this changes is who is allowed to keep going.
    """

    def __init__(self, api, max_expansions, iterations):
        self._api = api
        self.max_expansions = max_expansions
        self.iterations = iterations
        self.expansions = 0

    def get_similar_keywords(self, term):
        if self.expansions >= self.max_expansions:
            raise _BudgetSpent()
        self.expansions += 1
        return self._api.get_similar_keywords(term, iterations=self.iterations)

    def __getattr__(self, name):
        return getattr(self._api, name)


_OP_DOC = (
    "crawl: recursive best-first expansion from one seed — records every term "
    "found and returns the winnable POCKETS, the specific terms whose "
    "demand-per-listing beats their saturated neighbourhood. "
    "expand_seed: one level only, cheaper, when you just want the immediate "
    "neighbours as a name list. drill: one level from one term, returning the "
    "SUB-NICHES as ranked rows carrying their own volume, supply and ratio. "
    "Those rows are the SAME shape as `compare`, and each can be drilled "
    "again — that is how you go sub-niche by sub-niche. "
    "ALL SPEND THE SELLER ACCOUNT — read `spent` "
    "and `stopped_because` on the way out."
)


@mcp.tool()
@_guarded
def find_terms(
    seed: str,
    sources: str = "etsy_suggest,pinterest_prefix",
    mode: str = "any",
    min_n: int = 2,
) -> dict:
    """Find candidate terms across SEVERAL doors and combine them with a stated rule.

    sources: comma list of etsy_suggest (PUBLIC, 2 req) · pinterest_prefix (1 req,
    each term carries 52wk momentum free) · etsy_expand (SPENDS THE SELLER ACCOUNT,
    but the only door returning volume+supply inline). Defaults to the two FREE ones.
    mode: any = union · all = only terms EVERY door returned · min_n = at least N agree.

    The doors return DIFFERENT SHAPES — Etsy's box gives children, its expansion
    gives siblings, Pinterest gives its own vocabulary — and the two Etsy doors were
    measured completely disjoint. Strings only: size with `compare` before ranking.
    """
    from etsy.analytics.sources import DOORS, discover_terms
    want = [x.strip() for x in (sources or "").split(",") if x.strip()]
    if not seed or not seed.strip():
        return _fail("`seed` is required")
    if not want:
        return _fail("`sources` is required",
                     fix=f"Pick from: {sorted(DOORS)}")

    # Preflight only the tiers actually asked for — requiring a pinterest session to
    # read Etsy's public search box would refuse a call that costs nothing.
    tiers = {DOORS[d]["tier"] for d in want if d in DOORS}
    blocked = _preflight(tuple(sorted(tiers))) if tiers else None
    if blocked:
        return blocked

    out = discover_terms(seed.strip(), sources=tuple(want), mode=mode, min_n=min_n)
    if out.get("basis") in ("unknown_source", "bad_mode"):
        return _fail(out.get("note", "bad request"))
    return _ok({"operation": "find_terms", **out,
                "next": "These are STRINGS — no volume, no supply. Size them with "
                        "`compare` (mode=cheap) before ranking anything."})


@mcp.tool()
@_guarded
def scout(
    seed: str,
    sources: str = "etsy_suggest,pinterest_prefix",
    mode: str = "any",
    size_mode: str = "cheap",
    limit: int = 24,
) -> dict:
    """The whole strategy in ONE call: discover across doors, size, rank.

    Cheap doors find candidates, the private tier sizes only the survivors, the
    gates rank what is left. Running it the other way spends the seller account on
    terms that were never going to matter.

    sources/mode are `find_terms`'s (any / all / min_n). size_mode is `compare`'s
    (cheap = ~2*ceil(N/3) requests + seasonal curve, no CVR; full = 1/term + CVR).
    Over `limit` it sizes the most-corroborated first and NAMES what it skipped in
    `not_sized` — a cut, declared, never a slice posing as the neighbourhood.

    Every row carries `found_by` beside its verdict: which populations use the word,
    and whether you could rank for it, stay SEPARATE facts.
    """
    from etsy.analytics.sources import DOORS, scout as _scout
    want = [x.strip() for x in (sources or "").split(",") if x.strip()]
    if not seed or not seed.strip():
        return _fail("`seed` is required")
    unknown = [d for d in want if d not in DOORS]
    if unknown:
        return _fail(f"no such door: {unknown}", fix=f"Pick from: {sorted(DOORS)}")

    # Sizing always spends the seller tier, so preflight it alongside whichever
    # discovery tiers were asked for.
    tiers = {DOORS[d]["tier"] for d in want} | {"etsy_private"}
    blocked = _preflight(tuple(sorted(tiers)))
    if blocked:
        return blocked

    out = _scout(seed.strip(), sources=tuple(want), mode=mode,
                size_mode=size_mode, limit=limit)
    return _ok({"operation": "scout", **out})


@mcp.tool()
@_guarded
def keyword_crawl(
    operation: Annotated[CrawlOp, Field(description=_OP_DOC)],
    seed: str,
    max_nodes: int = 60,
    max_depth: int = 2,
    min_ratio: float = 0.25,
    want_pockets: int = 12,
    limit: int = 40,
) -> dict:
    """Recursive keyword discovery. SPENDS THE SELLER ACCOUNT — hard-capped, reports spend."""
    if not seed or not seed.strip():
        return _fail("`seed` is required", fix="Pass one keyword to expand from.")

    # Refuse rather than clamp. A silent clamp is worse than an error here: the
    # agent believes it saw the whole neighbourhood when it saw a slice.
    if max_nodes > MAX_NODES:
        return _fail(
            f"max_nodes={max_nodes} exceeds the ceiling of {MAX_NODES}",
            fix=f"This crawl authenticates as the operator's own Etsy SELLER "
                f"account (D-29), which cannot be replaced. Ask for "
                f"{MAX_NODES} or fewer, or run several smaller crawls — the "
                f"30-day cache makes overlapping ones nearly free.")
    if max_depth > MAX_DEPTH:
        return _fail(
            f"max_depth={max_depth} exceeds the ceiling of {MAX_DEPTH}",
            fix=f"Depth is where cost explodes: each level multiplies "
                f"expansions. Crawl at depth {MAX_DEPTH}, then re-seed from a "
                f"pocket you actually care about.")

    blocked = _preflight(("etsy_private",))
    if blocked:
        return blocked

    from etsy.analytics import keyword_crawl as kc
    from etsy.api.private.api import EtsyPrivateAPI, SessionDown

    budgeted = _Budgeted(EtsyPrivateAPI(), MAX_EXPANSIONS, AGENT_ITERATIONS)
    collected = []
    stopped = "frontier exhausted"

    def on_node(node):
        collected.append(node)
        # Adaptive stop: the question is "are there winnable pockets here", and
        # once enough are found, more requests do not improve the answer.
        if operation == "crawl":
            good = [n for n in collected
                    if (n.get("demand_per_listing") or 0) >= min_ratio]
            if len(good) >= want_pockets:
                raise _EnoughFound()

    try:
        nodes = kc.crawl(budgeted, seed,
                         # A drill pays for ONE expansion and every child arrives in
                         # that same response, so capping the node count buys nothing
                         # and costs coverage. At the default 60 a live drill of
                         # `badge reel` kept 59 of the 173 edges Etsy returned and
                         # reported 59 as though that were the whole neighbourhood —
                         # a silent cap presenting a slice as the answer.
                         max_nodes=(MAX_NODES if operation == "drill"
                                    else min(max_nodes, MAX_NODES)),
                         max_depth=1 if operation in ("expand_seed", "drill")
                                   else min(max_depth, MAX_DEPTH),
                         on_node=on_node)
    except _BudgetSpent:
        nodes, stopped = collected, "request budget spent"
    except _EnoughFound:
        nodes, stopped = collected, f"found {want_pockets} winnable pockets — enough to answer"
    except SessionDown as e:
        return _fail(f"SessionDown: {e}",
                     fix="The SELLER session is stale. Open Chrome with the "
                         "extension on a Shop Manager tab, then: "
                         "python -m core.vault_status",
                     spent={"expansions": budgeted.expansions})

    if operation == "drill":
        # ONE level down from one term, and every child returned with its own
        # numbers instead of just its name.
        #
        # `expand_seed` already fetched exactly this and then threw the
        # measurements away — it returns `all_terms`, a flat list of up to 300
        # bare strings — so the sub-niches could not be read, ranked, or chosen
        # between. The data was already paid for.
        #
        # Rows come back in the SAME shape `compare` emits, on purpose: the
        # output of a drill is a valid input to another drill, so the operator
        # can keep going down without learning a second format at each level.
        #
        # ⚠️ Free per child. `get_similar_keywords` returns 120-165 children each
        # already carrying volume and supply, so ranking them costs NO extra
        # call. Verified same-unit as results-data: `personalized gift` reads
        # 234,622/615,194 = 0.381 from the expansion and 226,574/591,082 = 0.383
        # live — so these ratios are comparable with every other table here.
        kids = [n for n in nodes if (n.get("term") or "").lower() != seed.lower()]
        kids.sort(key=lambda n: (n.get("demand_per_listing") is None,
                                 -(n.get("demand_per_listing") or 0)))
        rows = [{"term": n["term"], "volume": n.get("volume"),
                 "supply": n.get("supply"),
                 "demand_per_listing": n.get("demand_per_listing"),
                 "winnability": n.get("verdict"),
                 "verdict": n.get("verdict"),
                 "why": (n.get("winnability") or {}).get("reason"),
                 "basis": (n.get("winnability") or {}).get("basis"),
                 "phrase_words": len((n.get("term") or "").split()),
                 "supply_basis": (n.get("winnability") or {}).get("supply_basis"),
                 "parent": n.get("parent") or seed,
                 "depth": n.get("depth")} for n in kids[:limit]]
        by = {}
        for n in kids:
            by[n.get("verdict")] = by.get(n.get("verdict"), 0) + 1
        return _ok({
            "operation": operation, "parent": seed,
            "rows": rows, "returned": len(rows), "children_found": len(kids),
            # `returned` is what this call shows, `children_found` is what Etsy
            # actually offered. Reporting only the first would read as coverage.
            "truncated_by_limit": max(0, len(kids) - len(rows)),
            "node_ceiling": MAX_NODES,
            "hit_node_ceiling": len(kids) + 1 >= MAX_NODES,
            "breakdown": by,
            "spent": {"expansions": budgeted.expansions,
                      "private_requests_upper_bound":
                          budgeted.expansions * REQUESTS_PER_EXPANSION,
                      "basis": "BOUND — get_similar_keywords caches 30 days, so a "
                               "re-drill of the same term spends 0"},
            "stopped_because": stopped,
            "drill_next": "Any `term` in `rows` can be drilled again with "
                          "operation='drill' — the rows are the same shape going "
                          "in as coming out.",
            "basis": "measured — every child carries volume and supply from Etsy's "
                     "own expansion, no extra call per term; same ~30-day unit as "
                     "results-data",
            "note": "⚠️ Children are LONGER phrases than the parent, and `supply` is "
                    "a BROAD-match count, so each level down is pushed toward `wall` "
                    "by construction rather than by the market. Read `phrase_words` "
                    "and compare a child against its SIBLINGS, not against the "
                    "one-word head terms in `compare`. "
                    "Sorted by demand-per-listing (D-31), never volume. A term with "
                    "no volume sorts LAST because it cannot be compared, not "
                    "because it is worst (N-02). All-walls is a real finding: it "
                    "says this branch is saturated all the way down, and the answer "
                    "is to drill a different parent, not deeper here.",
        })

    pockets = kc.pockets(nodes, min_ratio=min_ratio)
    summary = kc.summary(nodes)
    spent = budgeted.expansions
    return _ok({
        "operation": operation,
        "seed": seed,
        "summary": summary,
        "pockets": pockets[:50],
        "pocket_count": len(pockets),
        "all_terms": [n["term"] for n in nodes][:300],
        "spent": {
            "expansions": spent,
            "expansions_remaining": max(0, MAX_EXPANSIONS - spent),
            # An UPPER BOUND, never a count. get_similar_keywords is cached for
            # 30 days, so an expansion of an already-crawled keyword costs ZERO
            # network requests — observed live: a 40-term crawl of `felt garland`
            # returned in under a second having spent nothing. Reporting the
            # derived figure as if it were a measurement would be exactly the
            # plausible-wrong-number this project guards against (Rule 3: bounds
            # are labelled as bounds).
            "private_requests_upper_bound": spent * REQUESTS_PER_EXPANSION,
            "basis": "expansions are MEASURED exactly; the request figure is a "
                     "BOUND at ~10 per expansion (3 enqueues + ~2.3 polls). A "
                     "cached expansion spends 0 — the true cost is between 0 and "
                     "this bound, and a fast return means the cache served it.",
        },
        "stopped_because": stopped,
        "note": (
            "POCKETS are the answer, not the term count. A crawl that finds 200 "
            "terms and 0 pockets has told you the neighbourhood is a wall all the "
            "way down — that is a real finding, not a failed run. Terms are "
            "recorded even when they are walls, because pruning decides where to "
            "LOOK, never what to REPORT."
        ),
        "basis": "measured (each edge carries its own volume and supply from "
                 "Etsy's own expansion endpoint — no extra call per term)",
    })

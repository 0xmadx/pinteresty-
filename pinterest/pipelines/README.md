# Pinterest pipelines

Four runnable scripts. Each is a thin script over [`PinterestTrendsAPI`](../endpoints/api.py) —
no logic of its own beyond sequencing calls and writing a JSON dump to [`pinterest/data/`](../data/).
For the standalone products (keyword research, ad targeting, alerts…) see
[`../products/README.md`](../products/README.md) instead — these four are the Etsy-facing pillar,
not the Pure Pinterest reading.

```bash
.venv/Scripts/python.exe pinterest/pipelines/scrape_search.py
.venv/Scripts/python.exe pinterest/pipelines/scrape_shopping.py
.venv/Scripts/python.exe pinterest/pipelines/scrape_spotlight.py
.venv/Scripts/python.exe pinterest/pipelines/pin_graph_pipeline.py --depth 2 --max-nodes 20
```

## [`scrape_search.py`](scrape_search.py) — discovery → curves → demographics → expansion

The four-step waterfall from [README §1](../README.md#1-the-pattern--every-surface-is-the-same-three-step-waterfall),
run once and dumped:

1. `top_trends()` on one preset (default `growing`) — the ranked table
2. `metrics()` for **every** row from step 1, batched in one call — never one term at a time
3. `demographics()` for the top-ranked term only
4. `prefix_match()` + `related_terms()` on that same term — the expansion step

Output: `data/search_pipeline_output.json` — `{metadata, discovery, metrics, demographics,
expansion_prefix, expansion_related}`. `end_date` always comes from `latest_available_date()`,
never hardcoded.

## [`scrape_shopping.py`](scrape_shopping.py) — full taxonomy → ranking → curves → Etsy scan

1. `product_categories()` — the 383-entry taxonomy, fetched once
2. `top_categories()` — **the entire ranking in one call** (44 rows on `OUTBOUND_CLICK`), not the
   UI's paginated 20
3. `category_metrics()` for the top 20 ranked categories, 180-day curves
4. `etsy_competitors()` swept over the top N (default 5) — the merchant filter that bridges this
   pillar back to Etsy listing titles

Output: `data/shopping_pipeline_output.json` — `{metadata, ranking, metrics, etsy_competitors}`.

## [`scrape_spotlight.py`](scrape_spotlight.py) — every editorial macro trend

Sweeps all 15 dropdown options in `constants.SPOTLIGHT_INTERESTS` (the "All" + 14 named
interests + the Fashion triple) through `featured_topics()`. `PinterestTrendsAPI` enforces the
one-id-or-Fashion-triple-or-None rule itself, so this never 400s or 500s regardless of which
option is swept.

Output: `data/spotlight_pipeline_output.json` — `{<label>: [5 topics each]}`.

## [`pin_graph_pipeline.py`](pin_graph_pipeline.py) — the BFS crawler

The free, wide funnel that decides where Etsy's metered quota gets spent. Mirrors
[`private/pipelines/ssr_graph_pipeline.py`](../../private/pipelines/ssr_graph_pipeline.py) and
shares its [`GraphDB`](../../core/graph_db.py) frontier contract, but runs far deeper — Etsy
costs a quota unit per node, Pinterest costs nothing.

```bash
.venv/Scripts/python.exe pinterest/pipelines/pin_graph_pipeline.py --depth 2 --max-nodes 20 --presets growing seasonal
```

**Flow:**

1. `seed()` sweeps the discovery table per preset (`top_trends`) and pushes every row onto the
   shared frontier tagged `source="pinterest"`
2. `expand()` on each popped node calls both `related_terms()` and `prefix_match()`, writes
   weighted edges (`kind="related"` / `"prefix"`, weight = the child's most recent level), and
   pushes unvisited children onto the frontier up to `--depth`
3. `flush()` batches curves for up to 50 pending nodes per `/metrics/` call, **at `days=365`**
   — not because a shorter window is needed, but because 365 is the same single request that
   lands as an *exact* series in the [series store](../endpoints/series_store.py) and carries
   `growth_rates`, which do not reproduce from raw counts (see
   [`local_math.py`](../endpoints/local_math.py)). The console line `N local, M fetched` is the
   store paying off — see [README §7.3](../README.md#73-doing-it-locally--what-replaces-a-request).

Terms discovered via `related_terms`/`prefix_match` (the overwhelming majority of the frontier)
never reach `/metrics/` at all: their series already rode along in the expansion response and the
store served them for free.

**Node/edge schema:** `node_from_row()` maps a discovery-table row to a graph node
(`term_id`, `search_count`, `seasonality_score`, `mom_change`/`yoy_change`/`wow_value` — all run
through `clamp_change()` so the "10,000%+" sentinel can never poison an average). Nodes reached
only via expansion (no discovery row) get a bare node with no stats until `flush()` patches in
`search_count` and `series_json` via `update_node` (not `add_node` — that would blank the
discovery-time stats already written).

Verified live: 17 nodes, 153 edges (99 prefix / 54 related), 241 queued on a depth-2, 20-node run.

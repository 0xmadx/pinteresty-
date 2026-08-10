# Pinterest — master index

One page to orient from. Everything in `pinterest/` reads live data from
`trends.pinterest.com` through a single client, [`endpoints/api.py`](endpoints/api.py)
(`PinterestTrendsAPI`), and then splits into two independent readings of that same data:

```
                              PinterestTrendsAPI
                          (endpoints/, cache + series store)
                                     │
                 ┌───────────────────┴───────────────────┐
                 │                                        │
         pipelines/                                  products/
   Pinterest AS FUNNEL                          Pinterest AS ITS OWN PRODUCT
   feeds the Etsy scoring model                  nothing routed back to Etsy
   (README §7)                                   (README §9)
```

Nothing in `products/` imports from `public/`, `private/` or `core/`. Nothing in `pipelines/`
exists without the Etsy side — it's the free BFS crawler that decides where Etsy's metered quota
gets spent. Both sides share the same client, cache, series store and local-math layer.

## Where to read next

| I want to... | Go to |
|---|---|
| Understand what Pinterest's API actually returns, endpoint by endpoint | [`endpoints/overviews.md`](endpoints/overviews.md) — the protocol reference |
| Work with the client library code (`api.py`, `constants.py`, series store, local math) | [`endpoints/README.md`](endpoints/README.md) |
| Understand how Pinterest feeds the **Etsy** scoring model, and the discovery→expand→score→spend funnel | [`README.md`](README.md) §§1–8 |
| Run one of the four Etsy-facing pipeline scripts | [`pipelines/README.md`](pipelines/README.md) |
| Use Pinterest as its **own** product — keyword research, ad targeting, content calendar, alerts... | [`products/README.md`](products/README.md), or [`README.md`](README.md) §9 for the summary + measured findings |
| See what's been verified live and what's still open | [Verification](#verification) and [Open questions](#open-questions) below |

## Directory map

```
pinterest/
├── endpoints/            the client library — see endpoints/README.md
│   ├── api.py              PinterestTrendsAPI — one method per endpoint, cache-first
│   ├── constants.py        interests, moments, presets, enums — all measured, not guessed
│   ├── series_store.py     harvests free series out of related/prefix, serves /metrics/ locally
│   ├── local_math.py       derivations that replace a request with arithmetic
│   ├── overviews.md        the protocol reference — endpoint-by-endpoint teardown
│   └── (raw DevTools captures the docs were extracted from)
├── pipelines/             Etsy-facing — Pinterest as the funnel. See pipelines/README.md
│   ├── scrape_search.py    discovery → curves → demographics → expansion
│   ├── scrape_shopping.py  taxonomy → full ranking → curves → Etsy competitor scan
│   ├── scrape_spotlight.py every editorial macro trend, 15 dropdown options swept
│   └── pin_graph_pipeline.py   the BFS crawler feeding core/graph_db.py
├── products/              standalone — Pinterest as its own product. See products/README.md
│   ├── keyword_research.py     1 — content research for any niche
│   ├── content_calendar.py     2 — dated publishing plan + .ics export
│   ├── ad_targeting.py         3 — Pinterest Ads interest/demographic research
│   ├── market_intel.py         4 — merchant share + the 383-node taxonomy
│   ├── history.py              5 — the weekly archive Pinterest itself doesn't offer
│   ├── audience.py             6 — who searches a term, by age and gender
│   ├── moodboard.py            7 — visual trend briefs with colour palettes
│   ├── alerts.py               8 — week-over-week momentum feed
│   └── cli.py                  one entry point for all eight
├── tests/                 live verification — nothing here is asserted from memory
├── data/                  cache/, series.db, history.db, and every pipeline's JSON dump
└── core/ (outside this tree: client.py, cookie_server.py, extract_cookie.py — cookie sync)
```

## Verification

Five suites, all live against the real API, none of it asserted from memory:

```bash
.venv/Scripts/python.exe pinterest/tests/test_live_endpoints.py        # 46 — flat REST + discovery
.venv/Scripts/python.exe pinterest/tests/test_shopping_endpoints.py    # 50 — shopping stack
.venv/Scripts/python.exe pinterest/tests/test_spotlight_moments.py     # 39 — spotlight + moments
.venv/Scripts/python.exe pinterest/tests/test_local_derivations.py     # 17 — series store + local math
.venv/Scripts/python.exe pinterest/tests/test_products.py              # 54 — the eight standalone products
```

**206 checks total.** Each suite exits non-zero and names the broken claim if Pinterest changes
a shape underneath it — the canary for drift, not a one-time sanity check. Two supporting scripts:
`audit_capture_coverage.py` (flags anything the docs don't mention across all 8 raw capture
files) and `backfill_series_store.py` (one-off: replays existing cache into the series store).

## What's been confirmed against the live Pinterest UI, not just the API

Two claims that matter enough to call out here rather than bury in a section doc — both checked
directly in a live, logged-in Pinterest session on 2026-08-07, not inferred from response shapes:

- **The 24 interest ids in `constants.INTERESTS` are the real Pinterest Ads targeting ids** —
  confirmed in Ads Manager's own campaign-setup interest picker, name-for-name and id-for-id.
- **UK moment timing genuinely does not exist**, not just in this client — `GB+IE` returns every
  date field null from the API, and Pinterest's own `/moments/<name>/` page is US-only and
  redirects away if you switch its region selector. The gap is upstream of this codebase.

## Open questions

Carried from [`README.md`](README.md#open-questions) — nothing here blocks current functionality:

- Is `related_terms`'s edge weighted by anything beyond the child's raw level? Proposal:
  correlate the two terms' 52-week series — computable from data already fetched.
- Shopping pagination (`page=1` in the nav state) has never been exercised.
- Which of the 383 categories have Etsy presence at all? One sweep of `etsy_competitors()`
  across every category answers it, ~383 cached calls, no quota.
- Two items still open from the Etsy-facing side: stripping `client_context` PII from
  `data/*_pipeline_output.json` dumps, and wiring the ranked Pinterest corpus into the Etsy
  scoring/listing pipeline (the "join pipeline").

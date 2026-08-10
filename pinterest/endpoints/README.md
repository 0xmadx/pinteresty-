# `pinterest/endpoints/` — the client library

This folder has two layers, and they answer different questions:

- **The protocol reference** — [`overviews.md`](overviews.md). What Pinterest's API actually
  does: transport, auth, every endpoint's params and response shape, the node/edge schema, all
  extracted from the raw DevTools captures below it. Read this when you need to know what a
  request or response *contains*.
- **This file** — what's actually in the code, and how the four modules fit together. Read this
  when you're calling or extending `PinterestTrendsAPI` and want the load-bearing behaviors
  without re-deriving them from `overviews.md`.

Both are pinned by live tests, not written from memory — see [Verification](#verification).

## The four modules

### [`api.py`](api.py) — `PinterestTrendsAPI`

Cache-first client, one method per endpoint, mirroring the shape of `EtsyPrivateAPI`/
`EtsyPublicAPI`. `__init__(self, cache=True, delay=0.6, store=True)`:

- Every response is written to `pinterest/data/cache/*.json` and read back before any request —
  `cache=False` forces the wire (used by tests that need ground truth).
- `delay` is a flat `time.sleep()` before every request; Pinterest has no quota but does
  rate-limit.
- `store=True` wires in the [series store](#series_storepy--the-thing-that-turns-requests-into-local-lookups) —
  set `False` to force every series onto the wire regardless of what's already cached locally.

Methods, grouped by what they cost:

| No live cost once cached | Costs a request every call |
|---|---|
| `latest_available_date()` | `top_trends(preset, ..., limit=None)` — discovery table, `limit` up to **100** (server ceiling; UI never sends more than 50) |
| `product_categories()` | `metrics(terms, days, ...)` — batched curves, up to ~50 terms/call, served from the store first when possible |
| `moments_calendar(country)` | `related_terms()` / `prefix_match()` — expansion, both auto-harvest their series into the store |
| | `demographics()`, `top_categories()`, `category_metrics()`, `category_demographics()`, `top_products()`, `featured_topics()`, `editorial_content()` |

`etsy_competitors(category_id, ...)` is a pure filter over `top_products()` (`merchant_name ==
"Etsy"`), not a separate call.

**Guardrails baked into the client rather than left to the caller:** `_check_region()` (shopping
only accepts `US`/`CA`/`GB+IE`), `_check_not_vertical()` (the 14 level-1 vertical ids 400 if
passed as a `product_category_id`), and range checks on `days`, `predicted_days`, `limit` and
`order_by` — all raise `ValueError` locally rather than spending a request to learn the server
would have 400'd.

### [`constants.py`](constants.py) — static vocabulary

Hardcoded rather than fetched (`available_interests` returns `null` on this account). Everything
here was measured against the live API, not guessed:

- `INTERESTS` (24 ids) — **confirmed identical to Pinterest Ads Manager's interest-targeting ids**
  (2026-08-07, checked directly in Ads Manager campaign setup). Ads Manager also exposes a second
  layer of 3–28 sub-interests per top-level id that Trends never surfaces.
- `MOMENTS_US/CA/GB_IE/DE` — cached per-region vocabularies; call `moments_calendar()` for the
  authoritative live set, since an out-of-vocabulary `moments=` value 400s rather than returning
  empty.
- `MOMENTS_DATED_REGIONS` / `_PARTIAL_REGIONS` / `_UNDATED_REGIONS` — which regions' moments
  actually carry `takeoff_ms`/`peak_ms`. Single-country codes are fully dated; three grouped codes
  (`DE+AT+CH`, `AU+NZ`, `MX+AR+CO+CL`) get exactly one peak-only moment; four more (`GB+IE` among
  them) are entirely undated. **There is no way to get UK moment timing at all** — `GB` and `IE`
  both 400 standalone, and confirmed against the live `/moments/` page too: it's US-only and
  redirects away if you switch its region.
- `PRESETS`, `SEASONAL_SCORE_FLOOR`, `CHANGE_CAP_SENTINEL`, `TOP_TRENDS_LIMIT_MAX` (100),
  `TOP_LIMIT_MAX` (522, shopping-side), age/gender enums in both the flat-REST and Ads spellings.

`clamp_change(value)` turns the UI's "10,000%+" sentinel (`100.01`) into `None` so it can never
poison an average — used everywhere a `mom_change`/`yoy_change`/`wow_change` gets aggregated.

### [`series_store.py`](series_store.py) — the thing that turns requests into local lookups

`related_terms()` and `prefix_match()` already hand back a full weekly series for every term they
suggest; without this store that series was discarded and the same numbers re-bought from
`/metrics/`. `class SeriesStore(db_path=...)` — SQLite at `pinterest/data/series.db`.

Provenance is ranked so a lower-quality series can never silently overwrite a better one:

```
RANK = {"metrics": 3, "related": 3, "prefix": 1}   # related is byte-identical to metrics
```

`put()` refuses to downgrade — an approximate `prefix` series never overwrites an exact one, and a
shorter series never overwrites a longer one. `get(term, days, ...)` returns `{counts, source,
precision, growth}` or `None` (never guesses); when a caller asks for a window shorter than
what's stored, `slice_window()` **renormalizes** the tail to its own peak rather than truncating —
Pinterest scales every window to 100 at its own maximum, so a naive tail slice is off by the ratio
between the two peaks. Below `MIN_SLICE_PEAK=25` the store refuses to serve at all: the source's
own rounding to integers has already destroyed enough precision that even a correct renormalization
can't recover it.

### [`local_math.py`](local_math.py) — derivations that replace a request with arithmetic

Every function here was verified against the live API before being written down, and the module
docstring records what is **NOT** derivable (`seasonality_score`, `growth_rates`,
demographics/forecasts/`top_products`) with the same weight as what is — the negative results
matter because a broken derivation returns a plausible number instead of an error.

| Derivable, no request | Function |
|---|---|
| All three event summaries from one `/top/` call | `event_summary()`, `intent_ratio()` |
| Both `order_by` orderings (they're both present in every row) | `resort()` — ties break on ascending category id, or the local order diverges from the API's |
| Launch dates from the moments calendar | `launch_plan()`, `calendar()` — subtraction, not an endpoint. `_drift()` only reports a delta when the two timestamps really are ~1 year apart (guards against a fake `-365d` on regions/moments where Pinterest echoes the same value into both blocks) |
| Momentum on a bare `counts[]` (no `growth_rates` attached) | `velocity()` — **our own** measure, not a reconstruction of the API's `growth_rates`, which do not reproduce from point-to-point deltas on rounded counts |

## Verification

```bash
.venv/Scripts/python.exe pinterest/tests/test_live_endpoints.py        # 46 checks — flat REST + discovery
.venv/Scripts/python.exe pinterest/tests/test_shopping_endpoints.py    # 50 checks — shopping stack
.venv/Scripts/python.exe pinterest/tests/test_spotlight_moments.py     # 39 checks — spotlight + moments
.venv/Scripts/python.exe pinterest/tests/test_local_derivations.py     # 17 checks — series_store + local_math
```

**152 live checks across four suites**, each one run against the real API rather than asserted
from memory — see [`../README.md`](../README.md) for the full verification banner including the
products-layer suite. `audit_capture_coverage.py` separately inventories every request URL,
param, payload key and `endpoint_name` across the 8 raw capture files below and flags anything
this documentation doesn't mention:

```bash
.venv/Scripts/python.exe pinterest/tests/audit_capture_coverage.py
```

## The raw captures

`Search trends/`, `shooping trending/`, `trends in the spothlight/` hold the original DevTools
exports `overviews.md` was extracted from — treat them as source material, not documentation;
`overviews.md` and this file are the documentation. `request look like .bash` is a handful of
example curl-shaped requests kept for quick reference.

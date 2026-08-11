# 06 — Stack & Dependencies

*What is actually imported today (with installed versions), what each dependency
earns its place for, and the justified target stack. Measured, not declared.*

Environment: **Python 3.14.6**, virtualenv at `.venv/`.
Third-party imports extracted by AST across all 59 modules.

---

## Declared vs actually used

`requirements.txt` is wrong in **both** directions — it declares seven packages
nothing imports, and omits four that the system cannot run without.

| Package | In `requirements.txt` | Installed | Files importing it | Verdict |
|---|---|---|---|---|
| `curl_cffi` | ✅ `>=0.7.0` | 0.16.0 | **1** — `core/session_manager.py` | **keep** — the transport |
| `beautifulsoup4` | ✅ `>=4.12.0` | 4.15.0 | **4** | **keep** — all HTML parsing |
| `python-dotenv` | ✅ `>=1.0.0` | 1.2.2 | **4** | **keep** |
| `pydantic` | ✅ `>=2.0.0` | 2.13.4 | **1** — `core/cookie_server.py` | **keep** — and should be used far more (config validation) |
| `httpx` | ❌ **undeclared** | 0.28.1 | **6** — all of `pinterest/` | ⚠️ **add** — the entire Pinterest transport is undeclared |
| `fastapi` | ❌ **undeclared** | 0.141.1 | **2** — both cookie servers | ⚠️ **add** |
| `uvicorn` | ❌ **undeclared** | 0.52.1 | **2** | ⚠️ **add** |
| `requests` | ❌ **undeclared** | 2.34.2 | **1** — `core/llm_client.py` | ⚠️ **add**, or switch that one call to `httpx` and drop it |
| `lxml` | ✅ `>=5.0.0` | 6.1.1 | **0** | **remove** — every parser call passes `'html.parser'` explicitly (`api.py:97`, `shop_scraper.py:41`, `listing_api.py:100`) |
| `pandas` | ✅ `>=2.1.0` | 3.0.5 | **0** | **remove for now** — see below |
| `numpy` | ✅ `>=1.26.0` | 2.5.1 | **0** | **remove for now** — see below |
| `plotly` | ✅ `>=5.18.0` | 6.9.0 | **0** | **remove** — nothing plots; `moodboard.to_html` hand-writes HTML (`:130`) |
| `playwright` | ✅ `>=1.40.0` | 1.62.0 | **0** | 🚫 **remove — prohibited** |
| `playwright-stealth` | ✅ `>=1.0.6` | 2.0.3 | **0** | 🚫 **remove — prohibited** |
| `capsolver` | ✅ `>=1.0.0` | 1.0.7 | **0** | 🚫 **remove** |
| `streamlit` | ❌ undeclared | 1.61.1 | **0** | **remove or declare** — installed, unused, unexplained |

### The prohibited three

`playwright`, `playwright-stealth` and `capsolver` are declared, installed, and
**imported by nothing**. `core/settings.py:31-45` still carries live config for that
dead path:

| Setting | Line | Points at |
|---|---|---|
| `CHROME_EXECUTABLE_PATH` | `:32` | a hardcoded Chrome SxS path |
| `CHROME_USER_DATA_DIR` | `:34` | `C:\Users\0xdevy\Desktop\eso esty\data\chrome_profile` — **a different directory than this repo** |
| `COOKIE_REFRESH_INTERVAL` | `:37` | 3600s "between playwright runs" |
| `PLAYWRIGHT_HEADLESS` | `:44` | `False`, "to solve Captcha/DataDome" |
| `PLAYWRIGHT_TIMEOUT` | `:45` | 60000ms, "wait for user to solve challenge" |
| `CAPSOLVER_API_KEY` | `:11` | a CAPTCHA-solving service |

**Recommendation: delete the dependencies and delete the config.** Not implement
them. Session synchronization already has a working owner —
`core/cookie_server.py` receiving from `chrome_extension/background.js` — and that
is the only mechanism this project uses. This entry exists to record that the
config describes a path that does not exist in code, so nobody restores it by
mistake.

*(No change to the access layer is proposed or performed here. Removing an unused
declaration from `requirements.txt` is dependency hygiene, not a modification of
session-handling code — and it is the operator's call, not this pass's.)*

### On pandas and numpy

They are declared, installed, and unimported. But unlike the prohibited three, they
are the **correct** tools for this system at the next step: D-07
(`DECISION_LOG.md:76-84`) names pandas/numpy as the in-process compute layer, and
the analysis layer that will need them (`profit.py`, `scoring.py` with percentile
normalization per D-02) has not been written yet.

**Recommendation:** move them out of `requirements.txt` now and add them back in the
same commit that introduces `analysis/scoring.py`. A dependency that is declared
before its first import is indistinguishable from one that is dead.

---

## Real scale — measured

| What | Size |
|---|---|
| `market_intelligence.db` | 28 KB, **0 rows** |
| `etsy/data/graph/graph.db` | 300 KB — 25 nodes, 252 edges, 304 frontier |
| `pinterest/data/series.db` | 128 KB — 354 rows |
| `pinterest/data/history.db` | 132 KB — 600 rows |
| `pinterest/data/` total (incl. 160 cache files) | **3.3 MB** |
| `etsy/data/` total | **304 KB** — `cache/` and `reports/` are **empty (0 files)** |
| **Everything** | **< 4 MB** |

The design documents assume "megabytes". The measured reality is **single-digit
megabytes**, one operator, weekly batches. Even the documents' own modest scale
assumption is an order of magnitude too generous.

That `etsy/data/cache/` and `etsy/data/reports/` contain zero files is itself a
finding: the Etsy pipelines have never completed a run that produced output.

---

## Target stack

Matched to that measured scale. This is D-07 (`DECISION_LOG.md:76-84`) with the
verification attached.

| Concern | Choice | Why it earns its place | Status |
|---|---|---|---|
| **Transport** | `curl_cffi` (Etsy) + `httpx` (Pinterest) | Already working. `curl_cffi` provides the TLS impersonation the Etsy path needs; `httpx` is fine for Pinterest. | exists |
| **Session sync** | `core/cookie_server.py` ← `chrome_extension/` | The only sanctioned mechanism. **Not to be extended.** | exists |
| **HTML parsing** | `beautifulsoup4` + stdlib `html.parser` | Already the actual behaviour. Drop `lxml` unless a measured parse bottleneck appears — at 4 MB there is none. | exists |
| **Storage (write)** | **SQLite** | Four SQLite stores already work. Zero-ops, single-file, transactional. Nothing here needs more. | exists |
| **Storage (analytical read)** | **DuckDB** — *when needed* | D-07 names it; **not installed**. At 600 total rows, SQLite handles every query. **Defer until a measured slow query exists.** | missing, correctly deferred |
| **Compute** | `pandas` + `numpy`, in-process | Right for percentile normalization (D-02) across a candidate pool. Add with first use. | deferred |
| **Config** | `pydantic-settings` + YAML | `REPO_STRUCTURE_AND_CONFIG.md:96-157` specifies three tiers; today it is a frozen dataclass with hardcoded Windows paths. Pydantic is already installed. | missing |
| **Serving** | `FastAPI` + `uvicorn` | Already installed and already used by the cookie server. Reuse for the read-only Gold API. | partially exists |
| **Testing** | `pytest` | **Not installed.** The Pinterest tests are hand-rolled scripts with a custom `check()` helper. | missing |
| **Packaging** | Docker, one image, two commands | `REPO_STRUCTURE_AND_CONFIG.md:201-222`. For reproducibility, not scale. | missing |
| **Logging** | stdlib `logging`, JSON lines | Currently `print()` everywhere. Blocks all five health questions (`MIGRATION_AND_OPERATIONS.md:118-128`). | missing |

### Explicitly not justified

Per the scale discipline — flagged, not endorsed:

| Tool | Why not |
|---|---|
| Kafka / streaming | `GOAL.md:76` — "Not real-time. Weekly batches are correct." |
| Spark / Dask | 600 rows. pandas handles nine orders of magnitude more. |
| Kubernetes / microservices | One operator, one container. Distribution solves coordination problems this system does not have. |
| Postgres / cloud warehouse | 4 MB. SQLite is not the bottleneck and will not become one. |
| Redis | Nothing needs a shared cache; the file cache is already too *sticky*, not too slow. |
| A graph database | `graph.db` is 25 nodes. SQLite with an `edges` table is already the right answer — `core/graph_db.py:39-50` reached it deliberately. |
| Playwright / any headless browser | 🚫 Prohibited outright. Session sync is the extension's job. |

---

## Dependency hygiene findings

| # | Finding | Location |
|---|---|---|
| **H-1** | No version pinning — every constraint is `>=`, so no two installs are reproducible | `requirements.txt` (all 11 lines) |
| **H-2** | No lockfile, no `pyproject.toml`, no `setup.py` — the project is not installable | repo root |
| **H-3** | Four undeclared runtime dependencies (`httpx`, `fastapi`, `uvicorn`, `requests`) | see table above |
| **H-4** | Seven declared-but-unimported packages, three of them prohibited | see table above |
| **H-5** | Python 3.14 is very new; `__pycache__` shows `cpython-314`. No `python_requires` is declared anywhere, so nothing records this. | — |
| **H-6** | `.venv/` is correctly gitignored (`.gitignore:2`) | ✅ |
| **H-7** | Two HTTP client stacks (`curl_cffi` and `httpx`) with no shared abstraction — a source adapter layer (D-05) would hide this; today it is duplicated transport policy | `core/session_manager.py` vs `pinterest/core/client.py` |
| **H-8** | `core/llm_client.py:2` pulls in `requests` for a single POST, when `httpx` is already a dependency | `core/llm_client.py:46` |

---

## Recommended `requirements.txt`

```
# transport
curl_cffi>=0.16.0,<0.17
httpx>=0.28,<0.29

# parsing
beautifulsoup4>=4.15,<5

# config + serving
pydantic>=2.13,<3
pydantic-settings>=2.0,<3
python-dotenv>=1.2,<2
fastapi>=0.141,<0.142
uvicorn>=0.52,<0.53

# dev
pytest>=8,<9
```

Removed: `lxml`, `pandas`, `numpy`, `plotly`, `playwright`, `playwright-stealth`,
`capsolver`. Added: `httpx`, `fastapi`, `uvicorn`, `pydantic-settings`, `pytest`.
`requests` is dropped by moving `llm_client.py`'s single call to `httpx`.

Add `pandas` and `numpy` back in the commit that first imports them —
`analysis/scoring.py`.

---

*Continue to [07_gaps_and_risks.md](07_gaps_and_risks.md).*

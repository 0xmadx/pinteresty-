# REPO STRUCTURE, CONFIG & SECRETS

*The blueprint describes layers; this says where files actually go, how the system
is configured, and how secrets and PII are handled.*

---

## Repo layout

Folder structure mirrors the architecture, so a file's location tells you which
layer it belongs to and what it's allowed to import.

```
project/
├── docs/                          # all the .md files
│   ├── START_HERE.md              # the index
│   ├── GOAL.md · GLOSSARY.md · DECISION_LOG.md
│   ├── blueprint/                 # 00–07 engineering blueprint
│   └── architecture/              # ← Claude Code's output goes here
│
├── src/
│   ├── sources/                   # LAYER 1 — adapters (the only provider-aware code)
│   │   ├── contracts.py           #   normalized record dataclasses — the spine
│   │   ├── base.py                #   Protocol definitions
│   │   ├── pinterest/             #   one package per provider
│   │   ├── etsy_demand/
│   │   ├── etsy_supply/
│   │   └── middleware/            #   cache · budget · backoff · circuit breaker
│   │
│   ├── ingest/                    # LAYER 2 — Bronze write + the guard boundary
│   │   ├── bronze.py              #   raw persistence
│   │   └── guards.py              #   ⚠️ THE guard boundary — clamp, noisy, freshness
│   │
│   ├── store/                     # LAYER 3 — Silver
│   │   ├── schema.sql
│   │   ├── trends.py · keywords.py · listings.py · shops.py
│   │   ├── ranks.py               #   rank_observations (append-only)
│   │   └── launches.py            #   LEARN (immutable snapshots)
│   │
│   ├── analysis/                  # LAYER 4 — Gold (pure functions, no I/O)
│   │   ├── profit.py              #   ← profit_calculator.py lands here
│   │   ├── scoring.py             #   ← scoring_engine.py lands here (ONE file)
│   │   ├── gaps.py                #   7-dimension search
│   │   ├── platform.py            #   where-to-list
│   │   └── calibration.py         #   LEARN math
│   │
│   ├── pipelines/                 # LAYER 5 — orchestration
│   │   ├── discover.py · validate.py · score.py · learn.py
│   │   └── run.py                 #   the single entry point
│   │
│   ├── api/                       # LAYER 6 — read-only serving
│   │   ├── main.py                #   FastAPI app
│   │   └── routes/                #   reads Gold ONLY
│   │
│   └── config.py                  # settings loading + validation
│
├── tests/
│   ├── unit/ · property/ · integration/ · contract/
│   └── fixtures/                  # real responses, PII stripped
│
├── data/                          # ⚠️ GITIGNORED
│   ├── bronze/                    #   raw archive
│   ├── app.db                     #   SQLite (Silver + Gold)
│   └── cache/
│
├── config/
│   ├── default.yaml               # committed — non-secret defaults
│   └── local.yaml                 # ⚠️ GITIGNORED — operator's real values
│
├── .env                           # ⚠️ GITIGNORED — secrets only
├── .env.example                   # committed — the template
├── docker-compose.yml
└── Dockerfile
```

### The import rule (enforces the architecture)

> Dependencies point **inward**. `analysis/` imports nothing from `sources/`,
> `store/`, or `api/`. It's pure functions over plain data.

| Layer | May import |
|---|---|
| `analysis/` | **nothing** from other layers (pure) |
| `store/` | `analysis/` |
| `ingest/` | `store/`, `sources/contracts` |
| `sources/` | `contracts`, `middleware` |
| `pipelines/` | all of the above |
| `api/` | `store/` (read), `analysis/` |

This is testable — a lint rule or a test that asserts no forbidden import exists.
It's also what makes `analysis/` trivially unit-testable, since it touches no I/O.

---

## Configuration

Three tiers, loaded in order (later overrides earlier):

1. `config/default.yaml` — committed defaults
2. `config/local.yaml` — the operator's real values, gitignored
3. environment variables — deploy-time overrides

Validated with **Pydantic Settings**, so a bad config fails at startup with a clear
message rather than at 3am mid-pipeline.

### `config/default.yaml` — the schema

```yaml
sources:
  demand:  test            # ← swap to etsy_official later
  supply:  test
  trends:  pinterest

budget:
  demand_calls_per_day: 15      # the metered quota
  concurrency: 5                # measured ceiling
  request_delay_seconds: 0.6

cache:
  ttl_days:                     # per-type; NOT one global value
    taxonomy: 90
    moments: 14
    search_volume: 10
    trends_series: 7
    serp_supply: 3
    shop_totals: 1
    rank: 0                     # 0 = never cache
    live_badges: 0

scoring:
  weights_version: 1
  min_pool_size: 2              # below this, percentiles are meaningless
  auto_tune_min_launches: 10    # don't fit 6 weights to 5 outcomes

profit:
  fee_schedule_verified: "2026-01"   # ⚠️ re-check against Etsy's current rates
  listing_fee: 0.20
  transaction_rate: 0.065
  processing_rate: 0.03
  processing_flat: 0.25
  offsite_rate_under_10k: 0.15
  offsite_rate_over_10k: 0.12
  margin_floor:
    digital: 0.70
    physical: 0.35
    personalized: 0.50

operator:                        # → local.yaml; these are personal
  country: US
  hourly_rate: 25
  labor_hours_per_week: 15
  cac_range: [0.0, 8.0]          # organic → paid, modeled as a RANGE

timing:
  lead_weeks: 6
  supplier_lead_weeks: 4         # physical only; digital = 0
```

**Everything the profit model needs is config, not code.** Fee changes are a YAML
edit. The `fee_schedule_verified` date is there so staleness is visible.

---

## Secrets

`.env`, gitignored, loaded via Pydantic Settings. Never in YAML, never committed.

```
# .env.example  (commit this; never commit .env)
PINTEREST_API_KEY=
ETSY_API_KEY=
LLM_API_KEY=
DB_PATH=./data/app.db
```

Rules:
- **No secret in any committed file**, including fixtures and Bronze archives.
- Rotate anything that has ever been committed — git history keeps it.
- Secrets are only read in `sources/*/` and `config.py`. Nothing else needs them.

---

## ⚠️ PII — a known live issue

The Pinterest pipeline dumps in `data/*_pipeline_output.json` currently retain
`client_context`, which carries **account owner name, email, and billing status**
(~63 keys). These are committed.

**Action, in order:**
1. Strip `client_context` at ingest — the guard boundary already should
   (`ingest/guards.py`).
2. Re-dump the existing files stripped.
3. Add `data/` to `.gitignore`.
4. If those dumps were ever committed, the PII is in git history — purge or
   rotate accordingly.

This is a ten-minute task and it's the first item in the build order for a reason.

---

## Docker

Two services, one image, sharing a volume — packaging for **reproducibility**, not
scale.

```yaml
services:
  ingest:                       # scheduled batch work
    build: .
    command: python -m src.pipelines.run
    volumes: [./data:/app/data, ./config:/app/config]
    env_file: .env
  api:                          # always-up read layer
    build: .
    command: uvicorn src.api.main:app --host 0.0.0.0
    volumes: [./data:/app/data, ./config:/app/config]
    env_file: .env
    ports: ["8000:8000"]
```

They never share memory — only the database file. That's the ingestion/serving
separation made physical, and it's the seam that lets serving scale independently
later.

---

## `.gitignore` essentials

```
data/                 # bronze, db, cache — PII risk and huge
config/local.yaml     # operator's real values
.env                  # secrets
__pycache__/ · .pytest_cache/ · *.db · *.db-journal
```

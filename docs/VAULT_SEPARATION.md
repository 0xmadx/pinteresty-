# Vault separation — this project vs pinterest-apify

**The plan, confirmed by the operator: each project owns its full stack —
its own containers, its own Redis, its own database. No sharing.** That has
been the actual state since 2026-08-25. This document keeps the full history
of how it got there — a data-layer mirror first, then a foreign-profile
filter, then full physical separation — because the reasoning and the
incidents along the way are worth keeping even after the mechanism itself is
gone. **As of 2026-08-26 (D-49), the mirror described in most of this
document no longer exists in code.** See the banner below before reading
anything past "Historical context."

## Current state — one project, one database

| | This project | `pinterest-apify` |
|---|---|---|
| Redis | `scraper-redis`, port 6379, **db 0 — the only database this project reads or writes** | `pinterest-redis`, port 6380 — its own container |
| Cookie writer | `cookie-server-go` (this repo's Go server) | its own AdsPower sync (`adspower/sync_cookies.py`) |
| Session capture | Chrome extension only (rule 6 — no browser automation, ever) | AdsPower / remote browsers, per-profile proxies |

Neither project's access layer needed to change to get here — `pinterest-apify`
moved itself onto its own Redis and repointed its own `.env`; this project's
extension, Go server and `docker-compose.yml` are untouched, because the
extension never depended on anything from the other side to begin with.

Verified after their cutover: their 7 `ads_*` session jars, left behind in this
project's db 0, had genuinely stopped being written (checked the same heartbeat
twice — it aged by exactly the wall-clock gap between checks) and were purged.
db 0 is now this project's alone.

## ⚠️ D-49 (2026-08-26) — the internal db-0/db-1 mirror is retired

Everything above this line is still true and current. Everything below —
`core/vault_mirror.py`, the db-1 "private copy," `VAULT_SOURCE_URL`,
`sync_if_stale()`, `separation_check()` — described a **second, narrower**
separation that existed *inside* this project's own Redis container, on top
of the one above: db 0 (written by `go-api`) mirrored one-way into a private
db 1 that everything else in this repo read, so that while `pinterest-apify`
was still sharing db 0, this project's own evictions and prunes could never
reach their sessions and vice versa.

Once the table above became true — `pinterest-apify` on its own Redis
entirely — that inner mirror was defending against a risk that no longer
existed. It was not free to keep: a copy that only refreshes when something
remembers to call `sync_if_stale()`, and that — measured, not assumed —
silently drifts stale between calls. That drift caused three separate
same-symptom incidents this project hit directly (`vault_status` reports
green, a live run 401s minutes later; see `CLAUDE.md`'s session-layer notes),
each traced back to db 1 holding a copy older than db 0's real state. The
clearest measurement: `vault_status` against db 1 reported **0 usable etsy, 0
usable pinterest** — some profiles' last heartbeat over 10 days old — while
the exact same command against db 0 directly, moments later, reported
**1 usable etsy, 2 usable etsy_private, 1 usable pinterest, vault green.**

So `core/vault_mirror.py` and its test file were deleted outright, every
`sync_if_stale()` / `_sync_mirror()` / `separation_check()` call site was
removed, and `REDIS_URL` (code default, `.env`, `.env.example`,
`docker-compose.yml`) now points every service straight at db 0. Full
rationale and the complete list of files touched: `docs/DECISION_LOG.md`
**D-49**.

**What this means for the "Historical context" section below:** every
mechanism it describes — the mirror, `VAULT_SOURCE_URL`, the "refresh before
judging" pattern, `separation_check()`'s `[separated]`/`[MERGED]` printout —
is **removed from the codebase**. Kept here as a record of a real defect
that was found and fixed correctly at the time, and because the underlying
lesson (a copy that nothing refreshes will silently go stale, and a
diagnostic that reads a stale copy will lie about a healthy system) is worth
keeping even once the specific mechanism is gone.

## Historical context — the staged approach that got here

Before full separation, sharing was reduced in two steps: a data-layer mirror
first (this project stopped *reading* the shared store directly), then a
filter against profiles that didn't belong to either side's own capture
method (D-47). Both are described below, exactly as they worked while they
existed.

### The situation, when it was still shared

The Chrome extension, the Go cookie server, the Redis container and
`docker-compose.yml` all belong to **this** repo. The `pinterest-apify` project
was a guest on that infrastructure: it pointed at the same
`redis://localhost:6379/0` and read `cookie:pinterest:*`, written by the same
extension.

That was fine for reading. It was not fine for *managing*, and both projects
managed:

| | did this to the shared store |
|---|---|
| `vault_status.plan_prune` | iterated **all three** platforms and would delete profiles the other project depends on |
| `cookie_vault` | evicts profiles it judges signed-out or stale — on every platform, including theirs |
| pinterest-apify's `mark_blocked` | removes a profile from the pool, silently shrinking ours |

None of that was a bug in either project. It was two owners of one mutable store.

### Stage 1 — what changed, and what deliberately did not (2026-08-19 to 2026-08-26 — NOT current, see D-49 above)

**The write path was untouched.** One browser, one extension, one Go server, writing
to db 0 — because that was the operator's constraint, and because changing it would
have meant editing the extension and the Go server that *both* projects depended on.

What changed, at the time, is that this project stopped **reading** db 0 directly.

```
 THIS DIAGRAM STOPPED BEING TRUE 2026-08-26 (D-49) — kept for history only.
 Today: Chrome ─► extension ─► Go server ─► db 0  ◄── everything in this repo reads THIS directly, live.

 As it worked 2026-08-19 – 2026-08-26:
 Chrome ─► extension ─► Go server ─► db 0  ◄── pinterest-apify read this, at the time
                                       │
                                  (mirror, one-way, read-only source)
                                       ▼
                                     db 1  ◄── everything in this repo read THIS, back then
```

Same Redis server, separate logical database. **Nothing on their side changes at
all** — no config, no code, no restart.

### The guarantees, and where each was enforced

| Guarantee | Enforced by |
|---|---|
| We never wrote to the shared vault | `vault_mirror.sync()` — source client was read-only; a test asserted `src.writes == []` |
| Our evictions could not reach their sessions | our evictions happened in db 1; their data was in db 0 |
| Their retirement could not shrink our pool | the mirror never `srem`'d from our pool; asserted by test |
| Our eviction survived a sync | a locally-evicted profile was only readmitted when the source heartbeat was **strictly newer** — i.e. a real re-login |
| A merged config cannot go unnoticed | `vault_status` printed `[separated]` / `[MERGED]` on every run; `sync()` refused and said so |
| A missing `.env` cannot silently re-merge | `ScraperConfig.REDIS_URL` **defaulted to db 1**, not db 0 |

### The trap the mirror created, and how it was closed

A copy went stale. `HEARTBEAT_MAX_AGE` is 300s, so within five minutes of the last
sync every profile in db 1 read as stale and the vault looked **empty** — while the
extension was beaming perfectly good cookies into db 0.

This was hit immediately: `vault_status` reported `etsy 0 usable / 3 known` on a
completely healthy vault.

So anything that judged db 1 had to refresh it first — `preflight.require()`,
`vault_status.main()`, and each of the three live API client constructors
called `sync_if_stale()` on construction. Even with all of that, the drift
still wasn't fully closed — see the D-49 measurement above — which is a
large part of why it was simpler to remove the second database than to keep
patching the refresh coverage.

### Configuration (historical — no longer set)

`.env` used to carry both of these; only `REDIS_URL` (now pointed at db 0)
remains:

```
VAULT_SOURCE_URL='redis://localhost:6379/0'   # shared; written by the Go server
REDIS_URL='redis://localhost:6379/1'          # ours; nothing else reads it
```

`docker-compose.yml` used to split `go-api` (db 0, the writer) from
`python-scraper`/`etsy-server` (db 1, the private copy). All three now read
`redis://redis:6379/0` — see D-49.

### Which platforms were mirrored, and why all three

`etsy`, `etsy_private` **and** `pinterest` — included because this repo uses
Pinterest momentum itself (the weekly `pinterest_bridge` job). Mirroring meant
holding a separate copy of those sessions rather than sharing the other
project's, so neither side's session management disturbed the other. Now that
the two projects are on physically separate Redis servers, this guarantee is
enforced by the network boundary instead, so nothing needs mirroring.

### Verification (historical)

```
17 assertions   core.test_vault_mirror   (one-way, eviction survival, readmission,
                                          their-retirement-does-not-shrink-us)
1047            whole suite, 0 failures
```

Live: `keyword_sweep` recorded 6/6 terms reading db 1; db 0 pools unchanged; no
lease key ever appeared in db 0.

## Correction, 2026-08-25 — they are a CO-WRITER, not a reader

This document described `pinterest-apify` as a project that *reads* db 0. It does
more than that, and the understatement mattered:

* `adspower/sync_cookies.py` **writes** cookie jars into db 0 as `ads_<user_id>`
* `browsers/identities.py` calls **`sadd` and `srem`** on `valid_profiles:pinterest`
  — it adds and removes members of the shared pool

**Measured 2026-08-25: 7 of the 9 pinterest profiles in our pool were theirs.** This
project was doing its Pinterest work on identities it never captured — different
browsers, different proxies, different exit IPs. A ban earned by their traffic would
have landed in our pool, and vice versa.

### The two projects capture sessions differently, on purpose

| | this project | pinterest-apify |
|---|---|---|
| capture | Chrome extension only | AdsPower / remote browsers, per-profile proxies |
| profile id | `profile_<random>` | `ads_<user_id>` |
| browser automation | **banned** (rule 6) | central to its design |

Neither approach is wrong; they are different projects solving different problems.
**Do not import one's approach into the other.**

### What enforced it (historical — the mirror this filtered no longer exists)

`vault_mirror.FOREIGN_PROFILE_PREFIXES` — anything matching was skipped on the
way in and purged from db 1 on every sync (a rule enforced only on entry would
have left pre-rule copies in the pool forever, since sync never deleted from
the destination). Ownership beat freshness: a foreign jar was excluded even
when its heartbeat was newer than ours.

**db 0 was still never written by this project.** Their jars remained exactly
where they were and their tooling was unaffected — verified after the change:
7 `ads_*` jars still present in db 0, still in their valid pool.

### What this filter alone could NOT fix — why full separation was still needed

The database itself was still one shared Redis. `FOREIGN_PROFILE_PREFIXES` stopped
their sessions entering ours, but it could not stop the reverse: the moment this
project's Chrome extension posted a cookie, it landed in db 0, and anything with
read access to db 0 could read it.

Confirmed the same day this filter shipped: `pinterest-apify` has its own export
path (`browsers/identities.py::export()`) that pulls **every** profile in
`valid_profiles:pinterest`, no ownership check, and writes the raw cookies to a
local JSON file on its own disk. This project's `profile_ldu6ypke8` and
`profile_p5ewxsodn` were found sitting exported there, dated 2026-08-20. The
shared database was never a passive fact — something on the other side actively
read and persisted whatever landed in it.

**A data-layer filter alone could not close that. Only a database the other
project has no credentials to can — the full-separation state described at the
top of this document, which is what made the D-49 mirror retirement safe.**

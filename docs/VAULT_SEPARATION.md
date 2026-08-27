# Vault separation — this project vs pinterest-apify

**The plan, confirmed by the operator: each project owns its full stack —
its own containers, its own Redis, its own database. No sharing.** That is now
the actual state, realized 2026-08-25. This document also keeps the earlier
staged approach (below), because the defenses built along the way still hold
as belt-and-suspenders even though the primary risk they guarded against
(one shared Redis) is gone.

## Current state — full separation

| | This project | `pinterest-apify` |
|---|---|---|
| Redis | `scraper-redis`, port 6379 | `pinterest-redis`, port 6380 — its own container |
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

## Historical context — the staged approach that got here

Before full separation, sharing was reduced in two steps, each documented
because the reasoning and the defenses they built still matter: a data-layer
mirror first (this project stopped *reading* the shared store directly), then a
filter against profiles that didn't belong to either side's own capture method
(D-47). Both are described below, and both remain active — the mirror and the
foreign-profile filter cost nothing to keep, and are the safety net if sharing
of any kind ever resumes.

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

## Stage 1 — what changed, and what deliberately did not

**The write path is untouched.** One browser, one extension, one Go server, writing
to db 0 — because that is the operator's constraint, and because changing it would
mean editing the extension and the Go server that *both* projects depend on.

What changed is that this project stopped **reading** db 0.

```
 Chrome ─► extension ─► Go server ─► db 0  ◄── pinterest-apify reads this, unchanged
                                       │
                                  (mirror, one-way, read-only source)
                                       ▼
                                     db 1  ◄── everything in this repo reads this
```

Same Redis server, separate logical database. **Nothing on their side changes at
all** — no config, no code, no restart.

## The guarantees, and where each is enforced

| Guarantee | Enforced by |
|---|---|
| We never write to the shared vault | `vault_mirror.sync()` — source client is read-only; a test asserts `src.writes == []` |
| Our evictions cannot reach their sessions | our evictions happen in db 1; their data is in db 0 |
| Their retirement cannot shrink our pool | the mirror never `srem`s from our pool; asserted by test |
| Our eviction survives a sync | a locally-evicted profile is only readmitted when the source heartbeat is **strictly newer** — i.e. a real re-login |
| A merged config cannot go unnoticed | `vault_status` prints `[separated]` / `[MERGED]` on every run; `sync()` refuses and says so |
| A missing `.env` cannot silently re-merge | `ScraperConfig.REDIS_URL` **defaults to db 1**, not db 0 |

That last one matters more than it looks. If the default had stayed db 0, an
unloaded `.env` would quietly put us back on the shared store and every guarantee
above would stop holding with nothing failing to announce it.

## The trap the mirror creates, and how it is closed

A copy goes stale. `HEARTBEAT_MAX_AGE` is 300s, so within five minutes of the last
sync every profile in db 1 reads as stale and the vault looks **empty** — while the
extension is beaming perfectly good cookies into db 0.

This was hit immediately: `vault_status` reported `etsy 0 usable / 3 known` on a
completely healthy vault.

So **anything that judges db 1 must refresh it first**:

- `preflight.require()` syncs before checking (non-fatal if the source is down —
  we may hold a perfectly good copy already)
- `vault_status.main()` syncs before reporting, and says so
- `vault_mirror` can be run by hand: `python -m core.vault_mirror`

## Configuration

`.env`:

```
VAULT_SOURCE_URL='redis://localhost:6379/0'   # shared; written by the Go server
REDIS_URL='redis://localhost:6379/1'          # ours; nothing else reads it
```

`docker-compose.yml`:

| service | `REDIS_URL` | why |
|---|---|---|
| `go-api` | `redis://redis:6379/0` | **must stay db 0.** It is the writer, and the other project reads db 0 directly. Pointing it at db 1 starves them while looking fine from here. |
| `python-scraper` | `redis://redis:6379/1` | our private copy |

## Which platforms are mirrored, and why all three

`etsy`, `etsy_private` **and** `pinterest`.

Pinterest is included because this repo uses Pinterest momentum itself — the weekly
`pinterest_bridge` job, which wrote 84 trend observations. Mirroring it means we
hold our *own copy* of those sessions rather than sharing the other project's, so
neither side's session management disturbs the other. That is the separation, not
an exception to it.

## Verification

```
17 assertions   core.test_vault_mirror   (one-way, eviction survival, readmission,
                                          their-retirement-does-not-shrink-us)
1047            whole suite, 0 failures
```

Live: `keyword_sweep` recorded 6/6 terms reading db 1; db 0 pools unchanged; no
lease key ever appeared in db 0.

## If you ever want to undo it

Set `REDIS_URL` back to `redis://localhost:6379/0` in `.env`. `vault_status` will
print `[MERGED]` on every run so the state is never a surprise. Nothing else needs
changing — the mirror simply reports that source and destination are the same and
copies nothing.

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

### What now enforces it

`vault_mirror.FOREIGN_PROFILE_PREFIXES` — anything matching is skipped on the way
in and purged from db 1 on every sync (a rule enforced only on entry would leave
pre-rule copies in the pool for ever, since sync never deletes from the
destination). Ownership beats freshness: a foreign jar is excluded even when its
heartbeat is newer than ours.

**db 0 is still never written by this project.** Their jars remain exactly where
they are and their tooling is unaffected — verified after the change: 7 `ads_*`
jars still present in db 0, still in their valid pool.

### What this filter alone could NOT fix — why full separation was still needed

The database itself was still one shared Redis. `FOREIGN_PROFILE_PREFIXES` stops
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
project has no credentials to can — the full-separation state already described
at the top of this document.**

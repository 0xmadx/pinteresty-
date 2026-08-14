# 10 — The Session Layer (ground truth, 2026-08-14)

Supersedes every earlier description of session sync in `01_system_overview.md`,
`05_module_map.md`, `06_stack_and_deps.md` and the `_old/` set. Those describe a
Python cookie server writing to `.env`. **That is no longer what runs.**

Reconciled from Gemini's `gemini/claude_handoff.md` and then **verified against the
running system** — code, Redis, Docker, and the extension source. Where the handoff
and reality disagree, reality is recorded here and the disagreement is named.

> **Boundary reminder:** everything in this document is **read-only**. It is described
> so pipelines can depend on it correctly. Nothing here may be extended or "fixed" by
> an agent — the defects below are the operator's to resolve.

---

## 1. The shape that actually runs

```
Chrome (human browses Etsy)
   │
   │  chrome_extension/background.js
   │    • cookies.onChanged  → all cookies for the domain
   │    • webRequest hook    → x-csrf-token, shop_id from /shop/(\d+)/
   │    • adds navigator.userAgent + profile_id
   ▼
POST http://localhost:8000/update-cookie      Authorization: Bearer super_secret_key_123
   │
   │  cookie_server_go/main.go   (Docker: cookie-server-go)
   ▼
Redis  (Docker: scraper-redis)                 ← THE VAULT, the single source of truth
   │      HSET  cookie:{platform}:{profile_id}
   │      SADD  valid_profiles:{platform}
   ▼
core/cookie_vault.py  RedisCookieVault.get_valid_account(platform)
   │      SRANDMEMBER → random profile  (this is the "pooling")
   ▼
core/session_manager.py  SessionManager._execute_with_retry()
   │      • curl_cffi Session, impersonate=chrome124
   │      • User-Agent  ← the profile's own UA   (TLS/UA match)
   │      • x-csrf-token ← the profile's csrf     (etsy_private only)
   │      • url.format(shop_id=...) replaces the {shop_id} template
   │      • on 403/429+DataDome → mark_invalid() and retry with another profile
   ▼
Etsy
```

### Three platforms, deliberately segregated

| Redis platform | Auth identity | Used for | Carries |
|---|---|---|---|
| `etsy` | ordinary buyer session | competitor shops, listings, reviews, SERP | cookies, UA |
| `etsy_private` | **the operator's own seller account** | Marketplace Insights only | cookies, UA, `csrf_token`, `shop_id` |
| `pinterest` | pinterest session | trends, moments, demographics | cookies, UA |

---

## 2. The rule this layer exists to enforce (D-29)

**`etsy_private` is the operator's own seller account. It is the scarce, unreplaceable
asset in this system.** A banned buyer session costs a re-login; a banned seller
account costs the business.

Therefore:

1. **Never pass a competitor's `shop_id` into a private endpoint.** The `{shop_id}` in
   a private URL is *whose dashboard we are authenticated as*, not *whose shop we are
   asking about*. Substituting a competitor's id is both wrong and a ban signal.
2. **If a fact is obtainable publicly, it must be obtained publicly.** Private calls
   are reserved for what genuinely requires seller access: search volume, CVR, chart
   series, trending terms, LLM keywords.
3. Competitor shops, listings, reviews and SERP data go through `etsy` — **always**.

| Question | Platform | Why |
|---|---|---|
| How many people search "mom necklace"? | `etsy_private` | only Marketplace Insights knows |
| What is this term's CVR / price band? | `etsy_private` | same |
| What is this competitor selling? | `etsy` | public shop page |
| How many reviews, and when? | `etsy` | public |
| How saturated is the SERP? | `etsy` | public |

---

## 3. Verified state, 2026-08-14 — **the vault is not usable**

Gemini's handoff closes with *"assume the backend scraping engine is stable,
deadlock-free, and handles DataDome perfectly."* The architecture is indeed
deadlock-free — that fix is real and good. **But the vault is empty and no live call
can currently succeed.** Probed directly:

```
redis ping                     → True          (container up 24h)
cookie-server-go               → up 5h, :8000 responding
valid_profiles:etsy            → (missing)     0 profiles
valid_profiles:etsy_private    → (missing)     0 profiles
valid_profiles:pinterest       → (missing)     0 profiles

cookie:etsy:profile_d7u07ruia          is_valid=0  46 cookies  no user_agent  no last_updated
cookie:etsy_private:profile_d7u07ruia  is_valid=0   0 cookies  shop_id=56057851  no csrf_token
```

Read that last line carefully: **the private profile holds a shop_id and nothing else.
Zero cookies, no CSRF token.** It could not have authenticated even when it was marked
valid.

### Root cause — the extension's profile role defaults to `"auto"`, which matches nothing

`chrome_extension/background.js:5` → `let PROFILE_ROLE = "auto";`

That value is then tested against three literals, and falls through every one:

| Path | Test | With role `"auto"` | Effect |
|---|---|---|---|
| cookie sync (`:96`) | `=== 'etsy_private'` / `=== 'etsy_public'` | neither matches → `targetPlatform` stays `'etsy'` | **all cookies land in `etsy`** |
| csrf/shop hook (`:135`) | early-return if `'pinterest'` or `'etsy_public'` | neither matches → proceeds | **shop_id + csrf land in `etsy_private`** |

So the two halves of one seller identity are split across two Redis keys, and the
private profile never receives the cookies that would let it authenticate. This is not
a stale session — **it has never been correct while the role was unset.**

**Operator fix:** open the extension popup and explicitly set the profile role. Then
reload an Etsy Shop Manager page so `cookies.onChanged` and the webRequest hook both
fire against the correct platform.

> ⚠️ One Chrome profile can hold **one** role. A single profile cannot serve both
> `etsy` and `etsy_private`, because the role is a single global. Two roles means two
> Chrome profiles, which is also the correct separation — the buyer session and the
> seller session should not be the same identity.

---

## 4. Defect list (operator-owned — do not let an agent patch these)

| # | Where | Defect | Consequence |
|---|---|---|---|
| **S-1** | `background.js:5` | `PROFILE_ROLE = "auto"` matches no branch | cookies and seller tokens split across platforms; private auth impossible. **This is the current blocker.** |
| **S-2** | `cookie_vault.py:46` | `while not profile_id: sleep(5)` — unbounded | an empty vault makes any pipeline **hang forever** instead of failing. A scheduled job will silently wedge. |
| **S-3** | `background.js:68` vs `:104` | force_sync sends `cookie_json` as a **JSON string**; onChanged sends an **object** | Go re-marshals the string → Python `json.loads` returns `str` → `isinstance(dict)` fails → **zero cookies injected, silently**. The popup's Save button produces an unusable profile. |
| **S-4** | `cookie_vault.py:60` | 5-minute heartbeat purge `SREM`s the profile | correct for freshness, but with S-2 it converts "operator closed Chrome" into "the scheduler is stuck". |
| **S-5** | `main.go:25`, `background.js:180` | API key `super_secret_key_123` hardcoded on both sides | localhost-only today; must not survive the move to a VPS. |
| **S-6** | `session_manager.py:83` | `url.format(shop_id=...)` | works today (all private URLs pre-interpolate their other fields), but any future literal `{` in a URL raises `KeyError`. `.replace()` would be safe. |
| **S-7** | `core/cookie_server.py` | **dead code** — no module imports it | it still writes `.env`, which nothing reads. Two contradictory session mechanisms in one tree invites reviving the wrong one. |
| **S-8** | history | `registry.json` (32 live session cookies) is in git history | **sign out of Etsy** to invalidate. Untracking it did not remove it. |

---

## 5. Failure modes, and how to tell them apart

| Symptom | Meaning | Action |
|---|---|---|
| hangs on `⏳ [Vault] No valid accounts` | vault empty (S-1/S-2) | set the extension role; reload Etsy |
| `401` | session present but not authenticated as a seller | private profile is missing cookies or csrf — S-1 |
| `403` + DataDome text | bot block; profile auto-invalidated, retries with another | if it was the only profile, the vault is now empty |
| `429` | **real throttle** — `SessionManager.rate_limited` counts it | back off. Nothing has ever recorded one. |
| `ValueError: Profile ... is missing shop_id` | a private URL needed a template fill | the profile is not really a seller profile |

**401 ≠ 429 ≠ 403.** They have three different causes and three different fixes;
conflating them is how a session problem gets mistaken for a rate limit.

---

## 6. Deployment

`docker-compose.yml` is the source of truth (Gemini's handoff §6, verified):

| Service | Container | Role |
|---|---|---|
| `redis` | `scraper-redis` | the vault; `--appendonly yes`, volume `redis_data` |
| `go-api` | `cookie-server-go` | `:8000/update-cookie` |
| `python-scraper` | `python-scraper` | the pipelines; mounts `.` at `/app` |

**Paused by decision, do not build:** split buyer/seller extensions, a proxy router,
IP-rotation logic in Python. IP alignment is an infrastructure concern (residential
proxy via `ScraperConfig.PROXY_URL`, or one VPS) — not a Python feature.

---

## 7. What this changes for the pipelines

| Previously documented | Now |
|---|---|
| cookies from `.env`, `load_dotenv(override=True)` before constructing a client | **irrelevant** — cookies come from Redis, fetched per request |
| "restart the cookie server" | "check the vault has a valid profile" |
| one session | a **pool**; a different identity may serve each request |
| `core/cookie_server.py` is the sync | `cookie_server_go/main.go` is the sync |

The one habit worth keeping: **before a long run, check the vault is green.**

```bash
.venv/Scripts/python.exe -m core.vault_status
```

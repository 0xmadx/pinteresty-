# Two fixes only you can make, and the one thing only you can start

Rule 6 puts `core/session_manager.py`, `core/cookie_vault.py`, `cookie_server_go/`
and `chrome_extension/` off limits to an agent. That is the right rule — those four
hold the one asset this system cannot replace. It should not mean you have to work
out the change yourself, so here it is, exact and reviewed.

---

## 1. 🚨 A 429 retires your seller session

### What is wrong

`session_manager.classify()` is written, unit-tested, and **called from nowhere**.
Verified by grepping call sites: the only hits are its own definition and a
docstring. The live loop ignores it and treats every 429 as a block:

```python
# core/session_manager.py:166-181  — CURRENT
is_blocked = response.status_code in (401, 403, 429) and (
    "datadome" in response.text.lower() or
    "geo.captcha-delivery.com" in response.text.lower() or
    response.status_code == 429          # <-- any 429 qualifies
)
if is_blocked:
    ...
    self.vault.mark_invalid(platform, account['profile_id'])   # <-- evicts
```

`mark_invalid` sets `is_valid=0` **and** `srem`s the profile from
`valid_profiles`. On `etsy_private` that profile is your own Etsy seller account
(D-29), and with one seller profile in the pool a single throttle takes the whole
private tier out until Chrome re-beams.

The module's own constants already say this should not happen:

```python
# Only these justify taking a profile out of rotation. A 429 is deliberately NOT
# here: the old code evicted on it, which destroyed a healthy session over a
# timing problem...
EVICTABLE = (AUTH_EXPIRED, BLOCKED)
```

Three documents claimed it was already fixed — `CLAUDE.md`'s facts table, the
decision log, and `session_manager.py:100`'s own docstring (*"Failover is no
longer 'any 401/403/429 burns the profile' — see classify()"*). A docstring inside
the function whose behaviour it misdescribes. Those are corrected now; the code is
not.

### The change

Replace lines **165–184** of `core/session_manager.py` (from the
`# Check for bot block or auth failure` comment through `time.sleep(2)`) with:

```python
            # Route the failure through classify() instead of treating every
            # 401/403/429 alike. EVICTABLE is (AUTH_EXPIRED, BLOCKED) — a 429 means
            # we asked too fast, and a malformed request means WE are wrong; in both
            # cases the session is healthy and evicting it destroys a good profile
            # over a problem it did not cause.
            verdict = classify(response)
            if verdict != OK:
                if verdict == RATE_LIMITED:
                    self.rate_limited += 1
                    print(f"⚠️  RATE LIMITED (429) on {platform} — Etsy throttling. "
                          f"The session is FINE and is NOT being evicted.")
                elif verdict == MALFORMED:
                    print(f"⚠️  Malformed request ({response.status_code}) — OUR bug, "
                          f"not the session. Profile kept.")
                else:
                    print(f"Session failure ({verdict}) on profile "
                          f"{account['profile_id']} "
                          f"(attempt {attempt + 1}/{self.config.MAX_RETRIES}) — evicting.")
                    self.vault.mark_invalid(platform, account['profile_id'])

                # A 429 is usually about rate, not identity, so rotating to another
                # profile and retrying immediately just asks faster. Back off longer.
                time.sleep(8 if verdict == RATE_LIMITED else 2)
            else:
                return response
```

`time` is already imported at module scope (line 2), so the local
`import time` inside the branch can go.

### Why this is a fix and not an extension

It adds no session-handling capability. It routes an existing, already-tested
function into the one branch that was supposed to call it — the behaviour every
doc in the repo already claims. If you would rather not touch the file at all,
the smaller version is to delete `or response.status_code == 429` from the
`is_blocked` expression: that alone stops a throttle evicting anything, and leaves
the malformed case unhandled.

### How to check it worked

```bash
.venv/Scripts/python.exe -m core.test_session_classify
grep -n "classify(" core/session_manager.py    # expect a CALL, not just the def
```

Then afterwards, `CLAUDE.md:194` should be rewritten back to the positive claim —
but only once the code earns it.

---

## 2. 🔑 `super_secret_key_123` on an open port

### What is wrong

```
docker-compose.yml:58            - API_KEY=super_secret_key_123
chrome_extension/background.js:225  'Authorization': 'Bearer super_secret_key_123'
cookie_server_go/main.go:25      apiKey = "super_secret_key_123"   # dev default
docker-compose.yml:51            - "8000:8000"                     # ALL interfaces
```

Both of the first two files are git-tracked and pushed to GitHub. `8000:8000`
binds every interface, not loopback — so anyone on your network who has read the
repo can reach the cookie server with a valid key.

### The change

1. Generate a real key and put it in `.env` (already gitignored):
   ```bash
   python -c "import secrets; print('COOKIE_API_KEY=' + secrets.token_urlsafe(32))" >> .env
   ```
2. `docker-compose.yml:58` → `- API_KEY=${COOKIE_API_KEY}`
3. `docker-compose.yml:51` → `- "127.0.0.1:8000:8000"` (loopback only)
4. `chrome_extension/background.js:225` → read the key from extension storage
   instead of a literal, and set it once in the extension's options.
5. `cookie_server_go/main.go:25` → **refuse to start** without `API_KEY` rather
   than falling back to a default. A dev fallback that ships is a production key.
6. `docker compose up -d --build cookie-server-go`, then re-run
   `python -m core.vault_status` to confirm the extension still syncs.

⚠️ The old key is in git history. Rotating the value is what matters; scrubbing
history is optional and disruptive for a private repo used by one person.

---

## 3. The constraint no code removes: **0 launches**

`launches = 0`, `launch_outcomes = 0`. `learn.py` needs **10** before it can
calibrate anything. `rank_check` has run on a 56-hour cadence for weeks and
returns `[]` every time, because `rank_tracker.py:85` starts with
`db.get_launches()`.

**Everything this system has produced is a prediction with no track record.** That
is not a flaw in the analysis; it is the absence of the feedback half.

Today's best candidate, if you want one:

| | |
|---|---|
| term | **`halloween badge reel`** |
| winnability | 0.523–0.655 — **contested**, the only non-wall in the watch list |
| price band | $9.00–$11.00, clears the profit gate |
| timing | peak **2026-10-20**, ~7 weeks out, Pinterest reads `rising` |
| calendar | 🔴 list now — late but **not missed** |
| angle | the healthcare cluster (nurse / medical / NICU / radiology) surfaced independently from BOTH doors |

Record it the moment it is live:

```bash
.venv/Scripts/python.exe -c "from core.graph_db import GraphDB; GraphDB().record_launch('<listing_id>', 'halloween badge reel', predicted_score=0.655, product_type='personalized')"
```

From then on `rank_check` stops being a no-op, `verdict_log` and `learn.py` stop
being dead code, and the system starts being graded instead of only consulted.

⚠️ It does not have to be a good launch. A listing the system rated *watching* is
**more** informative than one it rated *list now*, because B-04 says LEARN can
never discover it was wrong to **reject** something. One control launch is worth
more than one more scoring dimension.

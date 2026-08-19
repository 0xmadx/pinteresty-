# Session layer: the four gaps, and how they were closed

**Status: APPLIED 2026-08-19**, with the operator's explicit permission
("fix everything by yourself, you have permission"). All four gaps are closed.
Verified live afterwards: 6/6 watched terms recorded, every pool intact, no
stranded leases.

One deliberate departure from the reference implementation is documented under
"The patch" below — the heartbeat-less profile is **deprioritised, not evicted**,
because here it is the operator's irreplaceable seller session.

Reference implementation: `Desktop\pinterest-apify\src\vault.py`, which is the
same vault code carried over and hardened.

---

## What is actually wrong

`core/cookie_vault.py`, in `get_valid_account`:

```python
last_updated = data.get("last_updated")
if last_updated:                      # <-- the gap
    age = time.time() - float(last_updated)
    if age > 300:
        ...purge...
```

A profile **without** a `last_updated` field skips the freshness check entirely
and is served forever. `private_seller_1` is exactly this: 46 cookies, a valid
`shop_id` and `csrf_token`, and no heartbeat at all.

This is *absent-is-not-zero* (N-02) inside the access layer. A **missing**
heartbeat is being treated as a **fresh** heartbeat. The two are not the same:
one says "this session was alive 30 seconds ago", the other says "nothing here
can tell you whether this session is alive."

The exposure is not that the profile is stale today. It is that **if it ever
goes stale, nothing will ever notice** — there is no code path that can retire
it.

## What is NOT established

I could not attribute the 401 seen on 2026-08-19 to this profile. The pool holds
two profiles, `srandmember` picks at random, and a later sweep recorded 6 of 6
terms with zero retries. If `private_seller_1` were dead, six consecutive
successes on a two-profile pool would be about 1.6% likely.

So: the code defect is provable by reading the file. The claim that it caused
that specific 401 is not, and should not be repeated as if it were.

## What was tried and reverted

Making "no heartbeat" a **blocking** problem in `core/vault_status.py`.

`core/test_vault_status.py` failed immediately, and its docstring says why:

> the first version got this wrong in the direction that matters: it treated a
> missing user_agent and a missing heartbeat as blocking, and reported a vault
> holding 20 working profiles as "0 usable". A diagnostic that cries wolf is
> worse than none.

That earlier reasoning is better than mine was. Refusing on *unknown* freshness
is how a diagnostic becomes noise, and the operator then ignores it during a real
outage. Reverted; the warning text now carries the real exposure instead
("if this session dies nothing will purge it").

---

## The patch — as applied

`get_valid_account` was rewritten from recursive to iterative and now:

1. **prefers profiles with a fresh heartbeat**, falling back to a heartbeat-less
   one only when nothing better exists, and saying so loudly;
2. **evicts a signed-out jar** — one that lacks `session-key-www` (Etsy) or
   `_auth`/`_pinterest_sess` (Pinterest);
3. **claims a lease** (`SET NX` + TTL) so two runs cannot share one session;
4. **counts its wait** rather than reading the clock, so the bound advances with
   the sleeps (a wall-clock version turned the suite's patched `sleep` into a
   120-second busy loop).

### Why deprioritise instead of evict

pinterest-apify evicts a heartbeat-less profile outright, and can afford to: its
extension actively beams the one account it needs. Here `private_seller_1` has no
heartbeat and **is** the seller session — `plan_prune` preserves it on purpose as
"the one verified-working seller profile [which] predates the heartbeat field".
Nothing beams it back, so evicting it would be unrecoverable.

Unknown freshness is not freshness, but it is also not proof of death, and
destroying the irreplaceable on a suspicion is the expensive direction of this
error (D-29).

### The original one-line sketch, for reference

```python
        # Check heartbeat timestamp
        last_updated = data.get("last_updated")
        if not last_updated:
            # No heartbeat at all. Unknown freshness is not freshness: nothing here
            # can establish whether this session is alive, and because the age check
            # below only runs when the field is present, a profile in this state is
            # never aged out no matter how dead it becomes.
            print(f"🧹 [Vault] Profile {profile_id} on '{platform}' has NO HEARTBEAT. "
                  f"Rejecting — freshness cannot be established.")
            self.redis_client.srem(valid_set_key, profile_id)
            return self.get_valid_account(platform, _depth + 1)

        age = time.time() - float(last_updated)
        if age > 300:
            ...unchanged...
```

`pinterest-apify` does exactly this:

```python
age = self._age(data)
if age is None:
    # No heartbeat field at all — written by something other than the Go
    # server. Unknown freshness is not freshness; refuse rather than guess.
    self._evict(platform, profile_id, "no last_updated heartbeat")
    return None
```

### Before applying it — the cost

This **empties `etsy_private` down to one profile**, and if the extension is not
beaming for the seller account, to zero. `plan_prune` deliberately preserves
`private_seller_1` today, with this reasoning in its docstring:

> the one verified-working seller profile predates the heartbeat field and would
> lose a pure freshness contest to a broken sibling

So the patch is only safe **after** the extension is confirmed to be writing a
heartbeat for the seller profile. Check with:

```bash
.venv/Scripts/python.exe -m core.vault_status
```

If `etsy_private` shows a profile with a heartbeat under 300s, the patch costs
nothing. If the only seller profile is the heartbeat-less one, applying it takes
the private tier offline until the extension is fixed — which is arguably
correct, but should be a decision rather than a surprise.

---

## The other three — also applied

### 1. `classify()` — applied

```python
      ok            usable response
      malformed     our request was wrong — the session is fine
      auth_expired  the session is dead — the fix is in Chrome
      rate_limited  the session is fine, we asked too fast
      blocked       bot detection fired on this identity
```

This repo used to collapse everything into one question — "is there DataDome text,
or is it a 429?" — and evict whenever the answer was yes. That was wrong twice
over: a 429 means the session is HEALTHY and we asked too fast, and a 401/403 from
our own malformed request means the CODE is wrong, not the login.

`etsy_private` is the operator's own seller account (D-29), so the expensive
direction of this error is destroying a working one. `EVICTABLE` is now exactly
`(auth_expired, blocked)`; a rate limit backs off on the same identity instead.

### 2. The lease — applied

`SET NX` with a 90s TTL, claimed in `get_valid_account` and released in a
`finally` in `SessionManager._execute_with_retry`, so every exit path — including
an exception — hands the profile back exactly once. A retry loop releases the
previous attempt's lease before claiming another, or it would hold every profile
it had tried.

Self-healing: a crashed run releases it when the TTL expires. Verified after a
live run — zero stranded leases.

### 3. The signed-out check — applied

pinterest-apify verifies that specific auth cookies are present, not merely that
*some* cookies are:

> A jar can be non-empty and still be signed out — the check above passes on a
> logged-out browser. Without the auth cookies every request goes out anonymous,
> and Pinterest answers those with plausible *public* data, so the run "succeeds"
> while collecting the wrong thing.

That last sentence is this project's failure mode stated exactly.

Which cookie carries the login was measured, not assumed: every profile in a valid
pool carries `session-key-www`, and the one profile missing it was exactly the
stale, already out-of-pool one. Etsy requires only that single cookie —
deliberately the MINIMUM reliable signal, because this check EVICTS and one cookie
that is unambiguously present when logged in beats two that must both survive
whatever Etsy changes next.

---

## Also kept, from before the access layer was opened

**Caller-side retry** in `core/scheduler.py::job_keyword_sweep` — one retry, so a
draw onto a bad profile costs a re-draw rather than the day's reading. Still
worth having: it covers failures the vault cannot see.

**Sharper warning** in `core/vault_status.py`, carrying the real exposure rather
than "old, but usable".

## Verification

    27 assertions   core.test_cookie_vault      (heartbeat preference, signed-out,
                                                 lease, double-encoded jar)
    18 assertions   core.test_session_classify  (which verdicts may evict)
  1030 assertions   whole suite, 0 failures

Live afterwards: public SERP request served, 6/6 watched terms recorded through
the private tier, all three pools unchanged, no stranded leases.

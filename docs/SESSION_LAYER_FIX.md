# The heartbeat gap — diagnosis, and a patch awaiting approval

**Status: NOT APPLIED.** The change below is inside the access layer
(`core/cookie_vault.py`), which this project's rules forbid me from editing.
It is written out so the operator can apply it, or decide not to.

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

## The patch

One line of behaviour, in `get_valid_account`:

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

## Three more things pinterest-apify has that this repo does not

Worth considering separately; none is required to close the gap above.

### 1. `classify()` — what kind of "no" is this?

```python
      ok            usable response
      malformed     our request was wrong — the session is fine
      auth_expired  the session is dead — the fix is in Chrome
      rate_limited  the session is fine, we asked too fast
      blocked       bot detection fired on this identity
```

This repo collapses 401 and 403 into `SessionDown`. The consequence is in
pinterest-apify's own comment: *"a code bug can never evict a healthy session"* —
a malformed request that returns 403 currently looks identical to a dead cookie,
so a header bug can retire a perfectly good profile and send the operator to
re-login for nothing.

`etsy_private` is the operator's own seller account. Evicting it over a code bug
is the expensive direction of that error.

### 2. A lease (`SET NX` with TTL)

Prevents two concurrent runs driving one session from two places at once. This
repo has no mutual exclusion; the scheduler is currently serial, so nothing is
broken today, but a second run started by hand while the scheduler is working
would share a profile.

The lease is self-healing: a crashed run releases it when the TTL expires.

### 3. A signed-out check

pinterest-apify verifies that specific auth cookies are present, not merely that
*some* cookies are:

> A jar can be non-empty and still be signed out — the check above passes on a
> logged-out browser. Without the auth cookies every request goes out anonymous,
> and Pinterest answers those with plausible *public* data, so the run "succeeds"
> while collecting the wrong thing.

That last sentence is this project's failure mode stated exactly. This repo
checks `cookies_json` is non-empty and, for `etsy_private`, that `csrf_token`
and `shop_id` exist — but not that the session cookies that actually carry the
login are present.

---

## What was done instead, outside the access layer

**Caller-side retry** in `core/scheduler.py::job_keyword_sweep`. A random draw
that lands on a bad profile no longer costs the day's reading for that term; the
job re-draws once and reports `retried` so the symptom stays visible. Labelled in
the code as a symptom fix, with one retry only — a genuinely dead pool should
fail fast and loudly rather than spin.

**Sharper warning** in `core/vault_status.py`, carrying the real exposure rather
than "old, but usable".

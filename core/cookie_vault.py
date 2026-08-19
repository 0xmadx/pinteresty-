import json
import time

import redis
import random
from core.settings import ScraperConfig


class VaultEmpty(RuntimeError):
    """No usable session profile for a platform.

    A distinct type because callers must be able to tell "we have no session" apart
    from "Etsy said no" — the first is fixed in Chrome, the second is a real signal.
    """


class RedisCookieVault:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.redis_client = redis.Redis.from_url(
            self.config.REDIS_URL,
            decode_responses=True
        )

    def upsert_account(self, platform: str, profile_id: str, cookie_json: dict, csrf_token: str = None, shop_id: str = None):
        """Called by the cookie_server when an extension beams a fresh cookie."""
        key = f"cookie:{platform}:{profile_id}"
        
        mapping = {
            "cookies_json": json.dumps(cookie_json) if cookie_json else "",
            "is_valid": "1"
        }
        if csrf_token:
            mapping["csrf_token"] = csrf_token
        if shop_id:
            mapping["shop_id"] = shop_id

        self.redis_client.hset(key, mapping=mapping)
        # Add to the valid pool
        self.redis_client.sadd(f"valid_profiles:{platform}", profile_id)
        
    def mark_invalid(self, platform: str, profile_id: str):
        """Called by scrapers when they encounter a 403 DataDome block."""
        key = f"cookie:{platform}:{profile_id}"
        self.redis_client.hset(key, "is_valid", "0")
        self.redis_client.srem(f"valid_profiles:{platform}", profile_id)
        print(f"🚫 [Vault] Marked {profile_id} on {platform} as INVALID. Removed from rotation.")

    # How long to wait for the extension to refresh before giving up. Unbounded waiting
    # turns "the vault is empty" into a process that never returns and never errors —
    # a scheduled job wedges overnight and reports nothing (S-2). Waiting is still
    # right: the operator may simply be re-opening Chrome. Waiting *forever* is not.
    WAIT_TIMEOUT = 120
    WAIT_INTERVAL = 5
    MAX_REJECTIONS = 25

    # A profile whose heartbeat is older than this is dead. Unchanged behaviour.
    HEARTBEAT_MAX_AGE = 300

    # How long one caller owns a profile. Long enough for a slow page, short enough
    # that a crashed run releases it unaided rather than stranding the operator's
    # only seller session until someone notices.
    LEASE_TTL = 90

    # The cookies that actually carry a LOGIN, per platform. Verified against the
    # live vault 2026-08-19: every profile in a valid pool carries all of these, and
    # the single profile missing Etsy's session keys was exactly the stale, already
    # out-of-pool one.
    #
    # Checking that the jar is non-empty is not enough. A logged-OUT browser still
    # has 30+ cookies — analytics, DataDome, preferences — so the old check passes
    # and the request goes out anonymous. Etsy answers an anonymous request with
    # plausible PUBLIC data, so the run "succeeds" while collecting the wrong thing.
    # That is this project's defining failure mode reached through the session layer.
    # Etsy requires only `session-key-www`, though every live profile also carries
    # `session-key-apex`. Deliberately the MINIMUM reliable signal: this check
    # EVICTS, and evicting the operator's seller session is the expensive direction
    # of the error (D-29). One cookie that is unambiguously present when logged in
    # and absent when not is a better gate than two that must both survive whatever
    # Etsy changes next. Pinterest's pair is what pinterest-apify verified.
    AUTH_COOKIES = {
        "etsy": ("session-key-www",),
        "etsy_private": ("session-key-www",),
        "pinterest": ("_auth", "_pinterest_sess"),
    }

    # ---------------------------------------------------------------- leasing

    def release(self, platform: str, profile_id: str):
        """Hand a leased profile back. Safe to call twice, safe if never leased."""
        try:
            self.redis_client.delete(f"lease:{platform}:{profile_id}")
        except Exception:
            # Releasing must never be the thing that breaks a run. A lease that is
            # not released expires on its own via LEASE_TTL.
            pass

    def _age(self, data):
        """Seconds since the extension last beamed this profile, or None if unknown."""
        raw = data.get("last_updated")
        if not raw:
            return None
        try:
            return time.time() - float(raw)
        except (ValueError, TypeError):
            return None

    def _reject(self, platform, profile_id, reason):
        """Take a profile out of rotation and say why."""
        self.redis_client.hset(f"cookie:{platform}:{profile_id}", "is_valid", "0")
        self.redis_client.srem(f"valid_profiles:{platform}", profile_id)
        print(f"🧹 [Vault] Evicted {platform}/{profile_id}: {reason}")

    def _inspect(self, platform, profile_id):
        """Judge one profile without claiming it.

        Returns (data, verdict) where verdict is one of:
            "fresh"      usable, heartbeat inside HEARTBEAT_MAX_AGE
            "no_beat"    usable-looking but freshness CANNOT be established
            None         unusable; already evicted, with the reason printed
        """
        data = self.redis_client.hgetall(f"cookie:{platform}:{profile_id}")
        if not data:
            # A pool member with no hash behind it. Self-heal silently.
            self.redis_client.srem(f"valid_profiles:{platform}", profile_id)
            return None, None

        raw = data.get("cookies_json")
        if not raw:
            self._reject(platform, profile_id, "no cookies — authenticates as nobody")
            return None, None

        try:
            cookies = json.loads(raw)
        except (ValueError, TypeError):
            self._reject(platform, profile_id, "cookies_json is not valid JSON")
            return None, None
        if not isinstance(cookies, dict):
            # S-3: the popup Save button double-encodes. A string here is not a jar.
            self._reject(platform, profile_id, "cookies_json double-encoded (S-3)")
            return None, None

        required = self.AUTH_COOKIES.get(platform, ())
        missing = [c for c in required if c not in cookies]
        if missing:
            self._reject(platform, profile_id,
                         f"SIGNED OUT — missing {', '.join(missing)}")
            return None, None

        if platform == "etsy_private" and not (data.get("csrf_token") and data.get("shop_id")):
            self._reject(platform, profile_id,
                         "missing seller tokens (csrf_token/shop_id)")
            return None, None

        age = self._age(data)
        if age is None:
            # NO HEARTBEAT. The old code read `if last_updated:` and so skipped the
            # freshness check entirely for these — a MISSING heartbeat treated as a
            # FRESH one, which is absent-is-not-zero (N-02) inside the access layer.
            #
            # But it is NOT evicted here, and this is a deliberate departure from the
            # pinterest-apify vault this fix is modelled on. That project evicts, and
            # can afford to: its extension actively beams the only account it needs.
            # Here, `private_seller_1` has no heartbeat and IS the operator's seller
            # session — plan_prune preserves it on purpose as "the one verified-working
            # seller profile [which] predates the heartbeat field". Evicting it would
            # be unrecoverable, because nothing beams it back.
            #
            # So it is DEPRIORITISED instead: served only when no fresh profile exists,
            # and loudly when it is. Unknown freshness is not freshness, but it is also
            # not proof of death, and destroying the irreplaceable on a suspicion is the
            # expensive direction of this error (D-29).
            data["cookies_json"] = cookies
            data["profile_id"] = profile_id
            return data, "no_beat"

        if age > self.HEARTBEAT_MAX_AGE:
            self._reject(platform, profile_id,
                         f"heartbeat stale ({int(age)}s > {self.HEARTBEAT_MAX_AGE}s)")
            return None, None

        data["cookies_json"] = cookies
        data["profile_id"] = profile_id
        return data, "fresh"

    def _claim(self, platform, profile_id):
        """SET NX is the whole of the mutual exclusion.

        Whoever sets the key owns the profile until the TTL expires, so two runs can
        never drive one Etsy session from two places at once — which is precisely the
        pattern a fingerprinter looks for. A crashed run releases it unaided.
        """
        return bool(self.redis_client.set(
            f"lease:{platform}:{profile_id}", "1", nx=True, ex=self.LEASE_TTL))

    def get_valid_account(self, platform: str, _depth: int = 0):
        """Lease a usable account, waiting a bounded time for one to appear.

        Iterative, not recursive: the old version recursed once per rejected profile
        and needed MAX_REJECTIONS to avoid a RecursionError masking the real reason.

        FRESH PROFILES ARE PREFERRED. A profile with no heartbeat is used only when
        nothing better exists, because its freshness cannot be established — see
        _inspect. `_depth` is accepted and ignored, so existing callers still work.
        """
        valid_set_key = f"valid_profiles:{platform}"
        # Counted, not wall-clock. The suite patches time.sleep to a no-op to keep
        # itself fast; against a real deadline that turns the wait into a 120-second
        # busy loop, so the bound must advance with the sleeps rather than with the
        # clock. (Learned by hanging the test suite with the wall-clock version.)
        waited = 0
        warned_empty = False

        while True:
            candidates = list(self.redis_client.smembers(valid_set_key) or [])
            random.shuffle(candidates)

            fallback = []
            for profile_id in candidates:
                data, verdict = self._inspect(platform, profile_id)
                if data is None:
                    continue
                if verdict == "no_beat":
                    # Remember it, but keep looking for something provably fresh.
                    fallback.append((profile_id, data))
                    continue
                if self._claim(platform, profile_id):
                    return data

            for profile_id, data in fallback:
                if self._claim(platform, profile_id):
                    print(f"⚠️  [Vault] Using {platform}/{profile_id}, which has NO "
                          f"HEARTBEAT — freshness cannot be established. Nothing "
                          f"fresher is in the pool. If requests start failing, this "
                          f"is the first suspect.")
                    return data

            if waited >= self.WAIT_TIMEOUT:
                raise VaultEmpty(
                    f"No leasable '{platform}' profile after {self.WAIT_TIMEOUT}s. "
                    f"Run `python -m core.vault_status` — it reports whether the pool "
                    f"is genuinely empty, whether every profile is signed out, or "
                    f"whether this process is reading the wrong Redis.")

            if not warned_empty:
                print(f"⏳ [Vault] No usable '{platform}' profile. Waiting up to "
                      f"{self.WAIT_TIMEOUT}s for the Chrome extension to refresh...")
                warned_empty = True
            time.sleep(self.WAIT_INTERVAL)
            waited += self.WAIT_INTERVAL

    def set_shop_id(self, platform: str, profile_id: str, shop_id: str):
        """Update the shop_id for a specific profile."""
        key = f"cookie:{platform}:{profile_id}"
        self.redis_client.hset(key, "shop_id", shop_id)
        print(f"✅ [Vault] Saved Shop ID {shop_id} for {profile_id} on {platform}.")


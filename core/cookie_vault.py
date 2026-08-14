import json
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

    def get_valid_account(self, platform: str, _depth: int = 0):
        """Called by scrapers to grab a random working account.

        Raises VaultEmpty if no profile appears within WAIT_TIMEOUT.
        """
        valid_set_key = f"valid_profiles:{platform}"

        # Grab a random profile ID from the valid set
        profile_id = self.redis_client.srandmember(valid_set_key)

        import time
        waited = 0
        while not profile_id:
            if waited >= self.WAIT_TIMEOUT:
                raise VaultEmpty(
                    f"No valid '{platform}' profile after {waited}s. "
                    f"Run `python -m core.vault_status` — it reports whether the pool is "
                    f"genuinely empty or whether this process is reading the wrong Redis."
                )
            print(f"⏳ [Vault] No valid accounts for '{platform}'. Waiting for Chrome Extension "
                  f"to refresh cookies... ({waited}/{self.WAIT_TIMEOUT}s)")
            time.sleep(self.WAIT_INTERVAL)
            waited += self.WAIT_INTERVAL
            profile_id = self.redis_client.srandmember(valid_set_key)

        # Each rejection below recurses. Without a depth bound, a pool of N unusable
        # profiles costs N frames and then raises RecursionError instead of the real
        # reason — so the reason is carried explicitly.
        if _depth > self.MAX_REJECTIONS:
            raise VaultEmpty(
                f"Rejected {_depth} consecutive '{platform}' profiles as unusable. "
                f"Run `python -m core.vault_status` for the per-profile reason."
            )

        # Fetch the data for this profile
        key = f"cookie:{platform}:{profile_id}"
        data = self.redis_client.hgetall(key)
        
        if not data:
             # Cleanup anomaly
             self.redis_client.srem(valid_set_key, profile_id)
             return self.get_valid_account(platform, _depth + 1)
             
        # Check heartbeat timestamp
        last_updated = data.get("last_updated")
        if last_updated:
            age = time.time() - float(last_updated)
            if age > 300: # 5 minutes
                print(f"🧹 [Vault] Profile {profile_id} is DEAD (no heartbeat for {int(age)}s). Purging from '{platform}'...")
                self.redis_client.srem(valid_set_key, profile_id)
                return self.get_valid_account(platform, _depth + 1)
             
        # A profile with no cookies authenticates as nobody. The pool held four of
        # these on pinterest, and nothing stopped them being drawn: the seller check
        # below only guards etsy_private, so a public or pinterest request would go out
        # completely unauthenticated and the failure would look like a site change
        # rather than a missing session (S-13).
        if not data.get("cookies_json"):
            print(f"⚠️ [Vault] Profile {profile_id} on '{platform}' has NO COOKIES. "
                  f"Rejecting — it cannot authenticate as anyone.")
            self.redis_client.srem(valid_set_key, profile_id)
            return self.get_valid_account(platform, _depth + 1)

        # Auto-Detect Secondary Layer: Verify private profiles are actually private
        if platform == "etsy_private":
            if not data.get("csrf_token") or not data.get("shop_id"):
                print(f"⚠️ [Vault] AUTO-DETECT: Profile {profile_id} in 'etsy_private' is missing seller tokens! Rejecting to protect account.")
                self.redis_client.srem(valid_set_key, profile_id)
                return self.get_valid_account(platform, _depth + 1)
                
        data['profile_id'] = profile_id
        if data.get("cookies_json"):
            data["cookies_json"] = json.loads(data["cookies_json"])
            
        return data

    def set_shop_id(self, platform: str, profile_id: str, shop_id: str):
        """Update the shop_id for a specific profile."""
        key = f"cookie:{platform}:{profile_id}"
        self.redis_client.hset(key, "shop_id", shop_id)
        print(f"✅ [Vault] Saved Shop ID {shop_id} for {profile_id} on {platform}.")


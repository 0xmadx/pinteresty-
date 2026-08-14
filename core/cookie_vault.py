import json
import redis
import random
from core.settings import ScraperConfig

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

    def get_valid_account(self, platform: str):
        """Called by scrapers to grab a random working account."""
        valid_set_key = f"valid_profiles:{platform}"
        
        # Grab a random profile ID from the valid set
        profile_id = self.redis_client.srandmember(valid_set_key)
        
        import time
        while not profile_id:
            print(f"⏳ [Vault] No valid accounts for '{platform}'. Waiting for Chrome Extension to refresh cookies...")
            time.sleep(5)
            profile_id = self.redis_client.srandmember(valid_set_key)
            
        # Fetch the data for this profile
        key = f"cookie:{platform}:{profile_id}"
        data = self.redis_client.hgetall(key)
        
        if not data:
             # Cleanup anomaly
             self.redis_client.srem(valid_set_key, profile_id)
             return self.get_valid_account(platform)
             
        # Check heartbeat timestamp
        last_updated = data.get("last_updated")
        if last_updated:
            age = time.time() - float(last_updated)
            if age > 300: # 5 minutes
                print(f"🧹 [Vault] Profile {profile_id} is DEAD (no heartbeat for {int(age)}s). Purging from '{platform}'...")
                self.redis_client.srem(valid_set_key, profile_id)
                return self.get_valid_account(platform)
             
        # Auto-Detect Secondary Layer: Verify private profiles are actually private
        if platform == "etsy_private":
            if not data.get("csrf_token") or not data.get("shop_id"):
                print(f"⚠️ [Vault] AUTO-DETECT: Profile {profile_id} in 'etsy_private' is missing seller tokens! Rejecting to protect account.")
                self.redis_client.srem(valid_set_key, profile_id)
                return self.get_valid_account(platform)
                
        data['profile_id'] = profile_id
        if data.get("cookies_json"):
            data["cookies_json"] = json.loads(data["cookies_json"])
            
        return data

    def set_shop_id(self, platform: str, profile_id: str, shop_id: str):
        """Update the shop_id for a specific profile."""
        key = f"cookie:{platform}:{profile_id}"
        self.redis_client.hset(key, "shop_id", shop_id)
        print(f"✅ [Vault] Saved Shop ID {shop_id} for {profile_id} on {platform}.")


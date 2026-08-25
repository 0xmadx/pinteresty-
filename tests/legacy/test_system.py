import time
import json
import redis
from core.cookie_vault import RedisCookieVault
from core.session_manager import SessionManager
import requests
from unittest.mock import Mock, patch

def run_tests():
    print("🚀 Starting comprehensive system tests...")
    
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    
    # --- SETUP TEST DATA ---
    print("\n[1] Setting up Redis test data...")
    r.delete("valid_profiles:test_etsy")
    r.delete("valid_profiles:test_etsy_private")
    
    current_time = time.time()
    dead_time = current_time - 400 # 6+ minutes old
    
    # 1. Good Public Profile
    r.hset("cookie:test_etsy:good_pub", mapping={"cookies_json": "{}", "last_updated": current_time})
    r.sadd("valid_profiles:test_etsy", "good_pub")
    
    # 2. Dead Public Profile (Should be purged)
    r.hset("cookie:test_etsy:dead_pub", mapping={"cookies_json": "{}", "last_updated": dead_time})
    r.sadd("valid_profiles:test_etsy", "dead_pub")
    
    # 3. Good Private Profile
    r.hset("cookie:test_etsy_private:good_priv", mapping={"cookies_json": "{}", "last_updated": current_time, "shop_id": "123", "csrf_token": "abc"})
    r.sadd("valid_profiles:test_etsy_private", "good_priv")
    
    # 4. Bad Private Profile (Missing shop_id)
    r.hset("cookie:test_etsy_private:bad_priv", mapping={"cookies_json": "{}", "last_updated": current_time, "csrf_token": "abc"})
    r.sadd("valid_profiles:test_etsy_private", "bad_priv")

    from core.settings import ScraperConfig
    config = ScraperConfig()
    vault = RedisCookieVault(config=config)
    
    # --- TEST 1: The 5-Minute Purger ---
    print("\n[2] Testing 5-Minute Heartbeat Purger...")
    # Because 'srandmember' is random, we just loop enough times to ensure it hits 'dead_pub'
    # Actually, we can just assert that if we call get_valid_account multiple times, it eventually removes 'dead_pub'
    for _ in range(5):
        vault.get_valid_account("test_etsy")
        
    members = r.smembers("valid_profiles:test_etsy")
    if "dead_pub" not in members and "good_pub" in members:
        print("✅ PASS: Dead profile (>5 mins) was successfully purged.")
    else:
        print(f"❌ FAIL: Expected only 'good_pub', got {members}")
        
    # --- TEST 2: Private Auto-Detect Layer ---
    print("\n[3] Testing Private Auto-Detect Guardian...")
    for _ in range(5):
        vault.get_valid_account("test_etsy_private")
        
    members_priv = r.smembers("valid_profiles:test_etsy_private")
    if "bad_priv" not in members_priv and "good_priv" in members_priv:
        print("✅ PASS: Profile missing seller tokens was successfully rejected.")
    else:
        print(f"❌ FAIL: Expected only 'good_priv', got {members_priv}")
        
    # --- TEST 3: Session Manager 403 Rotation ---
    print("\n[4] Testing Session Manager 403 Instant Rotation...")
    session_manager = SessionManager(platform="test_etsy", max_retries=2)
    
    # Mocking the session.request to return a 403 first, then a 200
    mock_response_403 = Mock()
    mock_response_403.status_code = 403
    
    mock_response_200 = Mock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {"success": True}
    
    # We patch requests.Session.request instead of passing session directly, 
    # but SessionManager uses a newly created requests.Session. 
    # We can patch it at the class level.
    with patch("requests.Session.request", side_effect=[mock_response_403, mock_response_200]) as mock_req:
        try:
            result = session_manager.request("GET", "https://example.com")
            if result.status_code == 200:
                print("✅ PASS: Session Manager caught the 403 and successfully rotated to a new profile!")
            else:
                print("❌ FAIL: Session Manager returned the wrong response.")
        except Exception as e:
             print(f"❌ FAIL: Session Manager threw an exception: {e}")
             
    # Clean up
    r.delete("valid_profiles:test_etsy", "valid_profiles:test_etsy_private")
    r.delete("cookie:test_etsy:good_pub", "cookie:test_etsy:dead_pub")
    r.delete("cookie:test_etsy_private:good_priv", "cookie:test_etsy_private:bad_priv")
    print("\n🧹 Cleaned up test data.")

if __name__ == "__main__":
    run_tests()

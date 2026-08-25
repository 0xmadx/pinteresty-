import os
import sys
import json
import redis
import unittest

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager
from core.settings import ScraperConfig
from etsy.api.private.api import EtsyPrivateAPI

class TestDynamicPooling(unittest.TestCase):
    def setUp(self):
        self.config = ScraperConfig()
        
        # Manually seed a dummy profile in Redis
        self.redis_client = redis.from_url(self.config.REDIS_URL, decode_responses=True)
        self.test_profile_id = "profile_test_123"
        self.test_shop_id = "999999"
        self.test_csrf = "fake_csrf_abc123"
        
        # 1. Clear any existing test profile
        self.redis_client.delete(f"cookie:etsy_private:{self.test_profile_id}")
        self.redis_client.srem("valid_profiles:etsy_private", self.test_profile_id)
        
        # 2. Add the test profile to the set
        self.redis_client.sadd("valid_profiles:etsy_private", self.test_profile_id)
        
        # 3. Add the hash data
        self.redis_client.hset(
            f"cookie:etsy_private:{self.test_profile_id}",
            mapping={
                "cookies_json": json.dumps({"test_cookie": "123"}),
                "shop_id": self.test_shop_id,
                "csrf_token": self.test_csrf,
                "user_agent": "TestAgent/1.0"
            }
        )

    def tearDown(self):
        # Cleanup
        self.redis_client.delete(f"cookie:etsy_private:{self.test_profile_id}")
        self.redis_client.srem("valid_profiles:etsy_private", self.test_profile_id)
        self.redis_client.close()

    def test_url_and_header_injection(self):
        """
        Verify that calling the Private API dynamically injects the shop_id into the URL
        and the csrf_token into the headers, specifically by inspecting the requests Session.
        """
        api = EtsyPrivateAPI()
        
        # We will mock session.get to just return a mock response but capture what it was called with.
        # However, it's easier to mock curl_cffi.requests.Session inside _build_session.
        
        class MockResponse:
            def __init__(self):
                self.status_code = 200
            def json(self):
                return {"success": True}
                
        # Instead of actually hitting the network, let's patch the underlying session.get
        # Wait, curl_cffi Session is an object created inside _build_session.
        # We can just patch it out.
        
        original_build_session = api.session._build_session
        captured_request = {}
        
        class MockSession:
            def __init__(self):
                self.cookies = type('MockCookies', (), {'set': lambda self, k, v, domain=None: None})()
                self.headers = {}
                
            def get(self, url, **kwargs):
                captured_request['url'] = url
                captured_request['headers'] = dict(self.headers)
                return MockResponse()
                
            def post(self, url, **kwargs):
                captured_request['url'] = url
                captured_request['headers'] = dict(self.headers)
                return MockResponse()

        api.session._build_session = lambda: MockSession()

        # Trigger a private API call
        # Mock RequestCache to just run the _fetch function directly to avoid caching logic interfering
        class MockCache:
            def get_or_fetch(self, key, ttl, fetch_func, source):
                return fetch_func()
                
        api.cache = MockCache()
        
        api.get_results_data("test query")
        
        # Verify
        print(f"Captured URL: {captured_request.get('url')}")
        print(f"Captured Headers: {captured_request.get('headers')}")
        
        self.assertIn(self.test_shop_id, captured_request['url'], "shop_id was NOT injected into URL!")
        self.assertNotIn("{shop_id}", captured_request['url'], "URL still contains {shop_id} placeholder!")
        
        self.assertEqual(captured_request['headers'].get('x-csrf-token'), self.test_csrf, "CSRF token was NOT injected into Headers!")
        print("✅ SUCCESS: URL and Headers are correctly formatted dynamically by SessionManager!")

if __name__ == '__main__':
    unittest.main()

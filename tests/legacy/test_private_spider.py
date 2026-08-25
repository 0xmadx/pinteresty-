import time
import json
from core.settings import ScraperConfig
from core.session_manager import SessionManager
from core.cookie_vault import RedisCookieVault
from core.endpoints_manager import EndpointManager

def test_private_spider():
    print("Testing Etsy Private Spider with Redis Cookies & Registry Endpoint")
    print("-" * 60)
    
    config = ScraperConfig()
    vault = RedisCookieVault(config)
    session = SessionManager(config)
    endpoint_manager = EndpointManager()

    print("\n[1] Fetching valid Etsy Private profiles...")
    private_profiles = vault.redis_client.smembers("valid_profiles:etsy_private")
    if not private_profiles:
        print("❌ No valid Etsy Private profiles found in Redis. Please sync one via the Chrome Extension first.")
        return
        
    print(f"✅ Found {len(private_profiles)} Etsy Private profiles.")
    
    try:
        # Get an account from the vault (which includes csrf_token and shop_id)
        account = vault.get_valid_account("etsy_private")
        
        csrf_token = account.get("csrf_token")
        shop_id = account.get("shop_id")
        
        # Fallback to auto-discovery if the extension didn't capture the shop_id dynamically
        if not shop_id:
            print("⚠️ Shop ID missing from Redis! Auto-discovering...")
            shop_id = session.auto_discover_shop_id("etsy_private")
            
        profile_id = account.get("profile_id")
        
        print(f"Using Profile: {profile_id}")
        print(f"Shop ID: {shop_id}")
        if csrf_token:
            print(f"CSRF Token: {csrf_token[:10]}...{csrf_token[-10:]}")
        else:
            print("CSRF Token: None")

        
        if not csrf_token or not shop_id:
            print("❌ Missing CSRF Token or Shop ID! Auto-discovery failed.")
            return

        # Load the base endpoint from registry
        endpoint = endpoint_manager.get_endpoint("base")
        print("\n[2] Loaded 'base' endpoint from registry.")
        
        # Format the URL with the actual shop_id from Redis
        # The registry url looks like: https://www.etsy.com/api/v3/ajax/shop/56057851/marketplace-insights/...
        # We need to replace the hardcoded shop ID with our actual shop ID
        import re
        url = re.sub(r'/shop/\d+/', f'/shop/{shop_id}/', endpoint["url_template"])
        
        # Extract headers and payload
        headers = endpoint.get("headers", {})
        payload = endpoint.get("payload_template")
        method = endpoint.get("method", "POST")
        
        # Inject the correct CSRF token
        headers["x-csrf-token"] = csrf_token
        
        print(f"\n[3] Executing {method} Request to: {url}")
        print(f"Payload: {payload}")
        
        # Note: SessionManager automatically injects the cookies when platform="etsy_private"
        # and impersonates Chrome 124 TLS.
        response = session.request(
            method=method,
            url=url,
            headers=headers,
            data=payload,
            platform="etsy_private"
        )
        
        print("-" * 60)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Success! Response:")
            try:
                print(json.dumps(response.json(), indent=2)[:1000] + "\n... [truncated]")
            except Exception:
                print(response.text[:1000])
        else:
            print("❌ Request failed or blocked.")
            print("Response Headers:")
            print(response.headers)
            print("\nResponse Body:")
            print(response.text[:1000])
            
    except Exception as e:
        print(f"Error during test: {e}")

if __name__ == "__main__":
    test_private_spider()

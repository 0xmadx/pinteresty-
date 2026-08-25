import json
from core.settings import ScraperConfig
from etsy.api.public.api import EtsyPublicAPI
from etsy.api.private.api import EtsyPrivateAPI

def run_live_tests():
    print("🚀 Starting LIVE System Tests against real endpoints...")
    config = ScraperConfig()

    # --- TEST 1: Etsy Public API ---
    print("\n" + "="*60)
    print("[1] Testing Etsy Public API (Search Endpoint)")
    print("="*60)
    
    try:
        public_api = EtsyPublicAPI()
        print("Querying public search for 'wooden watch' (Page 1)...")
        results = public_api.get_public_search(query="wooden watch", filters={"page": 1})
        
        if results and "cards" in results:
            print(f"✅ PASS: Successfully retrieved {len(results['cards'])} listings from Public Search!")
            print(f"Sample First Item: {results['cards'][0].get('title', 'No Title')} - {results['cards'][0].get('price', 'No Price')}")
        else:
            print("❌ FAIL: Public search returned empty results. (Check if DataDome blocked it)")
    except Exception as e:
        print(f"❌ FAIL: Public API Exception: {e}")

    # --- TEST 2: Etsy Private API ---
    print("\n" + "="*60)
    print("[2] Testing Etsy Private API (Trending Terms Endpoint)")
    print("="*60)
    
    try:
        private_api = EtsyPrivateAPI()
        print("Querying private trending terms for taxonomy_id 199...")
        results = private_api.get_trending_terms(taxonomy_id=199)
        
        if results:
            print(f"✅ PASS: Successfully retrieved trending terms from Private API!")
            print(f"Sample Term (keys): {list(results.keys())}")
        else:
            print("❌ FAIL: Private API returned empty results or blocked.")
    except Exception as e:
        print(f"❌ FAIL: Private API Exception: {e}")

if __name__ == "__main__":
    run_live_tests()

import sys
import pprint
from config.settings import ScraperConfig
from core.cookie_pool import CanaryCookiePool

def test_cookies():
    print("Testing Chrome Canary Cookie Extraction...")
    config = ScraperConfig()
    
    print(f"Looking for Canary profile at: {config.CANARY_PROFILE_PATH}")
    
    cookie_pool = CanaryCookiePool(config)
    
    # Force refresh
    cookie_pool.refresh()
    
    cookies = cookie_pool.get_cookie_dict()
    
    if not cookies:
        print("\nNo cookies were found! Check if:")
        print("1. Chrome Canary is installed")
        print("2. You have visited Etsy in Canary")
        print("3. The CANARY_PROFILE_PATH in config/settings.py is correct")
    else:
        print(f"\nSuccessfully extracted {len(cookies)} cookies:")
        pprint.pprint(cookies)

if __name__ == "__main__":
    test_cookies()

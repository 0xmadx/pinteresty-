import sys
import pprint
from config.settings import ScraperConfig
from core.cookie_pool import PlaywrightCookiePool

def test_playwright_cookies():
    print("Testing Playwright Cookie Extraction...")
    config = ScraperConfig()
    cookie_pool = PlaywrightCookiePool(config)
    
    cookie_pool.refresh()
    cookies = cookie_pool.get_cookie_dict()
    
    if not cookies:
        print("\nNo cookies were found!")
    else:
        print(f"\nSuccessfully extracted {len(cookies)} cookies:")
        pprint.pprint(cookies)

if __name__ == "__main__":
    test_playwright_cookies()

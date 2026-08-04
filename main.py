import sys
from config.settings import ScraperConfig
from core.cookie_pool import PlaywrightCookiePool
from core.session_factory import ImpersonatedSession
from scraper.search_client import SearchClient
from scraper.parser import SearchParser
from services.search_service import SearchService

def main():
    print("Initializing Antigravity Scraper for Etsy...")
    config = ScraperConfig()
    cookie_pool = PlaywrightCookiePool(config)
    session = ImpersonatedSession(config, cookie_pool)
    
    client = SearchClient(session, config)
    parser = SearchParser()
    service = SearchService(client, parser)
    
    keyword = "vintage leather jacket"
    print(f"\n--- Running Full Search Pipeline for '{keyword}' ---")
    results = service.full_search_pipeline(keyword, pages=1)
    
    for page in results:
        print(f"Page {page.page_number} Results: {len(page.items)} items found")
        for item in page.items[:5]: # Print first 5
            price_display = f"({item.price})" if item.price else ""
            print(f" - {item.title} {price_display} -> {item.url[:60]}...")
            
    print("\n--- Testing Discover Queries ---")
    discovered = service.discover_queries("leather ")
    print(f"Suggestions: {discovered}")
            
if __name__ == "__main__":
    main()

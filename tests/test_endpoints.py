import os
import json
from config.settings import ScraperConfig
from core.cookie_pool import PlaywrightCookiePool
from core.session_factory import ImpersonatedSession
from scraper.search_client import SearchClient
from scraper.parser import SearchParser

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def save_text(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(data)

def main():
    print("Initializing test client...")
    config = ScraperConfig()
    cookie_pool = PlaywrightCookiePool(config)
    session = ImpersonatedSession(config, cookie_pool)
    
    client = SearchClient(session, config)
    parser = SearchParser()
    
    # Create directories
    dirs = ['data/search', 'data/suggest', 'data/typing_suggest']
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        
    print("\n--- 1. Testing Search Endpoint ---")
    search_html = client.search("handmade ring", page=1)
    if search_html:
        save_text("data/search/raw_response.html", search_html)
        parsed = parser.parse_search_results(search_html, page_number=1)
        save_json("data/search/parsed_results.json", parsed.model_dump())
        print(f"Saved {len(parsed.items)} parsed items to data/search/")
    else:
        print("Search failed.")

    print("\n--- 2. Testing Trending Suggest Endpoint ---")
    trending = client.get_trending_suggestions()
    save_json("data/suggest/trending.json", trending)
    print("Saved trending suggestions to data/suggest/")
    
    print("\n--- 3. Testing Typing Suggest Endpoint ---")
    typing = client.get_typing_suggestions("hand")
    save_json("data/typing_suggest/typing.json", typing)
    print("Saved typing suggestions to data/typing_suggest/")
    
    print("\nDone! Check the 'data/' folder.")

if __name__ == "__main__":
    main()

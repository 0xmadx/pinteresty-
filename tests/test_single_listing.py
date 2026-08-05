import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import ScraperConfig
from src.core.session_manager import SessionManager
from src.parsers.search_client import SearchClient

def run_test():
    print("Initializing Endpoint Engine for Single Listing Test...")
    config = ScraperConfig()
    
    # We use SessionManager which automatically loads the Datadome bypass cookie
    session_manager = SessionManager(config)
    client = SearchClient(session_manager.session, config)
    
    # Testing a real listing URL to parse its HTML
    url = "https://www.etsy.com/listing/1370681297/solitaire-ring-radiant-cut-5x7mm"
    print(f"[*] Fetching listing page: {url}")
    
    html = client.get_listing(url)
    
    if html:
        os.makedirs("data/endpoints", exist_ok=True)
        
        # Save raw HTML
        raw_filename = "data/endpoints/single_listing_1370681297.html"
        with open(raw_filename, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[+] Successfully fetched listing. Saved raw HTML to {raw_filename}")
    else:
        print("[-] Failed to fetch listing.")

if __name__ == "__main__":
    run_test()

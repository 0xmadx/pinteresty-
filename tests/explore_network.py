from playwright.sync_api import sync_playwright
import time

def explore_etsy():
    endpoints = []
    
    def log_response(response):
        if response.request.resource_type in ["xhr", "fetch"]:
            url = response.url
            if "etsy.com" in url and ("api" in url or "ajax" in url or "graphql" in url):
                endpoints.append(url)

    with sync_playwright() as p:
        print("Launching stealth-like browser to capture network requests...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.on("response", log_response)
        
        print("1. Visiting Homepage...")
        page.goto("https://www.etsy.com/")
        time.sleep(3)
        
        print("2. Simulating typing 'vintage leather'...")
        try:
            page.type("[data-id='search-query']", "vintage leather", delay=200)
        except Exception:
            pass
        time.sleep(2)
        
        print("3. Executing Search...")
        try:
            page.keyboard.press("Enter")
            page.wait_for_selector(".search-listings-group", timeout=10000)
        except Exception:
            pass
        time.sleep(3)
        
        print("4. Visiting a listing page...")
        try:
            links = page.query_selector_all("a.listing-link")
            if links:
                links[0].click()
                time.sleep(4)
        except Exception:
            pass
            
        browser.close()
        
    print("\n--- DISCOVERED INTERNAL API ENDPOINTS ---")
    unique_endpoints = sorted(list(set(endpoints)))
    for url in unique_endpoints:
        # Strip long query parameters for readability
        base_url = url.split("?")[0]
        print(base_url)

if __name__ == "__main__":
    explore_etsy()

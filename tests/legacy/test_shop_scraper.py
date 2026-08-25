from core.shop_scraper import ShopScraper
from core.settings import ScraperConfig
import sys

# Mock public API to just hold the config since ShopScraper takes it
class MockAPI:
    def __init__(self):
        self.config = ScraperConfig()
        self.cookies = {}
        
    def update_datadome_cookie(self, cookie):
        pass

if __name__ == "__main__":
    shop_name = "planner" if len(sys.argv) == 1 else sys.argv[1]
    
    print(f"Testing ShopScraper for shop: {shop_name}")
    api = MockAPI()
    scraper = ShopScraper(api)
    
    metrics = scraper.get_shop_metrics(shop_name)
    
    if metrics:
        print("✅ Scraped Metrics successfully:")
        print(metrics)
    else:
        print("❌ Failed to scrape metrics.")

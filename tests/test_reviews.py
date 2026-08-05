import sys
import os

# Add parent directory to path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import ScraperConfig
from src.core.session_manager import SessionManager
from src.endpoints.manager import EndpointManager
from src.services.review_service import ReviewService

def test_reviews_scraper():
    print("Initializing Review Scraper test...")
    
    config = ScraperConfig()
    session_manager = SessionManager(config)
    endpoint_manager = EndpointManager()
    
    # We must ensure the registry is loaded with the 'reviews' endpoint
    # The user previously added 'reviews' to registry.json via the main.py execution
    
    review_service = ReviewService(session_manager, endpoint_manager)
    
    try:
        # Scrape up to 2 pages with anti-ban delays
        reviews = review_service.scrape_reviews("reviews", max_pages=2)
        
        print(f"\n--- Successfully extracted {len(reviews)} Reviews! ---")
        for i, rev in enumerate(reviews[:5]):
            print(f"Review {i+1}:")
            print(f"  Buyer: {rev.buyer_name}")
            print(f"  Rating: {rev.rating}/5")
            print(f"  Date: {rev.date}")
            print(f"  Text: {rev.review_text[:100]}...")
            if rev.seller_response:
                print(f"  Seller Response: {rev.seller_response[:50]}...")
            print("-" * 40)
            
    except Exception as e:
        print(f"Error during review scraping: {e}")

if __name__ == "__main__":
    test_reviews_scraper()

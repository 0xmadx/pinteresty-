import re
import urllib.parse
from bs4 import BeautifulSoup
import json

from core.guards import soft_parse

def _parse_count(text):
    """'(4.2k)' -> 4200, '(19.8k)' -> 19800, '3,456' -> 3456, '3456 Sales' -> 3456"""
    if not text:
        return None
    # Remove commas and extract numbers and k/m
    text = text.lower().replace(',', '')
    m = re.search(r'([\d.]+)\s*([km]?)', text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    multiplier = {'k': 1_000, 'm': 1_000_000}.get(m.group(2), 1)
    return int(value * multiplier)

from bs4 import BeautifulSoup
from core.session_manager import SessionManager

class ShopScraper:
    def __init__(self, public_api):
        """
        Accepts an instance of EtsyPublicAPI for backwards compatibility.
        Now uses SessionManager to automatically bypass DataDome and inject synced cookies.
        """
        self.api = public_api
        self.config = self.api.config
        self.session_manager = SessionManager(self.config)

    def get_shop_metrics(self, shop_name):
        """
        Fetches the public shop homepage and extracts Total Sales and Total Reviews.
        Returns a dict: {'shop_name': str, 'total_sales': int, 'total_reviews': int}
        """
        url = f"https://www.etsy.com/shop/{urllib.parse.quote_plus(shop_name)}"
        
        # SessionManager will automatically try 'etsy' cookies.
        # It natively handles the failover loop, headers, and Datadome evasion.
        try:
            resp = self.session_manager.get(url, platform="etsy")
        except ValueError as e:
            print(f"⚠️ {e}")
            print("⚠️ No valid 'etsy' cookies. Falling back to 'etsy_private' cookies for public scraping.")
            try:
                resp = self.session_manager.get(url, platform="etsy_private")
            except ValueError as e:
                print(f"[-] {e}")
                return None
        
        # Keep the session alive: check if Etsy returned an updated datadome cookie
        if hasattr(resp, 'cookies'):
            new_datadome = resp.cookies.get('datadome')
            if new_datadome and self.api:
                self.api.update_datadome_cookie(new_datadome)
        
        if resp.status_code != 200:
            print(f"[-] Failed to fetch shop page for {shop_name}. Status Code: {resp.status_code}")
            return None
            
        soup = BeautifulSoup(resp.text, "html.parser")
            
        # 1. Find Total Sales
        total_sales = None
        sales_tags = soup.select('a[href$="/sold"]')
        if sales_tags:
            total_sales = _parse_count(sales_tags[0].text)
            
        # 2. Find Total Reviews
        total_reviews = None
        review_tags = soup.select('[data-buy-box-region="reviews"]')
        if review_tags:
            total_reviews = _parse_count(review_tags[0].text)
            
        # Fallback for reviews if data-attribute is missing (e.g., just "(4.2k)")
        if total_reviews is None:
            headers = soup.select('div.shop-home-header')
            if headers:
                # Look for a string like "(4.2k)"
                match = re.search(r'\(([\d.,]+[km]?)\)', headers[0].text)
                if match:
                    total_reviews = _parse_count(match.group(1))

        # Fallback for sales if the shop hides their sold history (the link disappears)
        if total_sales is None:
            headers = soup.select('div.shop-home-header')
            if headers:
                # Look for "26.8k Sales" or "26.8k sales" across lines
                text = headers[0].text.lower()
                match = re.search(r'([\d.,]+[km]?)\s*sales?', text)
                if match:
                    total_sales = _parse_count(match.group(1))
                    
        # 3. Extract exact LD+JSON Data
        exact_review_count = None
        exact_active_listings = None
        
        ld_matches = re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', resp.text, re.IGNORECASE | re.DOTALL)
        for m in ld_matches:
            with soft_parse("shop.ld_json", shop_name=shop_name):
                data = json.loads(m.group(1).strip())
                if isinstance(data, list):
                    for item in data:
                        # Extract exact reviews from Organization aggregateRating
                        if item.get('@type') == 'Organization':
                            rating = item.get('aggregateRating', {})
                            if 'reviewCount' in rating:
                                exact_review_count = int(rating['reviewCount'])

                        # Extract exact active items from ItemList
                        if item.get('@type') == 'ItemList':
                            if 'numberOfItems' in item:
                                exact_active_listings = int(item['numberOfItems'])

        return {
            "shop_name": shop_name,
            "total_sales": total_sales,
            "total_reviews": exact_review_count if exact_review_count is not None else total_reviews,
            "active_listings": exact_active_listings
        }

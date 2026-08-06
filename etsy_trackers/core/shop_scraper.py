import re
import urllib.parse
from bs4 import BeautifulSoup

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

class ShopScraper:
    def __init__(self, public_api):
        """
        Accepts an instance of EtsyPublicAPI to utilize its session and proxy/Datadome settings.
        """
        self.api = public_api

    def get_shop_metrics(self, shop_name):
        """
        Fetches the public shop homepage and extracts Total Sales and Total Reviews.
        Returns a dict: {'shop_name': str, 'total_sales': int, 'total_reviews': int}
        """
        url = f"https://www.etsy.com/shop/{urllib.parse.quote_plus(shop_name)}"
        resp = self.api.session.request("GET", url, headers=self.api.headers, cookies=self.api.cookies)
        
        if resp.status_code != 200:
            print(f"[-] Failed to fetch shop page for {shop_name}. Status Code: {resp.status_code}")
            return None
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Find Total Sales
        total_sales = None
        sales_tag = soup.find('a', href=lambda x: x and x.endswith('/sold'))
        if sales_tag:
            total_sales = _parse_count(sales_tag.text)
            
        # 2. Find Total Reviews
        total_reviews = None
        # Often found in a specific badge or span with "reviews" text
        review_tag = soup.find(attrs={"data-buy-box-region": "reviews"})
        if review_tag:
            total_reviews = _parse_count(review_tag.text)
            
        # Fallback for reviews if data-attribute is missing (e.g., just "(4.2k)")
        if total_reviews is None:
            header = soup.find('div', class_='shop-home-header')
            if header:
                # Look for a string like "(4.2k)"
                match = re.search(r'\(([\d.,]+[km]?)\)', header.get_text())
                if match:
                    total_reviews = _parse_count(match.group(1))

        # Fallback for sales if the shop hides their sold history (the link disappears)
        if total_sales is None:
            header = soup.find('div', class_='shop-home-header')
            if header:
                # Look for "26.8k Sales" or "26.8k sales" across lines
                text = header.get_text(" ", strip=True).lower()
                match = re.search(r'([\d.,]+[km]?)\s*sales?', text)
                if match:
                    total_sales = _parse_count(match.group(1))
                        
        return {
            "shop_name": shop_name,
            "total_sales": total_sales,
            "total_reviews": total_reviews
        }

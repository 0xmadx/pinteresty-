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
        
        # Public tier only. There used to be a fallback to `etsy_private` cookies when
        # the buyer pool was empty — which is exactly the trade D-29 forbids: it spends
        # the one irreplaceable seller account on competitor scraping, the riskiest work
        # in the system, precisely when sessions are already scarce. Better to fetch
        # nothing than to fetch it as the seller.
        resp = self.session_manager.get(url, platform="etsy")
        
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

    def get_shop_listings(self, shop_name, page=1):
        """One page of a shop's listings — the inventory `get_shop_metrics` cannot give.

        Shop totals answer "is this shop growing"; they cannot answer WHICH listing
        grew. That attribution needs per-listing readings over time (D-25), and this is
        the fetch that feeds them.

        Public tier only — a competitor's shop page is public, so per D-29 the seller
        session must never be spent on it.

        Every field is None when it did not parse. A review count that failed to parse
        is unknown, not zero: stored as 0 it would look like a brand-new listing and
        make its next velocity reading enormous (N-02).
        """
        url = (f"https://www.etsy.com/shop/{urllib.parse.quote_plus(shop_name)}"
               f"?page={int(page)}")
        resp = self.session_manager.get(url, platform="etsy")
        if resp.status_code != 200:
            print(f"[-] Failed to fetch listings for {shop_name}: {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        listings, seen = [], set()

        # Shop pages carry listing ids on several elements (the card, its link, its
        # favourite button), so the same listing appears repeatedly. Dedupe on the id
        # and keep the first card that actually has a title.
        for card in soup.select("[data-listing-id]"):
            listing_id = card.get("data-listing-id")
            if not listing_id or listing_id in seen:
                continue

            title_el = (card.select_one(".v2-listing-card__title")
                        or card.select_one("h3")
                        or card.select_one("[data-listing-card-listing-title]"))
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                continue                      # not a real card, just an id-bearing child
            seen.add(listing_id)

            text = card.get_text(" ", strip=True)
            stars = card.select_one("clg-static-review-stars")
            review_count = None
            rating = None
            if stars:
                rating = float(stars["rating"]) if stars.get("rating") else None
                review_count = _parse_count(stars.get("review-count-text") or "")

            price = None
            price_el = card.select_one(".currency-value")
            if price_el:
                with soft_parse("shop.listing_price", shop_name=shop_name,
                                listing_id=listing_id):
                    price = float(price_el.get_text(strip=True).replace(",", ""))

            listings.append({
                "listing_id": listing_id,
                "title": title,
                "price": price,
                "review_count": review_count,
                "rating": rating,
                "is_ad": "Ad from shop" in text,
                "shop_name": shop_name,
            })

        return listings

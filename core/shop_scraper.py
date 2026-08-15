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
        
        # A datadome-refresh hook used to live here, writing the rotated cookie back
        # onto the API object. It called a method that does not exist — every shop
        # fetch raised AttributeError — and it would be pointless now regardless:
        # cookies come from the Redis vault per request, not from an object that
        # outlives the call (D-28). The extension refreshes them at the source.

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

    # A listing's Product.aggregateRating.reviewCount at or above this share of the
    # shop's own total is indistinguishable from the shop figure, so it is refused.
    SHOP_TOTAL_CONTAMINATION_RATIO = 0.9

    def get_listing_outcome(self, listing_id, shop_total_reviews=None):
        """One listing's own review count and rating, from its LD+JSON Product block.

        Verified on the wire 2026-08-15, and the wire is stranger than it looks:

        1. The shop grid carries NO per-listing review counts — zero
           `clg-static-review-stars` elements on a shop page — so this signal costs one
           request per listing and cannot be batched out of the grid.

        2. **`Product.aggregateRating.reviewCount` is not always the listing's.** On
           some pages it is (1, 65, 253); on others Etsy fills it with the SHOP's total.
           Measured: shopflowerlane returned 4580 on 7 of 12 listings against a shop
           showing 4.6k; ARTOFJOYStudio returned 1383 on 2 of 12 against 1.4k. Same
           field, same block, same request — the page simply differs.

        That second one is the dangerous shape: a large, confident, wrong number. Taken
        at face value it hands seven listings the shop's entire review history, and the
        next sweep reads their "velocity" as the shop's growth. Every one of them would
        look like a runaway winner.

        So a count at or above `SHOP_TOTAL_CONTAMINATION_RATIO` of the shop total is
        refused. Proximity rather than equality because the shop page rounds (4.6k ->
        4600 against an exact 4580). The genuine values sit far below the line — 253 of
        1400, 65 of 4600 — so the separation is not delicate. Pass
        `shop_total_reviews` to enable the check; without it the value cannot be
        judged and is returned unguarded.

        Returns None when the block is absent — unknown, never zero (N-02).
        """
        url = f"https://www.etsy.com/listing/{urllib.parse.quote_plus(str(listing_id))}/"
        resp = self.session_manager.get(url, platform="etsy")
        if resp.status_code != 200:
            return None

        for match in re.finditer(
                r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                resp.text, re.IGNORECASE | re.DOTALL):
            with soft_parse("listing.ld_json", listing_id=listing_id):
                data = json.loads(match.group(1).strip())
                for item in (data if isinstance(data, list) else [data]):
                    if not isinstance(item, dict) or item.get("@type") != "Product":
                        continue
                    rating = item.get("aggregateRating") or {}
                    if "reviewCount" not in rating:
                        continue           # a listing with no reviews yet omits it

                    count = int(rating["reviewCount"])
                    if (shop_total_reviews
                            and count >= shop_total_reviews * self.SHOP_TOTAL_CONTAMINATION_RATIO):
                        return {
                            "listing_id": str(listing_id),
                            "total_reviews": None,
                            "rating": None,
                            "basis": "refused_shop_total_contamination",
                            "raw_review_count": count,
                        }
                    return {
                        "listing_id": str(listing_id),
                        "total_reviews": count,
                        "rating": float(rating["ratingValue"]) if rating.get("ratingValue") else None,
                        "basis": "measured",
                    }
        return None

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

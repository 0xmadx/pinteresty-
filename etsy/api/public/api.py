import json
import urllib.parse
from bs4 import BeautifulSoup
import re
import os
from core.session_manager import SessionManager
from core.settings import ScraperConfig

class EtsyPublicAPI:
    def __init__(self):
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'
        }
        
        self.cookies = {}
        if getattr(self.config, 'DATADOME_COOKIE', None):
            self.cookies['datadome'] = self.config.DATADOME_COOKIE

    def get_public_search(self, query, filters: dict = None):
        """Fetches the public search SERP and extracts supply, ranked organic IDs and card metrics.

        Etsy does not ship a `window.__INITIAL_STATE__` blob on this page. The numbers we
        need are split across three places, all of which `parse_search_html` handles:
          * a props JSON in an inline script  -> total supply + the ranked organic id list
          * hidden `<form>` inputs, one per card -> id, title, url, prices, ad/organic flag
          * the card markup itself             -> rating, review count, shop name and age
        Only the first 12 of the 48 page-1 slots are server-rendered; the rest are lazy
        loaded through the `neu/specs/listingCards` POST (see filter_relevant_aftersearch.py).
        """
        filters = filters or {}
        
        # Build a consistent cache suffix based on active filters
        cache_suffix = ""
        if filters:
            sorted_items = sorted(filters.items())
            suffix_parts = [f"{k}_{str(v).lower()}" for k, v in sorted_items]
            cache_suffix = "_" + "_".join(suffix_parts)
            
        cache_file = f"etsy/data/cache/public_search_{query.replace(' ', '_')}{cache_suffix}.json"
        if os.path.exists(cache_file):
            print(f"  [+] Loading public search for '{query}' from cache.")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # Build dynamic URL
        params = {"q": query}
        params.update(filters)
        
        # Explicit is often appended by default on Etsy searches
        if "explicit" not in params:
            params["explicit"] = "1"
            
        url = f"https://www.etsy.com/search?{urllib.parse.urlencode(params)}"
        
        resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)

        if resp.status_code != 200:
            print(f"[-] public search failed: {resp.status_code}")
            return None

        data = self.parse_search_html(resp.text, query)
        if not data:
            return None

        with open(cache_file, "w", encoding="utf-8") as out:
            json.dump(data, out)
        return data

    @staticmethod
    def _parse_count(text):
        """'(4.2k)' -> 4200, '(19.8k)' -> 19800, '(312)' -> 312."""
        if not text:
            return None
        m = re.search(r'([\d.,]+)\s*([km]?)', text.strip().lower().strip('()'))
        if not m:
            return None
        try:
            value = float(m.group(1).replace(',', ''))
        except ValueError:
            return None
        return int(value * {'k': 1_000, 'm': 1_000_000}.get(m.group(2), 1))

    @staticmethod
    def _price_float(text):
        if not text:
            return None
        m = re.search(r'([\d,]+\.?\d*)', text)
        return float(m.group(1).replace(',', '')) if m else None

    def parse_search_html(self, html, query):
        """Turns a raw SERP page into the supply/competition payload. Pure function, no I/O."""
        soup = BeautifulSoup(html, 'html.parser')

        def first_int(pattern):
            m = re.search(pattern, html)
            return int(m.group(1)) if m else None

        # --- Page-level supply signals -------------------------------------------------
        result = {
            "query": query,
            # Total competing listings for the query. This is the free, unlimited
            # equivalent of Marketplace Insights' metered `avg_total_listings`.
            "total_results": first_int(r'"organic_listings_count"\s*:\s*(\d+)'),
            "results_per_page": first_int(r'"result_count"\s*:\s*(\d+)'),
            "current_page": first_int(r'"initial_current_page"\s*:\s*(\d+)'),
            "total_pages": first_int(r'"initial_total_pages"\s*:\s*(\d+)'),
            "organic_listing_ids": [],
            "cards": [],
        }

        # The ranked organic id list for this page, in rank order. The array that sits
        # next to `result_count` is the page-level one; the other matches are per-card
        # analytics payloads holding a single id.
        for m in re.finditer(r'"result_count"\s*:\s*\d+.{0,200}?"listing_ids"\s*:\s*\[([\d,]+)\]', html, re.DOTALL):
            ids = [int(x) for x in m.group(1).split(',') if x.strip()]
            if len(ids) > len(result["organic_listing_ids"]):
                result["organic_listing_ids"] = ids

        # --- Card-level competition signals --------------------------------------------
        # The hidden add-to-cart form nested inside each card carries the clean fields;
        # the surrounding markup carries the social proof. The form has to be read from
        # within the card and not from a global id map: a listing can hold both an
        # organic slot and an ad slot on the same page, and a map would collapse the two.
        for card in soup.select('div.v2-listing-card'):
            lid = card.get('data-listing-id')
            if not lid:
                continue
            meta = {}
            for form in card.find_all('form'):
                inputs = {i.get('name'): i.get('value') for i in form.find_all('input', attrs={'name': True})}
                if 'organic_listings_count' in inputs:
                    meta = inputs
                    break
            text = card.get_text(' ', strip=True)
            stars = card.select_one('clg-static-review-stars')
            age = re.search(r'(\d+)\s+years?\s+on\s+Etsy', text)
            shop = card.select_one('.clickable-shop-name')

            price = meta.get('formatted_discounted_price') or meta.get('formatted_original_price')
            result["cards"].append({
                "listing_id": lid,
                "title": meta.get('listing_title'),
                "url": meta.get('listing_url'),
                "shop_id": card.get('data-shop-id'),
                "shop_name": shop.get_text(strip=True) if shop else None,
                # `listing_source` is Etsy's own label; the visible "Ad from shop" string
                # is the fallback for cards that ship without the hidden form.
                "is_ad": meta.get('listing_source') == 'ads' or 'Ad from shop' in text,
                "shop_years_on_etsy": int(age.group(1)) if age else None,
                "rating": float(stars['rating']) if stars and stars.get('rating') else None,
                "review_count": self._parse_count(stars.get('review-count-text')) if stars else None,
                "price": self._price_float(price),
                "original_price": self._price_float(meta.get('formatted_original_price')),
                "percent_discount": int(meta['percent_discount']) if meta.get('percent_discount') else None,
                "free_shipping": 'Free shipping' in text,
                "star_seller": bool(card.select_one('[data-star-seller-badge]')),
                "image_url": meta.get('listing_image_url'),
            })

        return result if result["total_results"] is not None or result["cards"] else None

    def get_listing_data(self, listing_id):
        """Scrapes a public listing page to extract Tags and Breadcrumb."""
        cache_file = f"etsy/data/cache/public_listing_{listing_id}.json"
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
                
        url = f"https://www.etsy.com/listing/{listing_id}"
        resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)
        
        if resp.status_code == 200:
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            result = {
                "breadcrumb": [],
                "tags": []
            }
            
            # 1. Extract Breadcrumb from LD+JSON
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    if data.get('@type') == 'BreadcrumbList':
                        items = data.get('itemListElement', [])
                        # Sort by position just in case
                        items.sort(key=lambda x: x.get('position', 0))
                        result['breadcrumb'] = [item.get('name') for item in items if item.get('name')]
                except Exception:
                    pass
                    
            # 2. Extract Tags from Listzilla JSON
            for script in soup.find_all('script', type='text/json', attrs={'data-neu-spec-placeholder-data': '1'}):
                try:
                    data = json.loads(script.string)
                    if data.get('spec_name') == 'Listzilla_ApiSpecs_Tags_Landing':
                        tags = data.get('args', {}).get('click_queries', [])
                        # The first 13 are usually the actual tags, the rest are broadened matches
                        result['tags'] = tags[:13]
                except Exception:
                    pass
                    
            with open(cache_file, "w", encoding="utf-8") as out:
                json.dump(result, out)
            return result
            
        return None

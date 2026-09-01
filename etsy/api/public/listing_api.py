import re
import json
from bs4 import BeautifulSoup

from core.guards import soft_parse

def get_listing_data(listing_id, public_api):
    """
    Fetches the raw listing page to extract:
    - shop_id (required for deep_dive_reviews endpoint)
    - favorites
    - in_cart_count
    """
    url = f"https://www.etsy.com/listing/{listing_id}"
    # `cookies=public_api.cookies` was here and EtsyPublicAPI has no `cookies`
    # attribute — an AttributeError on the first line of every call, swallowed by the
    # bare except in master_listing_analyzer, so four analytics modules have been dead
    # for the project's life while appearing to run. The SessionManager injects the
    # profile's own cookies anyway; passing them was never needed.
    resp = public_api.session.request("GET", url, headers=public_api.headers,
                                      platform="etsy")

    if resp.status_code != 200:
        print(f"[-] Failed to fetch listing {listing_id}. Status: {resp.status_code}")
        return None
        
    html = resp.text
    
    # 1. Extract shop_id and shop_name
    shop_id = None
    match = re.search(r'shop_id[\"\'\:\s=]+(\d+)', html.lower())
    if match:
        shop_id = int(match.group(1))
        
    shop_name = None
    name_match = re.search(r'etsy\.com/shop/([^/?\"\'\s]+)', html, re.IGNORECASE)
    if name_match:
        shop_name = name_match.group(1)
        
    # 2/3. Favourites and cart count — threshold-gated badges, so absent means BELOW
    # THE DISPLAY THRESHOLD, never zero (N-02). These used to default to 0, which
    # turned "Etsy did not render a badge" into "nobody wants this". The single
    # `people's carts` wording also missed Etsy's current `In 136 carts`.
    #
    # Parsing lives in `api.parse_listing_live` so there is ONE set of patterns and
    # one canary, shared with the live reader that MCP can actually reach.
    from etsy.api.public.api import parse_listing_live
    live = parse_listing_live(html, listing_id=listing_id)
    favorites = live["favorites"]
    in_cart = live["in_cart"]


    # Extract CSRF token (useful for reviews endpoint)
    csrf_token = None
    csrf_match = re.search(r'<meta name="csrf(?:_nonce|-token)" content="([^"]+)"', html)
    if csrf_match:
        csrf_token = csrf_match.group(1)
        
    # Extract SEO Data (Title and Description)
    title = ""
    description = ""
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if title_match:
        title = title_match.group(1)
        
    desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    if desc_match:
        description = desc_match.group(1)
        
    # Extract exact reviewCount and ratingValue from LD+JSON
    exact_review_count = 0
    rating_value = 0.0
    price = 0.0
    ld_matches = re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)
    for m in ld_matches:
        # Was `except Exception: pass`. A listing page carries several LD+JSON blocks and
        # only one is the Product, so failing on the others is normal — but a change to
        # the Product block used to look identical to those benign misses, leaving price
        # and review count at 0 with nothing said.
        with soft_parse("listing.ld_json", listing_id=listing_id):
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                for item in data:
                    if item.get('@type') == 'Product':
                        rating = item.get('aggregateRating', {})
                        if 'reviewCount' in rating:
                            exact_review_count = int(rating['reviewCount'])
                        if 'ratingValue' in rating:
                            rating_value = float(rating['ratingValue'])

                        offers = item.get('offers', {})
                        if 'lowPrice' in offers:
                            price = float(offers['lowPrice'])
                        elif 'price' in offers:
                            price = float(offers['price'])


    # 5. Extract Live Demand Signals (Urgency Badges) & Parse Integers
    #
    # N-02: these start as None, not 0. A badge renders only above a platform
    # threshold, so its ABSENCE means "we cannot see this listing's daily sales" —
    # not "this listing sold nothing today". Defaulting to 0 made those two
    # indistinguishable, and downstream `daily_sales > 0` checks then took the
    # not-measured case down the same branch as a genuine zero, which is the
    # measured-vs-derived collapse this codebase keeps having to undo.
    #
    # Callers that need a number for arithmetic should coalesce explicitly at the
    # point of use, where the choice is visible.
    demand_signals = []
    daily_sales = None
    daily_views = None
    scarcity_stock = None

    soup = BeautifulSoup(html, 'html.parser')
    for elem in soup.find_all(['span', 'div', 'p']):
        text = elem.get_text(strip=True).replace('\n', ' ')
        t_low = text.lower()
        
        if len(text) < 5 or len(text) > 80:
            continue
            
        is_signal = False
        if "bought this in the last" in t_low:
            is_signal = True
            m = re.search(r'(\d+)\s+people\s+bought', t_low)
            if m: daily_sales = int(m.group(1))
            
        elif "views in the last" in t_low or "viewed in the last" in t_low:
            is_signal = True
            m = re.search(r'(\d+)\+?\s+view', t_low)
            if m: daily_views = int(m.group(1))
            
        elif "in" in t_low and "cart" in t_low and "add" not in t_low:
            is_signal = True
            
        elif "only" in t_low and "left" in t_low:
            is_signal = True
            m = re.search(r'only\s+(\d+)\s+left', t_low)
            if m: scarcity_stock = int(m.group(1))
            
        if is_signal and text not in demand_signals:
            demand_signals.append(text)
            
    return {
        "listing_id": listing_id,
        "shop_id": shop_id,
        "shop_name": shop_name,
        "favorites": favorites,
        "in_cart": in_cart,
        "daily_sales": daily_sales,
        "daily_views": daily_views,
        "scarcity_stock": scarcity_stock,
        "csrf_token": csrf_token,
        "exact_review_count": exact_review_count,
        "rating_value": rating_value,
        "price": price,
        "title": title,
        "description": description,
        "demand_signals": demand_signals
    }

import re
import json

from etsy.api.public.api import EtsyPublicAPI

def get_recent_reviews(listing_id, public_api=None, shop_id=None, csrf_token=None):
    """
    Fetches the deep dive reviews for a listing to calculate Review Velocity.
    Returns a list of review timestamps (epoch).
    """
    if public_api is None:
        public_api = EtsyPublicAPI()
        
    if not shop_id:
        # 1. We need the shop_id. We can get this by fetching the listing page.
        url = f"https://www.etsy.com/listing/{listing_id}"
        resp = public_api.session.request("GET", url, headers=public_api.headers, cookies=public_api.cookies)
        
        if resp.status_code != 200:
            print(f"[-] Failed to fetch listing {listing_id}. Status: {resp.status_code}")
            return []
            
        # Look for shop_id in the raw HTML
        match = re.search(r'shop_id[\"\'\:\s]+(\d+)', resp.text.lower())
        if not match:
            print(f"[-] Could not extract shop_id for listing {listing_id}")
            return []
            
        shop_id = int(match.group(1))
        
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', resp.text)
        if csrf_match:
            csrf_token = csrf_match.group(1)
    
    # 2. Fetch the reviews using the deep_dive_reviews endpoint
    review_url = "https://www.etsy.com/api/v3/ajax/bespoke/member/neu/specs/deep_dive_reviews"
    
    headers = public_api.headers.copy()
    headers.update({
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest",
        # We need a CSRF token. The API class might have one, or we might need to extract it from the listing page.
    })
    
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
        
    payload = {
        "log_performance_metrics": True,
        "specs": {
            "deep_dive_reviews": [
                "Etsy\\Modules\\ListingPage\\Reviews\\DeepDive\\AsyncApiSpec",
                {
                    "listing_id": int(listing_id),
                    "shop_id": shop_id,
                    "scope": "listingReviews",
                    "page": 1,
                    "sort_option": "Recency", # Change from Relevancy to Recency to get the newest!
                    "rating_filter": None,
                    "tag_filters": [],
                    "review_highlight_transaction_id": None,
                    "should_lazy_load_images": False,
                    "should_show_variations": True,
                    "photo_aesthetics_ranking_dataset_version": "v1"
                }
            ]
        },
        "runtime_analysis": False
    }
    
    review_resp = public_api.session.request("POST", review_url, json=payload, headers=headers, cookies=public_api.cookies)
    if review_resp.status_code != 200:
        print(f"[-] Failed to fetch reviews for {listing_id}. Status: {review_resp.status_code}")
        return []
        
    try:
        data = review_resp.json()
    except json.JSONDecodeError:
        print(f"[-] Failed to parse review JSON.")
        return []
        
    timestamps = []
    
    # The response is highly nested. We will extract all created_at timestamps.
    # Usually it's in data['output']['deep_dive_reviews'] -> some HTML block, or it's returned as raw HTML snippet.
    # Wait, the deep_dive_reviews endpoint often returns HTML snippets.
    # Let's just regex search for "data-created-at" or similar standard timestamps in the response.
    raw_str = json.dumps(data)
    
    # Look for standard review date strings or epoch times
    # Actually, the review block in Etsy usually has the exact date text (e.g., "Aug 5, 2026")
    # Let's extract the raw HTML of the reviews and parse it if it returns HTML.
    html_output = ""
    if "output" in data and "deep_dive_reviews" in data["output"]:
        html_output = data["output"]["deep_dive_reviews"]
        
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_output, 'html.parser')
    
    # Review dates are often inside a specific p tag or div.
    # We can look for anything that looks like a date.
    dates = []
    # Using a common class for the review date.
    date_tags = soup.find_all('p', class_='shop2-review-date')
    if not date_tags:
        # fallback
        date_tags = soup.find_all(string=re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}'))
        
    for d in date_tags:
        if hasattr(d, 'text'):
            dates.append(d.text.strip())
        else:
            dates.append(str(d).strip())
            
    return dates

def get_review_details(listing_id, public_api=None, shop_id=None, csrf_token=None):
    """
    Fetches the deep dive reviews and extracts full text and ratings for sentiment analysis.
    Returns a list of dicts: [{'date': str, 'text': str, 'rating': int}]
    """
    if public_api is None:
        public_api = EtsyPublicAPI()
        
    if not shop_id:
        url = f"https://www.etsy.com/listing/{listing_id}"
        resp = public_api.session.request("GET", url, headers=public_api.headers, cookies=public_api.cookies)
        
        if resp.status_code != 200:
            return []
            
        match = re.search(r'shop_id[\"\'\:\s]+(\d+)', resp.text.lower())
        if match:
            shop_id = int(match.group(1))
        
        csrf_match = re.search(r'<meta name="csrf(?:_nonce|-token)" content="([^"]+)"', resp.text)
        if csrf_match:
            csrf_token = csrf_match.group(1)
            
    review_url = "https://www.etsy.com/api/v3/ajax/bespoke/member/neu/specs/deep_dive_reviews"
    headers = public_api.headers.copy()
    headers.update({
        "content-type": "application/json",
        "x-requested-with": "XMLHttpRequest",
    })
    
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
        
    payload = {
        "log_performance_metrics": True,
        "specs": {
            "deep_dive_reviews": [
                "Etsy\\Modules\\ListingPage\\Reviews\\DeepDive\\AsyncApiSpec",
                {
                    "listing_id": int(listing_id),
                    "shop_id": shop_id,
                    "scope": "listingReviews",
                    "page": 1,
                    "sort_option": "Recency",
                    "rating_filter": None,
                    "tag_filters": [],
                    "should_show_variations": True,
                }
            ]
        },
        "runtime_analysis": False
    }
    
    review_resp = public_api.session.request("POST", review_url, json=payload, headers=headers, cookies=public_api.cookies)
    if review_resp.status_code != 200:
        return []
        
    try:
        data = review_resp.json()
    except json.JSONDecodeError:
        return []
        
    html_output = ""
    if "output" in data and "deep_dive_reviews" in data["output"]:
        html_output = data["output"]["deep_dive_reviews"]

    return parse_reviews_html(html_output)


def parse_reviews_html(html_output):
    """Pure HTML → review dicts. Split out of get_review_details so the parse — the part
    that silently biased the flaw analysis — is testable without a network."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_output, 'html.parser')

    reviews = []
    # Since Etsy HTML classes change often, we'll try to find review containers or just extract paragraphs.
    # Usually reviews are in div or li with some review-item class.
    # We will just do a rough extraction of paragraphs that are long enough to be reviews.
    paragraphs = soup.find_all('p')

    star_pattern = re.compile(r'([1-5])\s+out of 5 stars', re.IGNORECASE)

    for p in paragraphs:
        text = p.get_text(strip=True)
        if len(text) > 20 and "out of 5 stars" not in text.lower():
            # A rating is MEASURED or None — never fabricated. The old code defaulted to 5
            # when the star text wasn't found, so a failed parse rated every review 5 and
            # the flaw analysis silently found nothing critical (invariant 1: a plausible
            # wrong number, not an error). Walk up a few ancestors; the star text usually
            # sits in a sibling node (aria/screen-reader span), so an ancestor's subtree
            # text will contain it if it exists at all.
            rating = None
            node = p
            for _ in range(3):
                node = node.parent
                if node is None:
                    break
                m = star_pattern.search(node.get_text(" ", strip=True))
                if m:
                    rating = int(m.group(1))
                    break

            reviews.append({
                "text": text,
                "rating": rating,                                   # None = not parsed
                "rating_basis": "measured" if rating else "unparsed",
                "date": "Recent"
            })

    return reviews

if __name__ == "__main__":
    # Test on a known listing
    print(get_recent_reviews("1370681297"))

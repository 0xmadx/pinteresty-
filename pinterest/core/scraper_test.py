import json
import httpx
from urllib.parse import urlencode
from pathlib import Path

# Load cookies synced from the Chrome extension
COOKIE_FILE = Path("pinterest_cookies.json")

def make_pinterest_request():
    if not COOKIE_FILE.exists():
        print(f"❌ No cookies found at {COOKIE_FILE}. Make sure the extension is running and synced.")
        return
        
    with open(COOKIE_FILE, "r") as f:
        cookie_data = json.load(f)
        
    cookies = cookie_data.get("cookie_json", {})
    
    # Extract the CSRF token from the cookies to use in headers if required by Pinterest
    csrftoken = cookies.get("csrftoken", "")

    # The payload from the .bash file, represented as a Python dictionary
    payload = {
        "options": {
            "url": "/v3/trends/partner/1103382114864552469/available_interests/",
            "data": {
                "available_term_count_threshold": 3,
                "lookback_window": 3,
                "trend_type": 2
            }
        },
        "context": {}
    }

    # URL encode the JSON payload
    encoded_data = urlencode({"data": json.dumps(payload, separators=(',', ':'))})
    
    # Construct the final URL
    base_url = "https://trends.pinterest.com/resource/ApiResource/get/"
    # We add the source_url and data parameters. (Ignoring `_=` timestamp cache buster for now)
    url = f"{base_url}?source_url=/search?country=US&{encoded_data}"

    # Headers based on the .bash file, matching what a real browser sends
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://trends.pinterest.com/search?country=US",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "x-pinterest-appstate": "active",
        "x-pinterest-pws-handler": "trends/search.js",
        "x-pinterest-source-url": "/search?country=US",
        "x-requested-with": "XMLHttpRequest"
    }

    print("🚀 Sending request to Pinterest...")
    
    # Make the GET request
    response = httpx.get(url, headers=headers, cookies=cookies)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("✅ Success!")
        print(json.dumps(response.json(), indent=2)[:500] + "\n...[truncated]...")
    else:
        print("❌ Failed.")
        print(response.text)

if __name__ == "__main__":
    make_pinterest_request()

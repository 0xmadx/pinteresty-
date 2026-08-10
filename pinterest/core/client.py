import json
import httpx
from pathlib import Path

COOKIE_FILE = Path(__file__).parent.parent.parent / "pinterest_cookies.json"

def get_pinterest_cookies():
    """Loads the live synced cookies from the server."""
    if not COOKIE_FILE.exists():
        raise FileNotFoundError(f"Cookie file not found at {COOKIE_FILE}. Make sure the cookie server and Chrome extension are running.")
        
    with open(COOKIE_FILE, "r") as f:
        data = json.load(f)
        return data.get("cookie_json", {})

def get_pinterest_client() -> httpx.AsyncClient:
    """
    Returns an httpx.AsyncClient configured with Pinterest's required 
    anti-bot headers and live cookies.
    """
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
    
    cookies = get_pinterest_cookies()
    
    # CSRF token must also be sent in headers for some POST requests, though GET works without it.
    if "csrftoken" in cookies:
        headers["x-csrftoken"] = cookies["csrftoken"]
        
    client = httpx.AsyncClient(
        base_url="https://trends.pinterest.com",
        headers=headers,
        cookies=cookies,
        timeout=httpx.Timeout(20.0) # Pinterest API can be slow (TTFB)
    )
    
    return client

import json
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

def get_pinterest_cookies():
    """Loads the live synced cookies from the .env file."""
    cookie_str = os.getenv("PINTEREST_COOKIES")
    if not cookie_str:
        raise ValueError("PINTEREST_COOKIES not found in .env. Make sure the cookie server and Chrome extension are running.")
        
    return json.loads(cookie_str)

def get_pinterest_client() -> StealthyFetcher:
    """
    Returns a StealthyFetcher configured with Pinterest's required 
    anti-bot headers. 
    Live cookies from get_pinterest_cookies() should be passed when fetching.
    """
    from scrapling.fetchers import StealthyFetcher
    # Optional: configure proxy or other settings here if needed
    return StealthyFetcher()

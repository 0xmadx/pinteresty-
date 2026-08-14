import json
from core.settings import ScraperConfig
from core.session_manager import SessionManager
from core.cookie_vault import RedisCookieVault

config = ScraperConfig()
vault = RedisCookieVault(config)
session = SessionManager(config)

account = vault.get_valid_account("etsy_private")
profile_id = account.get("profile_id")
csrf = account.get("csrf_token")
print(f"Using Profile: {profile_id}")

resp = session.request(
    "GET", 
    "https://www.etsy.com/api/v3/ajax/bespoke/member/shops", 
    platform="etsy_private",
    headers={"x-csrf-token": csrf} if csrf else {}
)
print("Status:", resp.status_code)
print(resp.text[:1000])

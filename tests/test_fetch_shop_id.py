import json
from core.settings import ScraperConfig
from core.session_manager import SessionManager
from core.cookie_vault import RedisCookieVault

config = ScraperConfig()
vault = RedisCookieVault(config)
session = SessionManager(config)

account = vault.get_valid_account("etsy_private")
profile_id = account.get("profile_id")
print(f"Using Profile: {profile_id}")

resp = session.request("GET", "https://www.etsy.com/your/shops/me/dashboard", platform="etsy_private")
with open("dashboard.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Saved dashboard.html")

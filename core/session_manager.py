import os
from curl_cffi import requests
from core.settings import ScraperConfig
from core.cookie_vault import RedisCookieVault

class SessionManager:
    """
    Manages the curl_cffi session, strictly enforcing the Chrome124 TLS fingerprint
    and automatically injecting the cookies from the Redis Cookie Vault.
    Handles automatic failover if a DataDome block is encountered.
    """
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.vault = RedisCookieVault(config)
        self.rate_limited = 0

    def _build_session(self, user_agent=None) -> requests.Session:
        # Impersonate Chrome 124 to pass TLS fingerprinting checks (Akamai/DataDome)
        session = requests.Session(impersonate=self.config.BROWSER_FINGERPRINT)
        
        # Apply Proxy if configured
        if self.config.USE_PROXY and self.config.PROXY_URL:
            session.proxies = {"http": self.config.PROXY_URL, "https": self.config.PROXY_URL}
            
        # Use provided User-Agent from the actual browser, fallback to hardcoded Chrome 124
        ua_to_use = user_agent if user_agent else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        
        session.headers.update({
            "User-Agent": ua_to_use,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        })
        return session

    def _execute_with_retry(self, method, url, cookies=None, platform="etsy", **kwargs):
        """
        Executes a request. If a 403 or DataDome block occurs, it invalidates the current 
        profile in Redis and grabs a new one to retry automatically (failover).
        """
        for attempt in range(self.config.MAX_RETRIES):
            # 1. Grab a valid account from Redis
            # This will raise ValueError if no valid accounts are found for the platform
            account = self.vault.get_valid_account(platform)
                
            # 2. Build a fresh session with the profile's specific User-Agent to match
            # the browser where the cookies were actually generated.
            profile_ua = account.get("user_agent")
            session = self._build_session(user_agent=profile_ua)
            
            # 3. Inject cookies from Redis
            redis_cookies = account.get("cookies_json", {})
            if isinstance(redis_cookies, dict):
                for k, v in redis_cookies.items():
                    # If it's pinterest, domain should be .pinterest.com, but we default to domain from cookie if possible
                    domain = ".etsy.com" if "etsy" in platform else ".pinterest.com" if "pinterest" in platform else ""
                    session.cookies.set(k, v, domain=domain)
                    
            # 4. Inject endpoint-specific overrides
            if cookies:
                for k, v in cookies.items():
                    domain = ".etsy.com" if "etsy" in platform else ".pinterest.com" if "pinterest" in platform else ""
                    session.cookies.set(k, v, domain=domain)
                    
            # 5. Inject CSRF Token and format Shop ID (ONLY for Private API)
            formatted_url = url
            if platform == "etsy_private":
                shop_id = account.get("shop_id")
                csrf_token = account.get("csrf_token")
                
                if "{shop_id}" in url:
                    if not shop_id:
                        raise ValueError(f"Profile {account['profile_id']} is missing shop_id! Vault Guardian should have caught this.")
                        
                    # Inject shop_id into the URL template
                    formatted_url = url.format(shop_id=shop_id)
                
                if csrf_token:
                    # Update session headers for this specific profile
                    session.headers.update({"x-csrf-token": csrf_token})
                    
            # Execute
            if method.upper() == 'GET':
                response = session.get(formatted_url, **kwargs)
            else:
                response = session.post(formatted_url, **kwargs)
                
            # Check for bot block or auth failure
            # Note: Do not invalidate merely because 'datadome' is in the text, as Etsy includes DataDome JS on valid pages.
            is_blocked = response.status_code in (401, 403, 429) and (
                "datadome" in response.text.lower() or 
                "geo.captcha-delivery.com" in response.text.lower() or 
                response.status_code == 429
            )
            
            if is_blocked:
                if response.status_code == 429:
                    self.rate_limited += 1
                    print(f"⚠️  RATE LIMITED (429) — this is Etsy throttling.")
                else:
                    print(f"Request blocked or unauthorized: {response.status_code} on profile {account['profile_id']} (attempt {attempt + 1}/{self.config.MAX_RETRIES}).")
                
                # IMPORTANT: Mark this profile as invalid in Redis!
                # The scraper will seamlessly grab a different profile on the next attempt.
                self.vault.mark_invalid(platform, account['profile_id'])
                
                import time
                time.sleep(2) # Brief pause before retry
            else:
                return response
                
        # Return the last response even if it failed, so the caller can handle it
        return response

    def get(self, url, cookies=None, platform="etsy", **kwargs):
        return self._execute_with_retry('GET', url, cookies=cookies, platform=platform, **kwargs)
        
    def post(self, url, cookies=None, platform="etsy", **kwargs):
        return self._execute_with_retry('POST', url, cookies=cookies, platform=platform, **kwargs)

    def request(self, method, url, cookies=None, platform="etsy", **kwargs):
        return self._execute_with_retry(method, url, cookies=cookies, platform=platform, **kwargs)


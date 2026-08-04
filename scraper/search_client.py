import time
import random
import urllib.parse
from typing import Dict, Any
from config.settings import ScraperConfig
from core.session_factory import ImpersonatedSession

class SearchClient:
    def __init__(self, session: ImpersonatedSession, config: ScraperConfig):
        self.session = session
        self.config = config

    def get_trending_suggestions(self) -> Dict[str, Any]:
        """Maps to search_suggesstion.py"""
        url = f"{self.config.BASE_URL}{self.config.SUGGEST_ENDPOINT}"
        params = {"dataset": "smu_trending_queries_v3"}
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "referer": f"{self.config.BASE_URL}/?",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        try:
            response = self.session.get(url, params=params, headers=headers)
            return response.json()
        except Exception as e:
            print(f"Error fetching trending suggestions: {e}")
            return {}

    def get_typing_suggestions(self, query: str) -> Dict[str, Any]:
        """Maps to typing_search suggestion.py"""
        params = {
            "extras": '{"expt":"v7_rtn","lang":"en-US","extras":[]}',
            "version": "10_12672349415_19",
            "search_query": query,
            "search_type": "all",
            "pathname": "/search",
        }
        url = f"{self.config.BASE_URL}{self.config.TYPING_SUGGEST_ENDPOINT}"
        headers = {
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "referer": f"{self.config.BASE_URL}/search",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        try:
            response = self.session.get(url, params=params, headers=headers)
            return response.json()
        except Exception as e:
            print(f"Error fetching typing suggestions: {e}")
            return {}

    def search(self, query: str, page: int = 1) -> str:
        """Maps to search.py"""
        url = f"{self.config.BASE_URL}{self.config.SEARCH_ENDPOINT}"
        params = {"q": query, "ref": "search_bar"}
        if page > 1:
            params["page"] = str(page)
            
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "referer": f"{self.config.BASE_URL}/",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }
        try:
            response = self.session.get(url, params=params, headers=headers)
            return response.text
        except Exception as e:
            print(f"Error executing search: {e}")
            return ""

    def simulate_typing(self, query: str):
        """Simulate human-like keystroke delays for autocomplete suggestions"""
        current_query = ""
        for char in query:
            current_query += char
            # Send partial query to suggest endpoint
            self.get_typing_suggestions(current_query)
            # Sleep between 50ms and 200ms
            time.sleep(random.uniform(0.05, 0.2))

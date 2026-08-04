from scraper.search_client import SearchClient
from scraper.parser import SearchParser
from models.schemas import SearchResultPage
from typing import List

class SearchService:
    def __init__(self, client: SearchClient, parser: SearchParser):
        self.client = client
        self.parser = parser

    def full_search_pipeline(self, query: str, pages: int = 1) -> List[SearchResultPage]:
        print(f"Simulating typing for: {query}")
        self.client.simulate_typing(query)
        
        results = []
        for page in range(1, pages + 1):
            print(f"Fetching search results for page {page}")
            html = self.client.search(query, page=page)
            if not html:
                print("Failed to fetch HTML or received empty response.")
                continue
                
            parsed_page = self.parser.parse_search_results(html, page_number=page)
            results.append(parsed_page)
            
        return results

    def quick_search(self, query: str) -> SearchResultPage:
        html = self.client.search(query)
        return self.parser.parse_search_results(html)

    def discover_queries(self, seed: str) -> List[str]:
        # Using the typing suggestions to find related queries
        response = self.client.get_typing_suggestions(seed)
        
        suggestions = []
        if isinstance(response, dict) and "results" in response:
            for res in response["results"]:
                if "query" in res:
                    suggestions.append(res["query"])
                    
        return suggestions

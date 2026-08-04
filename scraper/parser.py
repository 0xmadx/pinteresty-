from bs4 import BeautifulSoup
from models.schemas import SearchResultItem, SearchResultPage
from typing import Dict, Any, List

class SearchParser:
    def parse_search_results(self, html: str, page_number: int = 1, selector_config: Dict[str, str] = None) -> SearchResultPage:
        if selector_config is None:
            # Typical selectors for Etsy search results (might need adjusting)
            selector_config = {
                "result_container": "li.wt-list-unstyled",
                "title": "h3.v2-listing-card__title",
                "url": "a.listing-link",
                "price": "span.currency-value",
                "shop_name": "p.v2-listing-card__shop-name"
            }
            
        soup = BeautifulSoup(html, 'lxml')
        items = []
        
        containers = soup.select(selector_config["result_container"])
        for container in containers:
            title_el = container.select_one(selector_config["title"])
            url_el = container.select_one(selector_config["url"])
            price_el = container.select_one(selector_config["price"])
            shop_el = container.select_one(selector_config["shop_name"])
            
            # Use alternative fallback selectors if standard ones fail
            if not title_el:
                title_el = container.select_one("h2")
            if not url_el:
                url_el = container.select_one("a")
                
            if title_el and url_el:
                items.append(SearchResultItem(
                    title=title_el.text.strip(),
                    url=url_el.get('href', ''),
                    price=price_el.text.strip() if price_el else None,
                    shop_name=shop_el.text.strip() if shop_el else None
                ))
                
        return SearchResultPage(items=items, page_number=page_number)

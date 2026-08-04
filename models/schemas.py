from pydantic import BaseModel
from typing import List, Optional

class SearchResultItem(BaseModel):
    title: str
    url: str
    price: Optional[str] = None
    shop_name: Optional[str] = None

class SearchResultPage(BaseModel):
    items: List[SearchResultItem]
    page_number: int

class SuggestionItem(BaseModel):
    text: str
    
class TrendingQuery(BaseModel):
    query: str

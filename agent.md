# Etsy Data Extraction Agent Documentation

This project is a heavily generalized, anti-bot scraping architecture designed to fetch massive amounts of raw data from Etsy's backend endpoints while entirely bypassing DataDome and Akamai protections.

This workspace is explicitly prepared for downstream AI agents or data pipelines to consume raw JSON/HTML data. 

## Core Architecture Overview

We use a completely generalized Endpoint Engine. Rather than hardcoding Python requests for every single Etsy URL, the engine dynamically translates raw cURL commands from your browser into execution templates, handles dynamic cookie injection, and executes them flawlessly.

1. **`SessionManager` (`src/core/session_manager.py`)**
   - Automatically polls a local Cookie Server to retrieve a valid DataDome bypass cookie.
   - Bootstraps a `curl_cffi` Impersonated Session with TLS/JA3 fingerprints exactly matching Chrome 124 on Windows.
   - Strips dangerous headers (`sec-ch-ua`) that trigger DataDome blocks.

2. **`EndpointManager` (`src/endpoints/manager.py`)**
   - Scans the `inputs/curl_commands/` folder for `.py` files containing raw cURL commands.
   - Parses the cURL strings and maps them into dynamic templates inside `inputs/registry.json`.

3. **`EndpointExecutor` (`src/services/executor.py`)**
   - Uses the `SessionManager` to execute the registered endpoints.
   - Automatically handles dynamic payload injection (e.g., dynamically changing the search query, pagination, etc.).
   - Saves 100% of the raw output (JSON/HTML) directly to the `data/raw/` directory.

---

## 📂 The `inputs/curl_commands/` Folder (Add Your Endpoints Here!)

To add a new data source to this scraper, you **do not need to write any Python code**.
Simply go to your browser, right-click an Etsy Network request, select **Copy as cURL (bash)**, and paste it into a `.py` file inside `inputs/curl_commands/`.

### Currently Registered Endpoints:

#### 1. `filter_new` & `filter_relevant_aftersearch` (Search Grid)
* **What it is**: The internal `listingCards` POST endpoint that generates the massive search grid.
* **Raw Output**: `data/raw/filter_new_listingCards.json`
* **Data Contained**: Total market size (`organic_listings_count`), hidden ad spend intel (`listing_source="ads"`), grid placement rank, and exact pricing/discount logic.

#### 2. `search` (Main HTML Search)
* **What it is**: A standard GET request to `www.etsy.com/search`.
* **Raw Output**: `data/raw/search_search.html`
* **Data Contained**: The raw HTML of the search page.

#### 3. `search_suggesstion` (Trending Queries)
* **What it is**: The `smu_trending_queries_v3` GET endpoint.
* **Raw Output**: `data/raw/search_suggesstion_true.json`
* **Data Contained**: Array of highly searched, trending long-tail keywords. 

#### 4. `typing_search suggestion` (Autocomplete)
* **What it is**: The `suggestions_ajax.php` GET endpoint triggered when a user types in the search bar.
* **Raw Output**: `data/raw/typing_search suggestion_suggestions_ajax.php.json`
* **Data Contained**: Ranked autocomplete suggestions based on search volume.

#### 5. `reviews` & `reviews_seconad` (Deep Dive Reviews)
* **What it is**: The internal POST endpoint for fetching paginated listing reviews.
* **Raw Output**: `data/raw/reviews_deep_dive_reviews.json`
* **Data Contained**: Buyer profiles, review dates (useful for sales velocity calculations), and long-tail keyword sentiment.
* *Note*: This endpoint supports dynamic payload injection via `src/services/review_service.py` to paginate through thousands of reviews safely with anti-ban randomized delays.

#### 6. Single Listing Extraction (`SearchClient.get_listing`)
* **What it is**: A utility in `src/parsers/search_client.py` that takes any listing URL and fetches the raw HTML using the bypass session.
* **Raw Output**: `data/raw/single_listing_<id>.html`
* **Data Contained**: The raw listing HTML, which contains hidden bottom tags, H1 keyword stuffing, and Google JSON-LD Structured Product Data.

---

## 🚀 Execution & Testing

### The Master Script (`main.py`)
Run `main.py` in the root directory to execute the entire batch pipeline.
It will automatically scan `inputs/curl_commands/`, build the `registry.json`, execute every single endpoint, and dump the fresh raw data into `data/raw/`.

```bash
python main.py
```

### Dedicated Pipeline Tests (`tests/`)
If you only want to hit specific endpoints to test their raw output without running the master script, you can run the dedicated test scripts:

* `python tests/test_suggestions.py`
* `python tests/test_search_grid.py`
* `python tests/test_single_listing.py`
* `python tests/test_reviews.py`

*(All of these tests will output their data straight to `data/raw/`)*

---

## 🔗 The Pipeline Architecture (`src/pipelines/`)

While the endpoints are isolated and "dumb" (simply fetching raw data), we have scaffolding for orchestrating complex tasks. 

**`src/pipelines/keyword_discovery_pipeline.py`**
Demonstrates the separation of concerns. Instead of building a massive, tangled script, a pipeline orchestrates the flow of data:
1. Calls the `Suggestions` endpoint.
2. Feeds the output into the `Search Grid` endpoint.
3. Takes the top listings from the Grid and feeds them into the `Single Listing` fetcher.

This architecture ensures that if Etsy changes a single endpoint, you only have to update its cURL file, and the entire pipeline continues to function perfectly.
# Etsy Omni-Channel Architecture Master Document

## 1. The Ultimate Goal
The goal of this system is to mathematically remove all guesswork from e-commerce on Etsy. It is an end-to-end intelligence machine designed to:
1. **Discover** hidden demand via the Private API (Search Volume, CVR, Pricing).
2. **Analyze** the supply via the Public API (Saturation, Quality, Geo-monopolies).
3. **Arbitrage** the gap by finding explicit loopholes (e.g., High demand, but no fast shipping).
4. **Validate** the financials by extracting live cart data and estimating revenue.
5. **Generate** invincible listings by algorithmically stealing the best SEO tags from the most successful competitors.
6. **Predict** the future by injecting Pinterest top-of-funnel consumer behavior graph data into Etsy's bottom-of-funnel arbitrage pipelines.

---

## 2. Core Infrastructure (The Engines)

### The Private Demand Engine
* **Where:** `etsy/api/private/` and `etsy/engines/private_recursive_spider.py`
* **What:** Bypasses UI limitations to access Etsy's hidden backend APIs (`chart-series-data`, `results-data`).

### The Core Infrastructure
* **Where:** `core/session_manager.py`, `core/cookie_server.py`, `core/endpoints_manager.py`, `core/graph_db.py`
* **What:** The base operating system of the scraper.
* **How:** Manages live cookie injection, handles Datadome bypasses, and maintains a local Graph Database (`graph_db.py`) to map out how different niches connect to each other.

### The Automated Anti-Bot Bridge (Chrome Extension)
* **Where:** `chrome_extension/background.js` and `core/cookie_server.py`
* **What:** The ultimate bypass tool for Etsy's DataDome firewall.
* **How:** A custom Chrome extension running in your browser automatically detects whenever Etsy generates a new `datadome` clearance cookie. It instantly syncs that fresh token via HTTP POST to the local Python FastAPI server (`cookie_server.py`), keeping the scrapers alive infinitely without manual intervention.

### The Universal Public API
* **Where:** `etsy/api/public/api.py`, `listing_api.py`, `reviews_api.py`
* **What:** A universal scraper that bypasses DataDome to hit Etsy's public frontend.
* **How:** Uses rotating headers and custom cookie payloads to act as a human browser. Accepts raw payload dictionaries. Captures live typing suggestions and zero-state trending autocomplete endpoints.
* **The Genius Move (Calibration):** The system calibrates the "Free" public supply count (`organic_listings_count` from `Etsy.Context` scripts) against the Metered private supply count (`avgTotalListings`) to calculate a mathematical ratio (e.g. Free = 1.256 * Metered). This allows you to scrape infinite supply data for free without burning backend quotas.
* **The Lazy-Load Bypass:** Etsy only renders 12 cards in the SERP HTML to save costs. The API forces Etsy to hand over ranks 13-48 by intercepting the `Search2_ApiSpecs_LazyListingCards` POST request using the hidden `x-csrf-token` and `x-page-guid`.

### The Hybrid Arbitrage Engine
* **Where:** `etsy/engines/master_arbitrage.py`
* **What:** The connective tissue that links Private Demand to Public Supply.
* **How:** Scans across 7 dimensions (Geographic, Format, Quality, Feature, Occasion, Color, and Shipping Speed) to find 0% saturation loopholes.
* **Why:** To guarantee that you are launching a product with zero actual competition in its specific feature bracket.

---

## 3. The 10 Workflows (Detailed Breakdown)

### The Analytics & Financial Trackers
* **[W1] Grid Analytics Pipeline:** 
  * **Where:** `etsy/analytics/grid_analytics.py`
  * **What:** Scrapes top listings for a query and calculates their Lifetime Estimated Sales, **Estimated Views** (by injecting the exact CVR from the Private API), and "In Cart" intent.
* **[W2] Single Listing Analytics:** 
  * **Where:** `etsy/analytics/single_listing_analytics.py`
  * **What:** Sniper tool for deep-diving into one specific competitor's listing page.
  * **How:** Rips open the hidden `application/ld+json` block to extract the exact, unrounded decimal `reviewCount` and uses Regex to parse out the live `"20+ in cart"` text nodes. It then calculates precise **Estimated Views** by dividing the Ratio-Estimated Sales by the keyword's true Conversion Rate.
* **[W3] Shop Analytics Pipeline:** 
  * **Where:** `etsy/analytics/shop_analytics.py`
  * **What:** Extracts total sales, reviews, and age of a competitor's shop.
* **[W3.5] Daily Tracker Pipeline:** 
  * **Where:** `etsy/analytics/daily_tracker.py` & `etsy/analytics/tracking_data.json`
  * **How (The Math):** By scraping a shop's Total Sales today and comparing it to yesterday, it calculates the **Daily Sales Delta** (exact items sold in 24 hours), completely bypassing lifetime estimates.
* **[W3.6] The Ratio Estimator:** 
  * **Where:** `etsy/analytics/ratio_estimator.py`
  * **How (The Math):** Etsy hides listing sales, but exposes Shop Sales. The engine calculates the **Sales-to-Review Ratio** (Total Shop Sales / Total Shop Reviews) and multiplies it by a single listing's reviews to estimate its exact lifetime sales.
* **[W4] Sentiment Analytics Pipeline & AI Review Mining:** 
  * **Where:** `etsy/analytics/sentiment_analytics.py`, `etsy/api/public/reviews_api.py`, & `core/llm_client.py`
  * **How (Velocity):** Targets the `Etsy\Modules\ListingPage\Reviews\DeepDive\AsyncApiSpec` internal system. It forces a `"Recency"` sort, extracts the raw backend HTML block, and parses exact `shop2-review-date` timestamps to calculate if a product is "DEAD" or "HOT".
  * **How (AI Sentiment):** It extracts the text of all negative reviews (1-3 stars) and pipes them directly into the **DeepSeek AI API** (`core/llm_client.py`). DeepSeek acts as an automated product analyst, instantly synthesizing hundreds of complaints into a concise "Top 3 Pain Points" report.
  * **Why:** To figure out exactly what buyers love (to copy), what they hate (to fix and advertise as an improvement in your own product), and to prove sales velocity.
* **[W5] SEO Analytics Pipeline:** 
  * **Where:** `etsy/analytics/seo_analytics.py`
  * **What:** Rips the titles, materials, and tags from a single listing to reverse-engineer a specific competitor's ranking strategy.

### The Private Discovery Workflows
* **[W6] Private Comparison Pipeline:** 
  * **Where:** `etsy/engines/private_comparison.py`
  * **What:** Bulk compares a list of keywords against each other to instantly see which has the highest demand-to-supply ratio.
* **[W6.5] SSR Graph & Private Scoring:** 
  * **Where:** `etsy/engines/ssr_graph_pipeline.py` & `private_scoring_pipeline.py`
  * **What:** Deep pipelines for scoring niches mathematically on the backend.
* **[W6.8] The Category Taxonomy Trending Engine:** 
  * **Where:** `etsy/api/private/api.py` (`get_trending_terms`)
  * **What:** Pulls the top trending, high-volume keywords for an entire global Category without consuming daily rate-limit quotas.
* **[W7] Private Recursive Spider & Semantic Mapper:** 
  * **Where:** `etsy/engines/private_recursive_spider.py`
  * **What:** Crawls the "Related Searches" graph using the LLM Semantic Edge node mapper to laterally jump across micro-niches.
* **[W8] Private Product Blueprint:** 
  * **Where:** `etsy/engines/private_blueprint.py`
  * **What:** Extracts the absolute truth (CVR, exact buyer prices) for a single keyword to verify the exact price point you need to sell at.
* **[W9] Master Niche Finder (The Ultimate Engine):** 
  * **Where:** `etsy/engines/master_niche_finder.py`
  * **What:** Connects W6, W7, and W8 into an autonomous loop to automatically find winning niches with zero human input.

### The Content Generation Workflow
* **[W10] Triple-Pass Listing Generator:** 
  * **Where:** `etsy/generators/listing_generator.py`
  * **What:** Hits the API 3 times (Evergreen/Most Relevant, Trending/Newest, Customer Favorites/Highest Reviews) to algorithmically blend the best tags into a mathematically perfect Listing Title & Tag matrix.

---

## 4. The Master SEO Strategy (The Operator Playbook)
Located in `docs/plane_seo brainstrome.md`, this is the grand strategy that governs how all the above pipelines are actually used in sequence to generate revenue.
1. **Phase 1 (Pick the Niche):** Use `get_trending_terms` (W6.8) to find identity-based niches without burning quota.
2. **Phase 2 (Catch the Trend):** Diff the autocomplete suggestions (W1) weekly. When a keyword newly appears, it's early demand. Launch 6-8 weeks before the peak.
3. **Phase 3 (Build Corpus):** Use `A-Z Append`, the `Suggestion LLM` (W7), and mine competitor tags (W5).
4. **Phase 4 (Find the Gap):** Search for a "Weak SERP": high live demand (carts), low supply, and where the top 10 competitors **don't** have the exact query phrase in their title.
5. **Phase 5 & 6 (Build & Launch):** Fully automated via `etsy/generators/listing_generator.py`. This script mathematically scores the "SERP Gap" and then auto-generates the listing by blending consensus tags from Evergreen (Relevancy), Trending (Newest filter), and Top-Rated (Highest Reviews filter) competitors into the exact 140-char Title and 13-Tag format required to rank on both Etsy and Google.

---

## 5. The Pinterest Synergy (The Predictive Layer)
The Etsy API provides Bottom-of-Funnel validation (what is selling *today*). The isolated Pinterest pipelines provide Top-of-Funnel prediction (what will sell *in 3 months*). By merging the two systems, we supercharge the Etsy pipelines:

1. **Supercharging [W7] The Spider Graph:** Currently, the `private_recursive_spider.py` uses Claude LLM to guess semantic relationships between keywords. By connecting Pinterest's pre-computed **383-Category DAG Graph** (Pinterest Tool #9), we can perfectly map aesthetic niches without LLM hallucinations.
2. **Supercharging [W10] Listing Generation:** We can dynamically inject Pinterest's **Demographics** (Tool #6) and **Topic Clusters** (Tool #1) directly into the 13 Etsy Tags, capturing audiences searching by aesthetic vibe (e.g., "PNW aesthetic") instead of just literal product names.
3. **Supercharging The Arbitrage Engine:** The `master_arbitrage.py` calculates Color Arbitrage. By pulling the **Dominant Color** from Pinterest's featured topics (Tool #7), we can perfectly align our product color launches with what the internet is visually demanding right now.
4. **Automating Launch Timing:** Instead of guessing when to launch based on Phase 2 of the Playbook, we can feed Pinterest's precise **takeoff_timestamp_millis** (Tool #2) directly into the Etsy system to trigger the `listing_generator.py` exactly 6 weeks before a trend goes viral.
* **The Database Handoff:** Pinterest's Demographics, Dominant Colors, and Takeoff Timestamps are saved by the Pinterest Agent directly into the `trends` table in the Etsy `market_intelligence.db` SQLite database.

## 6. The Central Intelligence Database (The Unifier)
**Where:** `core/database.py`  
**What:** The `market_intelligence.db` SQLite database is the central nervous system of the entire architecture. It perfectly bridges the gap between the Private API, the Public API, DeepSeek LLM, and the external Pinterest Agent.

It permanently solves 5 historical data silos:
1. **The Volume Silo:** `private_blueprint.py` writes exact Demand and True CVR to the `keywords` table. The Hybrid Arbitrage Engine reads this to calculate the Arbitrage Gap automatically without manual data entry.
2. **The Pricing Silo:** `private_blueprint.py` writes the exact median price *buyers actually pay* to the database. `grid_analytics.py` reads this to instantly flag if current public competitors are overpricing.
3. **The AI Flaw Silo:** `sentiment_analytics.py` pipes negative reviews into DeepSeek and writes the Top 3 Flaws to the `listings` table. The Listing Generator pulls these flaws automatically to write titles/tags that boast about solving those exact flaws.
4. **The Cross-Agent Silo (Pinterest):** The separate Pinterest AI Agent (Claude Code) writes trend aesthetics directly to the `trends` table. The Etsy Arbitrage Engine reads from this exact same table to sync the data.
5. **The Sales Velocity Silo:** `grid_analytics.py` calculates Estimated Views and Lifetime Sales and writes them to the `listings` table, where the Arbitrage Engine pulls them for the final report.

---

## 7. The Unified Data Flow (Relations)
1. **PREDICTION (Pinterest):** Pinterest detects a momentum spike (+75% MoM) for "Coquette Room Decor" and provides the takeoff timestamp and dominant color (Pink).
2. **DISCOVERY (W9 -> W7):** The Etsy Master Niche Finder maps the keyword and traverses the semantic graph.
3. **ARBITRAGE (Hybrid Engine):** The engine tests the keyword on Etsy and discovers a 0% saturation loophole for "Pink" + "Fast Shipping".
4. **VALIDATION (W1):** The Grid Analytics pipeline verifies that the few existing listings have massive "20+ in cart" intent.
5. **LAUNCH (Etsy):** The Listing Generator writes a title/tag combo optimizing for "Pink Coquette Halloween", automatically injecting the exact 3 DeepSeek flaws to solve.

---

## 8. The Anti-Bot & Cookie Sync System (Instructions for Claude Code)
**Where:** `chrome_extension/` and `core/cookie_server.py`  
**What:** Etsy (DataDome) and Pinterest have extremely strict anti-bot systems. We completely bypass this using a "Browser-to-Backend Relay".

### How It Works:
1. **The Chrome Extension (Keep-Alive System):** A custom Chrome Extension runs in the background of the user's browser. It features an "Auto-Refresh Alarm" that silently reloads active Etsy and Pinterest tabs every 4 minutes. This forces DataDome/Pinterest to constantly issue fresh, human-validated cookies.
2. **The Intercept:** The extension intercepts these fresh cookies the second they are generated.
3. **The FastAPI Relay:** The extension makes a silent POST request to a local FastAPI server (`core/cookie_server.py`) running on `http://localhost:8000/update-cookie`.

### How Claude Code Should Access Pinterest Cookies:
* **DO NOT** attempt to scrape Pinterest using Playwright or headless browsers. You will get blocked.
* **DO NOT** ask the user to manually copy/paste cookies.
* The `cookie_server.py` automatically detects Pinterest cookies from the extension and saves them directly to `pinterest_cookies.json` in the root directory.
* **For Claude Code:** Simply read `pinterest_cookies.json` and inject those headers into standard `requests.get()` calls to the Pinterest API. The cookies will always be fresh as long as the user has a Pinterest tab open.

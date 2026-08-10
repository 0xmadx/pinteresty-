# Etsy Engines Layer

This directory contains the "Master Engines"—the high-level orchestrators that chain multiple scraping pipelines and API endpoints together to automate large-scale arbitrage analysis. 

Rather than doing one single task (like scraping a review), these engines execute full end-to-end workflows and feed the final synthesized data directly into `market_intelligence.db`.

## 1. `master_arbitrage.py` (The Hybrid Engine)
This is the holy grail script of the architecture. It maps **Private Demand** directly against **Public Supply**.
* **How It Works:**
  1. Pulls the true Search Volume and CVR from the Private API.
  2. Pulls the exact Public Competitor count.
  3. Calculates the absolute "Arbitrage Gap" (Demand vs Supply).
  4. Synthesizes a **7-Dimensional Arbitrage Matrix** (Format, Geographic, Quality, Occasion, Feature, Shipping, Color) to pinpoint exactly *why* a niche has a gap.
* **Output:** Generates a Go/No-Go Arbitrage Report for a specific keyword.

## 2. `master_listing_analyzer.py` (The URL X-Ray Tool)
A utility script designed for rapid competitor analysis.
* **Input:** Any standard Etsy listing URL.
* **How It Works:**
  1. Parses the 10-digit listing ID from the URL.
  2. Sequentially executes the `SingleListingPipeline`, `SentimentAnalyticsPipeline` (DeepSeek), and `SEOAnalyticsPipeline`.
  3. Pulls the freshly updated data directly from `market_intelligence.db` to print a unified, 360-degree breakdown of the competitor's exact sales, velocity, SEO tags, and AI-identified product flaws.

## 3. `private_blueprint.py` (The Broad Niche Finder)
The primary entry point for discovering "Blue Ocean" keywords.
* **How It Works:**
  1. Uses the Private API's autosuggest endpoint to recursively generate thousands of keyword ideas.
  2. Automatically queries the Private API to fetch the hidden `search_volume` and `query_cvr` for every single keyword.
* **Output:** Streams the highest-converting, highest-volume keywords directly into the `keywords` table in `market_intelligence.db`.

## 4. `master_niche_finder.py` & `ssr_graph_pipeline.py` (Semantic Mappers)
These engines traverse Etsy's internal graph to build maps of related keywords.
* **How It Works:** They scrape the "Related Searches" and "Similar Items" metadata to branch out from a seed keyword (e.g., mapping "leather journal" to "rustic mens diary").

## 5. Private Scoring Utilities (`private_recursive_spider.py`, `private_scoring_pipeline.py`, `private_comparison.py`)
Modular scripts that power the `private_blueprint.py` engine, handling the logic for aggressively crawling autosuggestions and scoring/comparing them against standard metrics.

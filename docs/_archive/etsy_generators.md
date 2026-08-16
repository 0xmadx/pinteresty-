# Etsy Generators Layer

This directory contains the automated content creation scripts. It represents the final step of the Arbitrage Pipeline: taking the raw data we extracted and turning it into ready-to-publish, optimized Etsy listing assets.

## 1. `listing_generator.py` (The SEO Copywriter)
An AI-powered generator that builds a fully optimized Etsy listing blueprint from scratch by leveraging the competitor intelligence we scraped.

* **Purpose:** Once we have identified a "Blue Ocean" keyword (using the `engines`) and identified competitor flaws (using the `analytics` / DeepSeek), this script generates a superior Etsy listing to capture that market share.
* **How It Works:**
  1. Pulls the target keyword's exact 13 Tags and Materials (harvested by `seo_analytics.py`).
  2. Ingests the competitor's biggest flaws (identified by DeepSeek in `sentiment_analytics.py`).
  3. Uses an LLM to automatically generate a highly optimized **Title**, an engaging **Description** (that specifically solves the competitor's flaws), and a finalized list of 13 **Tags**.
* **Output:** A complete, copy-pasteable text package that you can use to immediately launch a superior product listing on Etsy, perfectly engineered to rank on Page 1.

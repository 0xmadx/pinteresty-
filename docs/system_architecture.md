# System Architecture

## Core Engine
- session_manager.py: spoofs Chrome 124 TLS and injects DataDome cookies.

## Private Graph Crawler
- Uses ssr_graph_pipeline.py to traverse the keyword graph.

## Public Scraper
- Uses raw endpoints to fetch data without auth.

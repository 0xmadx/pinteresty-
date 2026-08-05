# Developer Guide

To run the graph crawler:
python private/pipelines/ssr_graph_pipeline.py
"@

    ".agents\skills\etsy_architecture\SKILL.md" = @"
---
name: etsy_scraper_context
description: Master context for the Etsy scraper project architecture.
---
# Etsy Scraper Architecture Context

When working on this project, ALWAYS remember the following folder structure:
- core/: Shared logic (session_manager, config)
- private/: Authenticated dashboard scraper (graph DB, SSR extraction)
- public/: Unauthenticated public scraper

Do not put files in src/ or data/ at the root. Everything belongs in its respective pillar.

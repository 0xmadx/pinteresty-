# Etsy Private API Layer

This directory contains the highly specialized clients designed to interact with Etsy's **Internal Private APIs** (the backend endpoints used by the Etsy iOS/Android apps and internal tools). 

Unlike the Public API, the Private API returns highly accurate, JSON-structured backend metrics that are completely hidden from normal website visitors.

## 1. `api.py` (The Core Private Client)
The central `EtsyPrivateAPI` class.
* **Purpose:** Imitates internal Etsy client requests using `tls_client` to bypass standard TLS-fingerprinting blocks.
* **Key Endpoints Targeted:**
  * **Search Autosuggest:** To find hidden "Blue Ocean" keyword derivatives before they become mainstream.
  * **Search Volume & Analytics:** Bypasses public data to pull the exact `search_volume` and `query_cvr` (Conversion Rate) metrics for a keyword straight from Etsy's backend.
* **Auth Requirement:** Relies on the `x-api-key` (the hardcoded client ID used by Etsy apps) rather than a DataDome browser cookie.

## 2. `registry.json`
A cached database of known Private API endpoints, query structures, and required GraphQL payload schemas. This ensures the `api.py` client constructs its POST payloads exactly how the authentic Etsy internal apps do.

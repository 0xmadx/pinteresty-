# Etsy Niche Decision Machine - Architecture Visualization

This document provides a visual representation of the updated, deadlock-free architecture, specifically illustrating the flow of authentication data (Cookies, CSRF Tokens, Shop IDs, and User-Agents) from the Chrome Browser all the way to the Etsy API.

## Data Flow Diagram

```mermaid
sequenceDiagram
    participant B as Chrome Browser (RDP)
    participant E as Chrome Extension
    participant G as Go Cookie Server (Docker)
    participant R as Redis Vault (Docker)
    participant P as Python SessionManager (Docker)
    participant A as Python EtsyPrivateAPI
    participant S as Etsy Servers (DataDome)

    %% Phase 1: Harvesting
    Note over B, R: Phase 1: Secret Harvesting
    B->>S: User logs into Etsy
    S-->>B: Returns Session Cookies
    B->>E: User browses dashboard
    E->>B: Scrape `shop_id` from URL
    E->>B: Scrape `x-csrf-token` from HTML/Headers
    E->>G: POST /update_cookie (Payload: Cookies, shop_id, csrf, user_agent)
    G->>R: HSET cookie:etsy_private:{profile_id}
    Note right of G: Go Server sanitizes and formats the payload
    G->>R: SADD valid_profiles:etsy_private {profile_id}

    %% Phase 2: Execution
    Note over R, S: Phase 2: Dynamic Execution
    A->>P: request(GET, "/api/v3/ajax/bespoke/shop/{shop_id}/...")
    P->>R: SRANDMEMBER valid_profiles:etsy_private
    R-->>P: Returns {profile_id}
    P->>R: HGETALL cookie:etsy_private:{profile_id}
    R-->>P: Returns Vault Profile (Cookies, shop_id, csrf, user_agent)
    
    %% Phase 3: Injection & Disguise
    Note over P, A: Phase 3: Dynamic Injection
    P->>P: Replaces "{shop_id}" in URL with profile's shop_id
    P->>P: Instantiates curl_cffi Session (Chrome 124 TLS Fingerprint)
    P->>P: Sets Header ["User-Agent"] = profile's user_agent
    P->>P: Sets Header ["x-csrf-token"] = profile's csrf
    P->>P: Loads profile's Cookies into CookieJar
    
    %% Phase 4: Request
    P->>S: GET formatted_url (Perfectly disguised request)
    S-->>P: 200 OK (DataDome bypassed)
    P-->>A: Returns JSON Response
```

### Key Architectural Fixes Visualized Here:
1. **No Circular Dependency:** The Python Scraper (`EtsyPrivateAPI`) no longer attempts to scrape the dashboard for `shop_id`. It relies entirely on the Chrome Extension to provide it.
2. **Dynamic URL Formatting:** The URL template contains `{shop_id}`. The `SessionManager` performs a string replacement right before sending the request, matching the exact profile pulled from the database.
3. **Perfect Disguise:** By saving the `user_agent` alongside the cookies in Phase 1, the `SessionManager` in Phase 3 can perfectly mimic the exact browser that generated the cookies, preventing TLS/User-Agent mismatch detection by DataDome.

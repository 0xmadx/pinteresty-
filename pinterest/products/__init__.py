"""Standalone Pinterest products — `trends.pinterest.com` as its own data source.

Nothing in this package imports from `public/`, `private/` or `core/`, and nothing here
produces an Etsy-shaped record. Every module answers a question that stands on its own:

    1. keyword_research   what should anyone write / pin / bid on, in any niche
    2. content_calendar   when does interest actually take off, and when to publish
    3. ad_targeting       which Pinterest Ads interest x age x gender is moving
    4. market_intel       who owns the clicks in a category, and the 383-node taxonomy
    5. history            the weekly archive Pinterest itself does not offer
    6. audience           who searches for a term, by age and gender
    7. moodboard          what a trend looks like — pins, colours, palette
    8. alerts             what changed since last week, as a monitorable feed

The only shared dependency is `pinterest.endpoints` (the API client, the series store and
the local-math derivations), so any one module can be lifted out on its own.
"""

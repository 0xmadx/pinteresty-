---
description: Can print-on-demand serve this Etsy term profitably? Price ceiling + lead time.
argument-hint: <search term>
allowed-tools: Bash(.venv/Scripts/python.exe -m etsy.analytics.pod_check:*)
---

Run the POD viability check for the term: **$ARGUMENTS**

```bash
.venv/Scripts/python.exe -m etsy.analytics.pod_check "$ARGUMENTS"
```

Then read the result back to the operator, and be careful about three things.

**The ceiling is the number that matters, and it comes off page one.** Etsy's
`search_term_median_price` band is market-wide across every listing; the listings
that actually rank usually charge substantially more. Quote the ceiling at the
**page-one median**, and if the `ratio` is well above 1, say plainly that the band
would have understated it.

**Never call anything profitable.** Printify's catalog exposes no variant price, so
the COGS is genuinely unavailable — the output ends in a ceiling and a handoff.
Frame it as: *"you need to source this under $X delivered; go price it in the
Printify UI."* Do not estimate the COGS, and do not let a plausible-sounding blank
price stand in for a real one.

**Lead time is often the real blocker, not margin.** Printify handling is commonly
10 days, which closes Etsy's 7-day delivery bracket outright. If
`can_reach_fast_bracket` is false, say so — the operator competes on everything
except speed, and for date-driven gift products that is a genuine disadvantage
rather than a footnote.

If a reading is `unmeasured`, report it as unknown. It is not zero.

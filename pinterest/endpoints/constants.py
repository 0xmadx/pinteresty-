"""Static Pinterest Trends vocabulary.

Hardcoded rather than fetched: `/v3/trends/partner/<userId>/available_interests/` is reachable
but returns `{"results": null, "insufficientDataResponse": ...}` on this account, and the lists
are static in the UI anyway. Every value here is confirmed live — see
`pinterest/tests/test_live_endpoints.py`.
"""

# --- Interests (l1interests) ----------------------------------------------------------
INTERESTS = {
    "Animals": "925056443165",
    "Architecture": "918105274631",
    "Art": "961238559656",
    "Beauty": "935541271955",
    "Children's Fashion": "903733943146",
    "Design": "902065567321",
    "DIY and Crafts": "934876475639",
    "Education": "922134410098",
    "Electronics": "960887632144",
    "Entertainment": "953061268473",
    "Event Planning": "941870572865",
    "Finance": "913207199297",
    "Food and Drinks": "918530398158",
    "Gardening": "909983286710",
    "Health": "898620064290",
    "Home Decor": "935249274030",
    "Men's Fashion": "924581335376",
    "Parenting": "920236059316",
    "Quotes": "948192800438",
    "Sport": "919812032692",
    "Travel": "908182459161",
    "Vehicles": "918093243960",
    "Wedding": "903260720461",
    "Women's Fashion": "948967005229",
}
INTEREST_NAMES = {v: k for k, v in INTERESTS.items()}

# --- Seasonal moments -----------------------------------------------------------------
# US only. The moment vocabulary is PER REGION and `/top_trends_filtered/` validates against
# the region's own list — `moments=oktoberfest&country=US` is a 400, not an empty result. Call
# api.moments_calendar(region) for the authoritative set; these are cached copies.
MOMENTS_US = [
    "christmas", "easter", "fathers day", "halloween", "hanukkah", "independence day",
    "memorial day", "mothers day", "new years eve", "st patricks day", "summer",
    "thanksgiving", "valentines day",
]
MOMENTS_CA = [
    "canada day", "christmas", "diwali", "fathers day", "halloween", "lunar new year",
    "mothers day", "new years eve", "summer", "superbowl", "thanksgiving", "valentines day",
]
MOMENTS_GB_IE = [
    "christmas", "easter", "fathers day", "halloween", "lunar new year", "mothers day",
    "new years eve", "prom", "st patricks day", "summer", "valentines day",
]
MOMENTS_DE = [
    "christmas", "easter", "fathers day", "halloween", "karneval", "mothers day",
    "new years eve", "oktoberfest", "ramadan", "spring", "summer", "valentines day",
]
MOMENTS = MOMENTS_US  # backwards-compatible alias

# Moments coverage, cross-checked against the live UI on 2026-08-07 (not just the API):
#   single-country (US CA BR MX IT ES FR DE CO AR) -> full takeoff_ms + peak_ms
#   DE+AT+CH, AU+NZ, MX+AR+CO+CL                    -> ONE moment gets peak_ms only,
#                                                       takeoff_ms stays null even there
#   GB+IE, NL+BE+LU, SE+DK+FI+NO, IT+ES+PT+GR+MT    -> every date field null, names only
#   JP                                              -> empty list
#   AU, NL, IE, GB, ZZ                              -> 400 (no standalone code for any of
#                                                       these; there is no single-country
#                                                       UK view to fall back to)
# The live /moments/<name>/ detail page is US-only: switching its region selector redirects
# away rather than rendering, so Pinterest's own product has nothing to show for GB+IE
# either — the gap is upstream of us, not a client bug.
# Still wider than the spotlight module, which is US/CA/GB+IE only.
MOMENTS_DATED_REGIONS = ["US", "CA", "BR", "MX", "IT", "ES", "FR", "DE", "CO", "AR"]
MOMENTS_PARTIAL_REGIONS = ["DE+AT+CH", "AU+NZ", "MX+AR+CO+CL"]
MOMENTS_UNDATED_REGIONS = ["GB+IE", "NL+BE+LU", "SE+DK+FI+NO", "IT+ES+PT+GR+MT"]
PHASE_LABELS = ["approaching", "cooldown", "ended"]  # UI renders "ended" as "Frozen"

# --- Spotlight ------------------------------------------------------------------------
SPOTLIGHT_REGIONS = ["US", "CA", "GB+IE"]   # case-insensitive; everything else 400
SPOTLIGHT_EVENT = "SAVE"                    # the only accepted event — no event switch here
SPOTLIGHT_TOPIC_COUNT = 5                   # fixed; limit/offset are ignored

# The dropdown's 15 options. `interests` takes EXACTLY ONE id, or the Fashion triple, or is
# omitted for "All". Two ids, four ids, or any other triple -> 400.
FASHION_TRIPLE = ["903733943146", "924581335376", "948967005229"]
SPOTLIGHT_INTERESTS = {
    "All": None,
    "Animals": ["925056443165"], "Architecture": ["918105274631"], "Art": ["961238559656"],
    "Beauty": ["935541271955"], "DIY and Crafts": ["934876475639"],
    "Education": ["922134410098"], "Event Planning": ["941870572865"],
    "Fashion": FASHION_TRIPLE, "Food and Drinks": ["918530398158"],
    "Gardening": ["909983286710"], "Health": ["898620064290"],
    "Home Decor": ["935249274030"], "Parenting": ["920236059316"],
    "Travel": ["908182459161"], "Wedding": ["903260720461"],
}
# Ids valid on /search/ but absent from the spotlight dropdown split two ways:
# these return 200 with an EMPTY list...
SPOTLIGHT_EMPTY_INTERESTS = ["919812032692", "913207199297", "918093243960", "902065567321"]
# ...while the three Fashion ids passed individually, and any unknown id, return 500.

# --- Tab presets ----------------------------------------------------------------------
# lookbackWindow is COSMETIC: the same preset across windows 1/2/3/5 returns byte-identical
# rows. Only trendsPreset selects the ranking logic. The window values below mirror what the
# UI sends, purely so our traffic looks like the UI's.
PRESETS = {
    "top_monthly": {"trendsPreset": 1, "lookbackWindow": 2, "sorted_by": "volume"},
    "top_yearly": {"trendsPreset": 2, "lookbackWindow": 5, "sorted_by": "volume"},
    "growing": {"trendsPreset": 3, "lookbackWindow": 3, "sorted_by": "velocity"},
    "seasonal": {"trendsPreset": 4, "lookbackWindow": 2, "sorted_by": "velocity"},
}

# Measured floor on the Seasonal preset is 0.829886 — cut at 0.82 so the boundary row survives.
SEASONAL_SCORE_FLOOR = 0.82

# The UI's "10,000%+" cap. A real value, not a real 10,001x move — clamp, never average.
CHANGE_CAP_SENTINEL = 100.01

# --- Demographic enums ----------------------------------------------------------------
# Flat REST endpoints take numeric indices; the /ads/v4 shopping endpoints take strings.
GENDER = {"male": 0, "female": 1, "unspecified": 2}
GENDER_ADS = {"male": "MALE", "female": "FEMALE", "unspecified": "UNSPECIFIED"}

# 18-24 sends TWO buckets — that is why eight indices cover seven visible bands.
AGE = {
    "18-24": [2, 3],
    "25-34": [4],
    "35-44": [5],
    "45-49": [6],
    "50-54": [7],
    "55-64": [8],
    "65+": [9],
}
AGE_ADS = {
    "18-24": "AGE_18_24", "25-34": "AGE_25_34", "35-44": "AGE_35_44", "45-49": "AGE_45_49",
    "50-54": "AGE_50_54", "55-64": "AGE_55_64", "65+": "AGE_65_PLUS",
}

# --- Shopping -------------------------------------------------------------------------
EVENTS = ["OUTBOUND_CLICK", "SAVE", "ENGAGEMENT"]

# Category counts differ per event: OUTBOUND_CLICK 44, ENGAGEMENT 35, SAVE 18.
# IMPRESSION is also accepted on /top/ and returns the same 35 as ENGAGEMENT (aliased).
# CLOSEUP is rejected. On top_products, only OUTBOUND_CLICK returns rows.
SHOPPING_EVENTS = ["OUTBOUND_CLICK", "ENGAGEMENT", "SAVE"]

# The 14 level-1 verticals. They are referenced as parents but are NOT in the 383-entry
# taxonomy map, and passing one as a product_category_id is a 400 every time.
VERTICALS = {
    "1181": "Fashion", "1250": "Home decor", "1042": "Beauty",
    # selectable in the UI: the three above. The rest are parent-only ids.
    "1161": None, "1148": None, "1194": None, "1315": None, "1500": None,
    "1481": None, "1016": None, "1436": None, "1007": None, "1241": None, "1489": None,
}

TOP_LIMIT_MAX = 522        # 523+ -> 400, 0 and negatives -> 400
TOP_LIMIT_DEFAULT = 8      # what you get if you omit `limit`

# --- Search discovery table -------------------------------------------------------------
# `numTermsToReturn` on /top_trends_filtered/. The UI only ever sends 50 and the table is
# fixed at 50 on screen, but the server accepts up to 100 — 101 is a 400. Verified on
# presets 1/3/4 and with an l1interests filter; the first 50 rows come back byte-identical
# to the default call, so raising this only ever ADDS rows 51-100 and never re-ranks.
TOP_TRENDS_LIMIT_MAX = 100
TOP_TRENDS_LIMIT_UI = 50
ORDER_BY = ["PCT_CHANGE_MOM", "RELATIVE_VOLUME"]

# --- Regions --------------------------------------------------------------------------
# Search endpoints take grouped values from the region dropdown...
REGION_GROUPS = ["US", "GB+IE", "DE+AT+CH", "MX+AR+CO+CL"]
# ...but Shopping accepts only these three. DE+AT+CH -> 400.
SHOPPING_REGIONS = ["US", "CA", "GB+IE"]

# --- moment/metrics -------------------------------------------------------------------
# ⭐ The ONLY endpoint in this API that resolves below weekly. Verified live 2026-09-01
# on `halloween`: aggregation_level="daily" + lookback_days=365 returned 365 points;
# "weekly" returned 66. Everything else in Pinterest Trends is weekly-only.
MOMENT_AGGREGATIONS = ["daily", "weekly", "monthly"]   # case-insensitive; "hourly" -> 400
MOMENT_LOOKBACK_MAX = 730                              # 1095 -> 400 "too large"
MOMENT_INTEREST_LIMIT_MAX = 24                         # 0 = omit moment_interests; 50 -> 400
MOMENT_PREDICTED_DAYS_MAX = 91                         # 180/365 -> 400 "too large"
# ⚠️ predicted_days must divide evenly into the aggregation unit: monthly + 91 -> 400
# ("91 predicted days do not evenly divide into monthly agg"). weekly + 91 -> 13 points.

# --- days / predicted_days ------------------------------------------------------------
# Search /metrics/ takes ONLY these; days=45 or 60 returns 400.
SEARCH_METRICS_DAYS = [30, 90, 180, 365, 730]
# Shopping metrics is far looser: any integer 1-730 (0 and 731+ -> 400).
SHOPPING_DAYS_RANGE = (1, 730)
# 7 -> 500, 29 and 92 -> 400. Only these are safe.
PREDICTED_DAYS = [0, 14, 28, 35, 56, 91]


def age_buckets(*bands):
    """age_buckets('18-24', '25-34') -> '2,3,4' for the flat REST endpoints."""
    out = []
    for b in bands:
        out.extend(AGE[b])
    return ",".join(str(i) for i in out)


def genders(*names):
    """genders('female') -> '1'"""
    return ",".join(str(GENDER[n]) for n in names)


def clamp_change(value):
    """Turn the 10,000%+ sentinel into None so it can't poison an average."""
    return None if value is None or value >= CHANGE_CAP_SENTINEL else value

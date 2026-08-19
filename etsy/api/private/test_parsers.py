"""The private-tier parsers, and the snake_case family of bugs they exist to kill.

Etsy returns snake_case; this repo historically read camelCase, and the difference
emptied every table for the life of the project. These pins cover the specific shapes
that were verified on the wire — including the LLM keyword edge, where the bug hid at
three separate layers (enqueue read, poll read, and `edge_term` itself).

    .venv/Scripts/python.exe -m etsy.api.private.test_parsers
"""
from etsy.api.private.api import (_money, edge_term, normalise_listing_card,
                                  parse_results_data)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


# --- edge_term: the LLM keyword endpoint uses search_term --------------------------
# Verified live 2026-08-15: enqueue.cached_data.results and the poll body both key the
# keyword on `search_term`. edge_term listed searchTerm/query/term/keyword but NOT
# search_term, so every one of 118 real edges resolved to None and the recursion
# produced nothing even after the enqueue/poll reads were fixed.
check("edge_term reads search_term (the live spelling)",
      edge_term({"search_term": "felt banner", "search_volume": 2179}) == "felt banner")
check("still reads the camelCase spelling", edge_term({"searchTerm": "x"}) == "x")
check("still reads query (the enqueue dedupe key)", edge_term({"query": "y"}) == "y")
check("prefers search_term when several are present",
      edge_term({"search_term": "a", "query": "b"}) == "a")
check("None for an edge with no known key", edge_term({"volume": 5}) is None)
check("None for a non-dict", edge_term("felt banner") is None)

# The exact edge shape the endpoint returns — must yield a usable term AND its metrics.
edge = {"search_term": "felt ball garland", "search_volume": 693,
        "avg_total_listings": 11100, "cvr": 1}
check("a real LLM edge resolves its term", edge_term(edge) == "felt ball garland")
check("and carries volume for winnability", edge["search_volume"] == 693)
check("and supply for winnability", edge["avg_total_listings"] == 11100)
# volume/supply = 0.06 here; the whole point of recursion is reaching terms like this
# whose winnability can be judged, not just Etsy's 28 curated head terms.

# --- _money: the median band arrives as "$17.10" -----------------------------------
check("a formatted price coerces to float", _money("$17.10") == 17.10)
check("thousands separators are handled", _money("$1,234.50") == 1234.50)
check("an already-numeric value passes through", _money(17.1) == 17.1)
check("None stays None", _money(None) is None)
check("an unreadable price is None, never 0.0", _money("$") is None)
# 0.0 would be a free product, passing every margin floor — an unreadable price must
# never become a guaranteed `go`.

# --- parse_results_data: prices are floats, and the wider bar band is separate ------
payload = {
    "stats": {"search_term": "mom necklace", "search_volume": 12867,
              "avg_total_listings": 351677, "query_cvr": 0.000256, "cvr": 0},
    "competitive_price_data": {"search_term_median_price": {
        "median_price_low": "$17.10", "median_price_high": "$20.90",
        "median_price_bar_low_float": 12.67, "median_price_bar_high_float": 25.33}},
    "wow_data": {"value": 10.5},
}
d = parse_results_data(payload)
check("volume read from snake_case", d["volume"] == 12867)
check("supply read from snake_case", d["supply"] == 351677)
check("the RATE comes from query_cvr, not the ordinal bucket", d["cvr"] == 0.000256)
check("price_low is a float, not '$17.10'", d["price_low"] == 17.10)
check("price_high is a float", d["price_high"] == 20.90)
check("the formatted original is kept for display", d["price_low_text"] == "$17.10")
check("the wider bar band is exposed separately, not as a fallback",
      d["price_bar_low"] == 12.67 and d["price_bar_high"] == 25.33)
# median 17.10-20.90 vs bar 12.67-25.33 are different bands for the same term;
# substituting one for the other would move the margin and the verdict.
check("Etsy's own momentum is read", d["wow_change"] == 10.5)

# --- normalise_listing_card: reviews arrive as strings -----------------------------
card = normalise_listing_card({"listing_id": "1", "number_of_reviews": "1,459",
                               "shop_name": "X", "price": {"formatted_price": "$24.00"}})
check("a string review count becomes an int", card["review_count"] == 1459)
check("shop_name read from snake_case", card["shop_name"] == "X")
check("an unreadable review count is None, not 0",
      normalise_listing_card({"number_of_reviews": "n/a"})["review_count"] is None)

# --- a dead seller session is legible, not a silent None ---------------------------
# The failure this pins: browser/extension off -> stale session -> 401 -> the old code
# returned None, which read like a broken endpoint. It was mis-diagnosed as one once.
from core.request_cache import RequestCache  # noqa: E402
from etsy.api.private.api import EtsyPrivateAPI, SessionDown  # noqa: E402


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.text = "null"

    def json(self):
        return None


class _FakeSession:
    def __init__(self, code):
        self.code = code

    def request(self, *a, **k):
        return _Resp(self.code)


def _api(code):
    api = EtsyPrivateAPI.__new__(EtsyPrivateAPI)
    api.session = _FakeSession(code)
    api.headers = {}
    api.manager = None
    api.cache = RequestCache()
    return api


for code in (401, 403):
    try:
        _api(code).get_results_data(f"probe {code}")
        check(f"a {code} raises rather than returning None", False, "returned")
    except SessionDown as exc:
        check(f"a {code} raises SessionDown", True)
        check(f"{code} names the cause", "session" in str(exc).lower())
        check(f"{code} points at the check", "vault_status" in str(exc))

check("SessionDown is distinct from a generic error",
      issubclass(SessionDown, RuntimeError) and SessionDown is not RuntimeError)
# So a caller can catch "your browser is off" separately from "Etsy said no" (429) and
# "the code broke" — three different fixes.

# A 500 is NOT a session problem and must not masquerade as one.
check("a 500 returns None, not SessionDown",
      _api(500).get_results_data("probe 500") is None)


# --- THE PARSER'S SHAPE IS A CONTRACT, and consumers keep getting it wrong ----------
#
# parse_results_data returns a FLAT dict. Twice now code has been written against an
# imagined nested `stats` block with camelCase keys — once across seven modules for
# the life of the project (D-24), and once again on 2026-08-19 in the MCP tool and
# the keyword sweep job, both written the same afternoon the rule was restated.
#
# Indexing a shape the parser does not return does not raise. It yields None for
# every field, and a pipeline then writes a row of NULLs that reads as "we looked and
# the market is unmeasured". These assertions exist so that mistake fails loudly in
# the suite instead of silently in the database.
FLAT_KEYS = ("keyword", "volume", "supply", "cvr", "cvr_bucket", "price_low",
             "price_high", "wow_change", "wow_direction", "listings")
live_shape = parse_results_data(payload)
for key in FLAT_KEYS:
    check(f"parse_results_data exposes '{key}' at the TOP level",
          key in live_shape, sorted(live_shape))
check("there is NO nested 'stats' block — indexing one silently yields None",
      "stats" not in live_shape, sorted(live_shape))
check("and no camelCase survives the parser",
      not [k for k in live_shape if any(c.isupper() for c in k)],
      [k for k in live_shape if any(c.isupper() for c in k)])

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

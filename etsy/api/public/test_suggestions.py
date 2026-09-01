"""Offline tests for Etsy's search-box autocomplete. No network.

Two docs listed "Search Autosuggest" as a capability of this system. It was never
built — what existed was `similar_keywords`, which is `llm-exploratory-keywords`:
LLM-GENERATED adjacencies, on the SELLER session, at ~10 requests per expansion.
Different signal, different cost, different risk.

This is the real query stream, on the buyer session, at 2 requests. Etsy runs TWO
autocomplete endpoints that DISAGREE — suggestions_ajax.php returns 14 for
`badge reel` where the v3 endpoint returns 10, and each carries terms the other
misses, so reading one would silently halve the candidate set.

What these pin:

  1. The echoed query is NOT a suggestion. Etsy returns the input as row 0, and
     counting it inflates every result by one and makes a dead term look alive.
  2. A failure returns None — never an empty suggestion list, which would read as
     "Etsy has nothing for this term" (N-02).
  3. The wire facts that were probed rather than assumed: `version` is INERT
     (garbage returns the same rows, so nothing expires), `extras` is NOT
     (dropping it costs 3 of 14), and the lists do NOT rotate across calls.

Run:  python -m etsy.api.public.test_suggestions
"""
import sys

from etsy.api.public.api import EtsyPublicAPI

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class _Session:
    """Records URLs and returns a canned payload per endpoint. No network."""

    def __init__(self, payload, status=200, v3=None, v3_status=None):
        self.payload, self.status, self.urls = payload, status, []
        self.v3 = v3 if v3 is not None else {"results": []}
        self.v3_status = v3_status if v3_status is not None else status

    def request(self, method, url, **kw):
        self.urls.append(url)
        if "suggestions_ajax" in url:
            return _Resp(self.payload, self.status)
        return _Resp(self.v3, self.v3_status)


class _Cache:
    """Pass-through: these tests are about the parse, not the TTL."""

    def get_or_fetch(self, key, ttl, fetch, source=None):
        self.key, self.ttl = key, ttl
        return fetch()


# The shape measured live 2026-09-01 on `badge reel`.
LIVE = {
    "results": [
        {"query": "badge reel", "categories": []},
        {"query": "badge reel funny", "categories": []},
        {"query": "badge reel nurse", "categories": []},
        {"query": "badge reel halloween", "categories": []},
        {"query": "badge reel fall", "categories": []},
    ],
    "simplified_queries": [],
}


def _api(payload, status=200, v3=None, v3_status=None):
    api = EtsyPublicAPI.__new__(EtsyPublicAPI)
    api.session = _Session(payload, status, v3, v3_status)
    api.cache = _Cache()
    api.headers = {}
    return api


def main():
    print("\nthe parse")
    api = _api(LIVE)
    out = api.get_search_suggestions("badge reel")
    check("returns the real completions", len(out["suggestions"]) == 4, out)
    # Etsy echoes the input as row 0. Counted, it inflates every result by one and
    # makes a term with zero real completions look like it has one.
    check("the ECHOED query is dropped, not counted as a suggestion",
          "badge reel" not in out["suggestions"], out["suggestions"])
    check("order is preserved — it is Etsy's own popularity ordering",
          out["suggestions"][0] == "badge reel funny", out["suggestions"])
    check("the seasonal hooks survive",
          {"badge reel halloween", "badge reel fall"} <= set(out["suggestions"]))
    check("basis is measured", out["basis"] == "measured")

    check("case and padding do not defeat the echo filter",
          "  Badge Reel " not in _api(LIVE).get_search_suggestions("  Badge Reel ")["suggestions"])

    print("\nrefusals")
    # An empty list would read as "Etsy knows nothing about this term". None is
    # "we did not get an answer" — a different claim (N-02).
    check("BOTH endpoints failing returns None, NOT an empty suggestion list",
          _api(LIVE, status=429, v3_status=429).get_search_suggestions("x") is None)
    check("a 404 pair likewise",
          _api(LIVE, status=404, v3_status=404).get_search_suggestions("x") is None)
    empty = _api({"results": [{"query": "zzz"}]}).get_search_suggestions("zzz")
    check("a genuine empty result IS an empty list, and says measured",
          empty["suggestions"] == [] and empty["basis"] == "measured", empty)
    check("malformed JSON is swallowed by soft_parse, not raised",
          _api({"nope": 1}).get_search_suggestions("x")["suggestions"] == [])
    check("ten identical calls are pointless — the lists do NOT rotate (measured)",
          "do NOT rotate" in EtsyPublicAPI.get_search_suggestions.__doc__)
    check("a row with no query is skipped rather than adding None",
          _api({"results": [{"categories": []}, {"query": "ok"}]})
          .get_search_suggestions("x")["suggestions"] == ["ok"])

    print("\nthe request")
    api = _api(LIVE)
    api.get_search_suggestions("badge reel")
    url = api.session.urls[0]
    check("hits BOTH endpoints — each carries terms the other misses",
          any("suggestions_ajax" in u for u in api.session.urls)
          and any("/api/v3/ajax/public/search/suggestions" in u
                  for u in api.session.urls), api.session.urls)
    check("the query is URL-encoded", "search_query=badge+reel" in url, url)
    check("`extras` IS sent — dropping it costs 3 of 14 rows", "extras=" in url)
    check("`version` is NOT sent — probed inert, so sending it would imply it works",
          "version=" not in url, url)
    # Probed: limit / language / country / lang all returned the identical 11 rows.
    # Sending them would imply they do something.
    check("no inert parameters are sent",
          not any(p in url for p in ("limit=", "language=", "country=", "lang=")), url)
    # Autocomplete tracks what is being typed NOW; that is the whole reason to read
    # it. A long TTL would turn a live signal into a stale one.
    check("cached for ONE day, not thirty — this is a live signal",
          api.cache.ttl == 86400, api.cache.ttl)
    check("the cache key is per-term and versioned past the single-endpoint shape",
          api.cache.key == "suggest2_badge reel", api.cache.key)

    print(chr(10) + "the merge")
    both = _api(LIVE, v3={"results": [{"query": "badge reel"},
                                      {"query": "badge reel miffy"},
                                      {"query": "badge reel nurse"}]})
    m = both.get_search_suggestions("badge reel")
    check("v3-only terms are added, not dropped",
          "badge reel miffy" in m["suggestions"], m["suggestions"])
    check("a term both endpoints return appears ONCE",
          m["suggestions"].count("badge reel nurse") == 1, m["suggestions"])
    check("and the contribution of each endpoint is reported",
          m["from_ajax_only"] == 4 and m["added_by_v3"] == 1, m)
    check("provenance per term is kept",
          m["sources"]["badge reel miffy"] == "v3"
          and m["sources"]["badge reel nurse"] == "ajax", m["sources"])
    # ajax mixes a shop-name row of raw HTML into results. Counted, it poses as a
    # keyword and would be sent to a sizing call.
    junk = _api({"results": [{"query": "badge reel real"},
                             {"query": '<span class="copy-text">find shop names</span>'}]})
    check("the ajax shop-name HTML row is dropped, not treated as a query",
          junk.get_search_suggestions("badge reel")["suggestions"] == ["badge reel real"])
    half = _api(LIVE, v3_status=500).get_search_suggestions("badge reel")
    check("one endpoint failing still returns the other's terms",
          len(half["suggestions"]) == 4, half)
    check("...and SAYS it is partial — a half-sized list must not read as a narrow niche",
          half["partial"] is True and half["basis"] == "partial", half)
    check("a full answer is not flagged partial",
          _api(LIVE, v3={"results": []}).get_search_suggestions("badge reel")["partial"] is False)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

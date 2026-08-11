"""Rank tracking — the outcome half of the LEARN loop (M-3).

`record_launch()` captures what we *predicted*. This captures what actually happened:
for each launched listing, where did it land in the public SERP for the term it was
launched against?

`MIGRATION_AND_OPERATIONS.md:111` schedules this 3×/week and requires **both organic
and absolute** rank to be recorded, because they answer different questions:

    absolute — position among everything the buyer sees, ads included. What the
               shopper's eye actually encounters.
    organic  — position among unpaid results only. What SEO earned, independent of
               who bought placement that day.

A listing can slide in absolute rank while holding organic rank simply because a
competitor started running ads. Recording only one makes that look like a ranking
loss it isn't.

**The rule that matters here:** a listing that is not in the results is recorded with
`rank=None`, never skipped. "Checked, not found" and "never checked" are different
facts, and `rank_observations` is built so they cannot be confused — see
`graph_db.rank_observations`.

No new session handling: this reuses `EtsyPublicAPI.get_public_search`, the same call
the arbitrage engine already makes.
"""
from core import runlog
from core.graph_db import GraphDB
from core.runlog import logged_stage
from etsy.api.public.api import EtsyPublicAPI

# Etsy serves 48 slots per SERP page; only the first 12 are server-rendered (see
# `parse_search_html`). Positions are computed against what the page actually returned,
# and `page` is recorded so a later reader knows the denominator.
RESULTS_PER_PAGE = 48


def find_rank(search_result, listing_id):
    """Locate one listing in a parsed SERP payload. Pure — no I/O, no network.

    Returns a dict with both rank flavours, or `rank=None` when the listing is absent.
    Split out from the fetching so the position arithmetic — the part that is easy to
    get subtly wrong and impossible to notice — is testable offline.
    """
    listing_id = str(listing_id)
    cards = (search_result or {}).get("cards") or []
    organic_ids = [str(i) for i in (search_result or {}).get("organic_listing_ids") or []]

    absolute_rank = None
    is_ad = False
    for position, card in enumerate(cards, start=1):
        if str(card.get("listing_id")) == listing_id:
            absolute_rank = position
            is_ad = bool(card.get("is_ad"))
            break

    organic_rank = None
    if listing_id in organic_ids:
        organic_rank = organic_ids.index(listing_id) + 1

    return {
        "rank": organic_rank if organic_rank is not None else absolute_rank,
        "organic_rank": organic_rank,
        "absolute_rank": absolute_rank,
        "is_ad": is_ad,
        # Total supply competing for the term, so a rank of 40 reads differently
        # against 200 competitors than against 200,000.
        "competitor_count": (search_result or {}).get("total_results"),
        "found": absolute_rank is not None or organic_rank is not None,
    }


@logged_stage("rank_tracker")
def track_ranks(db=None, public_api=None, term_lookup=None):
    """Observe every launched listing's current rank. Returns a list of results.

    `term_lookup` maps a stored `term_id` to the query string to search. Defaults to
    identity, since launches store the term itself; pass a callable when term_ids are
    prefixed (e.g. the `pin:`/`etsy:` convention in `nodes`).
    """
    db = db or GraphDB()
    public_api = public_api or EtsyPublicAPI()
    term_lookup = term_lookup or (lambda t: t)

    launches = db.get_launches()
    if not launches:
        print("[-] No launches recorded yet — nothing to track. Record a launch when "
              "you list a product (graph_db.record_launch).")
        return []

    print(f"[+] Tracking {len(launches)} launched listing(s)...")
    results = []
    checked = missing = 0

    for launch in launches:
        listing_id, term_id = launch["listing_id"], launch["term_id"]
        query = term_lookup(term_id)

        search = public_api.get_public_search(query)
        if search is None:
            # The search itself failed. Recording rank=None here would assert
            # "not in results", which we did not observe. Skip and say so.
            print(f"    [!] '{query}': search failed — NOT recorded (an absent row means "
                  f"unchecked, which is the truth here)")
            runlog.count(errors=1)
            continue

        found = find_rank(search, listing_id)
        db.record_rank(listing_id, term_id,
                       rank=found["organic_rank"],
                       absolute_rank=found["absolute_rank"],
                       page=1 if found["found"] else None,
                       is_ad=found["is_ad"],
                       competitor_count=found["competitor_count"])
        checked += 1
        if not found["found"]:
            missing += 1
            print(f"    [·] {listing_id} not in results for '{query}' "
                  f"— recorded as unranked (measured)")
        else:
            print(f"    [+] {listing_id} @ '{query}': organic="
                  f"{found['organic_rank']} absolute={found['absolute_rank']}"
                  f"{' (AD)' if found['is_ad'] else ''} "
                  f"of {found['competitor_count']} competitors")
        results.append({**found, "listing_id": listing_id, "term_id": term_id})

    runlog.count(rows_in=len(launches), rows_out=checked)
    print(f"[+] {checked} observed, {missing} unranked, "
          f"{len(launches) - checked} unchecked (search failed).")

    # D-12: the calibration gate. Reported every run so the operator knows how far off
    # auto-tuning is, rather than discovering the threshold when they try to use it.
    n = db.launch_count()
    if n < 10:
        print(f"[i] {n}/10 launches recorded. D-12 holds auto-tuning until 10 — "
              f"below that, outcomes cannot distinguish a good model from luck.")
    return results


if __name__ == "__main__":
    track_ranks()

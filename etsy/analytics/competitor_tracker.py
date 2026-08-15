"""What competitors LAUNCHED, and whether it worked (D-25).

The weak version of this feature is a listing feed: *"the shop you track listed a mom
necklace."* Listings are cheap — sellers list constantly and most of it fails, so that
tells you what they **guessed**, not what **worked**. Copying guesses is worse than
useless.

The strong version is an outcome: *"they listed it three weeks ago and it already has
12 reviews."* Reviews are the one thing a seller cannot fabricate, and velocity is an
outcome rather than a forecast.

**Why it is worth building at all** — it is the only unbiased outcome dataset available
here. Your own launches only ever test niches the model already liked, so LEARN can
never discover it was wrong to *reject* something (B-04). A competitor's launches are
independent of your model: you get to watch things succeed and fail that you would
never have picked. Ten of your launches is a biased sample of ten; three shops'
launches is an unbiased sample that grows every week for free.

Three things it must keep admitting:

  * **reviews are a lower bound on sales.** Most buyers never review. A review count is
    "at least this many sold", never "this many sold".
  * **age is observed, not known.** Etsy does not publish a listing's creation date on
    the shop page, so `first_seen_at` is when *we* first looked. A listing already old
    when tracking began has no knowable age, and its velocity is therefore a bound too.
  * **survivorship applies here as much as anywhere (B-01).** Track only star shops and
    you learn what winners do, not what works. Track some mid-tier shops deliberately.
"""
from datetime import datetime

MIN_OBSERVATIONS = 2      # a rate needs two points; one point is a level
MIN_WINDOW_HOURS = 12     # below this, rounding dominates the rate


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def review_velocity(history):
    """Reviews per day for one listing, from its observation history.

    Returns a dict whose `basis` says what the number is worth, or refuses. Every
    refusal here is a case where a plausible number could be produced and would be
    wrong:

      insufficient_history   one sighting is a level, not a rate
      window_too_short       two readings hours apart make rounding the signal
      unmeasured             the review count never parsed — absent is not zero (N-02)
      counter_decreased      reviews went down; Etsy removed one, so the window is
                             not a clean difference and no rate is honest
    """
    usable = [h for h in history if h.get("total_reviews") is not None]
    if len(usable) < MIN_OBSERVATIONS:
        return {"velocity": None, "basis": "insufficient_history",
                "observations": len(usable),
                "detail": f"need {MIN_OBSERVATIONS} readings with a parsed review count"}

    usable.sort(key=lambda h: h["collected_at"])
    first, last = usable[0], usable[-1]
    t0, t1 = _parse(first["collected_at"]), _parse(last["collected_at"])
    if not t0 or not t1:
        return {"velocity": None, "basis": "unreadable_timestamps", "observations": len(usable)}

    hours = (t1 - t0).total_seconds() / 3600
    if hours < MIN_WINDOW_HOURS:
        return {"velocity": None, "basis": "window_too_short", "observations": len(usable),
                "window_hours": round(hours, 2)}

    delta = last["total_reviews"] - first["total_reviews"]
    if delta < 0:
        return {"velocity": None, "basis": "counter_decreased", "observations": len(usable),
                "detail": "review count fell — a removed review makes the window unusable"}

    return {
        "velocity": round(delta / (hours / 24), 4),
        "basis": "measured",
        "observations": len(usable),
        "window_days": round(hours / 24, 3),
        "reviews_gained": delta,
        "total_reviews": last["total_reviews"],
        # Reviews undercount sales by an unknown factor, so the velocity is a floor.
        "is_lower_bound": True,
    }


def observed_age_days(history, now=None):
    """How long we have WATCHED this listing, and whether that is its real age.

    `age_is_bounded` False means the listing already existed when tracking began, so
    its true age is unknown and only greater than this. A "listed 3 weeks ago" claim is
    honest only when `age_is_bounded` is True.
    """
    if not history:
        return {"days": None, "basis": "never_seen"}
    ordered = sorted(history, key=lambda h: h["collected_at"])
    first = _parse(ordered[0].get("first_seen_at") or ordered[0]["collected_at"])
    latest = _parse(ordered[-1]["collected_at"])
    if not first or not latest:
        return {"days": None, "basis": "unreadable_timestamps"}
    # `sighting_basis` is the column `record_listing_observation` writes. Reading
    # `basis` here would silently return None for every row — the producer/consumer
    # key drift that emptied every table in this project once already.
    sighting = ordered[0].get("sighting_basis", "unknown")
    return {
        "days": round((latest - first).total_seconds() / 86400, 2),
        "basis": sighting,
        # Only a listing we watched APPEAR has a knowable age. One that was already
        # there on our first sweep is older than this by an unknown amount.
        "age_is_bounded": sighting == "first_sighting",
    }


def new_listings(db, shop_name, since):
    """Listings whose first sighting is after `since` — what this shop just launched.

    Only meaningful once a baseline sweep exists: on the very first sweep every listing
    is 'new', which is an artefact of when we started, not of what they did.
    """
    return [row for row in db.tracked_listings(shop_name)
            if (row.get("first_seen_at") or "") > since]


def rank_by_outcome(db, shop_name=None, min_velocity=None):
    """Their listings, best-performing first — the point of the whole module.

    Sorted on measured review velocity. Listings that cannot yet be judged are returned
    too, at the end, with the reason: dropping them would quietly hide the newest
    launches, which are exactly the ones worth seeing early.
    """
    out = []
    for row in db.tracked_listings(shop_name):
        history = db.get_listing_history(row["listing_id"])
        velocity = review_velocity(history)
        age = observed_age_days(history)
        if min_velocity is not None and (velocity["velocity"] or 0) < min_velocity:
            continue
        out.append({**row, "velocity": velocity, "age": age})
    out.sort(key=lambda r: (r["velocity"]["velocity"] is not None,
                            r["velocity"]["velocity"] or 0), reverse=True)
    return out


def sweep_shop(db, scraper, shop_name, watched_terms=None, max_review_fetches=20,
               collected_at=None, shop_total_reviews=None):
    """One tracking pass over a shop. Two tiers, because the wire forces it.

        1 request   the shop grid → ids, titles, prices (what they have listed)
        N requests  one per listing → its own review count (whether it worked)

    Shop pages carry no per-listing review counts, so the outcome signal cannot be
    batched out of the grid. `max_review_fetches` caps the cost and spends it where it
    is worth most: listings never seen before, then the ones checked longest ago.

    A listing whose review fetch is skipped or fails is still recorded, with
    `total_reviews=None`. That is deliberate — the sighting is real and starts the
    clock on `first_seen_at`, and recording 0 would fake a brand-new listing and make
    its next reading enormous (N-02).
    """
    listings = scraper.get_shop_listings(shop_name)
    if listings is None:
        return {"shop": shop_name, "error": "listing fetch failed", "recorded": 0}

    known = {row["listing_id"]: row for row in db.tracked_listings(shop_name)}
    # Unseen first — a new launch is the whole point of watching. Then stalest.
    ordered = sorted(listings,
                     key=lambda l: (l["listing_id"] in known,
                                    (known.get(l["listing_id"]) or {}).get("collected_at") or ""))

    recorded, fetched, new, refused = 0, 0, [], 0
    for listing in ordered:
        outcome = None
        if fetched < max_review_fetches:
            # The shop total is passed so a listing page returning the SHOP's review
            # count instead of its own can be caught and refused rather than recorded
            # as a spectacular fake winner. See ShopScraper.get_listing_outcome.
            outcome = scraper.get_listing_outcome(
                listing["listing_id"], shop_total_reviews=shop_total_reviews)
            fetched += 1
            if outcome and outcome.get("basis") == "refused_shop_total_contamination":
                refused += 1
        if listing["listing_id"] not in known:
            new.append(listing["listing_id"])

        result = db.record_listing_observation(
            listing["listing_id"], shop_name=shop_name, title=listing.get("title"),
            price=listing.get("price"),
            total_reviews=(outcome or {}).get("total_reviews"),
            rating=(outcome or {}).get("rating"), is_ad=listing.get("is_ad"),
            matched_term=match_title_to_term(listing.get("title"), watched_terms),
            collected_at=collected_at)
        recorded += 1

    return {"shop": shop_name, "seen": len(listings), "recorded": recorded,
            "review_counts_fetched": fetched,
            "review_counts_refused": refused, "new_listings": new,
            # On the first sweep every listing is "new", which is an artefact of when
            # tracking started rather than anything the shop did.
            "is_baseline": not known}


def match_title_to_term(title, watched_terms):
    """Which watched niche does this listing title belong to? None if none.

    NOT `term_join.best_match`. That one demands exact content-word set equality, which
    is right for joining a term to a term (D-17) but can never fire on a title: a real
    listing reads "Reversible Linen Apron: No-Tie Organic European Flax", so it would
    never equal the niche "linen apron".

    Containment is the correct relation here — a title holding every content word of a
    niche is plausibly in it. The **most specific** match wins, which preserves the
    thing D-17 was protecting: a title containing {mom, necklace} matches "mom
    necklace" rather than the broader "necklace", so a narrow niche is never collapsed
    into a wide one. A tie on specificity is refused rather than guessed.
    """
    from etsy.analytics.term_join import content_words

    words = content_words(title or "")
    if not words:
        return None

    best, best_size, tied = None, 0, False
    for candidate in watched_terms or []:
        needed = content_words(candidate)
        if not needed or not needed <= words:
            continue
        if len(needed) > best_size:
            best, best_size, tied = candidate, len(needed), False
        elif len(needed) == best_size and candidate != best:
            tied = True
    # Two equally specific niches both fit; picking either would be a coin toss
    # presented as a finding.
    return None if tied else best


def match_to_watchlist(listings, watched_terms):
    """Tag each listing with the watched niche it belongs to, if any.

    The pairing that makes this actionable: *a shop you track just launched into a
    niche you are considering, and here is how fast it is gaining reviews.*

    A listing matching nothing is left `None`, never forced into the nearest niche.
    """
    return [{**listing,
             "matched_term": match_title_to_term(listing.get("title"), watched_terms)}
            for listing in listings]

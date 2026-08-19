"""
sourcing.py

Layer: analytics/ (pure analysis + a thin fetch helper)
Purpose: answer "where do the incumbents ship from, and how fast?" — the two
         questions that explain a competitor's price and expose whether speed
         is a defensible gap.

Why this exists. A competitor selling a personalized towel at $16.60 when our
landed POD cost is $22.15 has a cost structure we cannot see from price alone.
Origin explains it: an overseas manufacturer selling direct has a different
floor than a US print-on-demand reseller. And origin comes with a *weakness* —
long delivery — which is attackable if we ship fast and they do not.

Both halves are free: `locationQuery` and `delivery_days` are public-SERP
filters, and each request returns only `total_results`, which is the answer.

⚠️ Two things this cannot see, recorded so nobody mistakes silence for absence:

  * **Etsy's ships-from filter lists 77 countries and Turkey is not one of
    them.** Turkish textile sellers are a real, visible force in the towel
    category (`TurkishTowelWeaving`, $11.98), and they land in the unmeasured
    remainder. A large remainder is a signal in itself, not a rounding error.
  * A filter returning *exactly* the unfiltered total was **ignored**, not
    matched. That is how a wrong parameter name poisons an analysis silently,
    so it is detected rather than trusted (see `IGNORED`).
"""
from dataclasses import dataclass, field

# A bracket whose count equals the unfiltered total means Etsy did not apply the
# filter — a wrong or unsupported parameter. Never read as "everything matches".
IGNORED = "filter_ignored"

# Below this share of listings delivering fast, speed is worth investigating as a
# gap. Not a verdict on its own — D-10 still requires demand inside the bracket.
FAST_DELIVERY_THIN = 0.20
# Above this share from a single foreign origin, price competition is likely
# structural (direct manufacturing) rather than something to out-execute.
IMPORT_DOMINANT = 0.50


@dataclass(frozen=True)
class Share:
    label: str
    listings: int
    share: float          # of total supply
    status: str = "measured"   # measured | filter_ignored | unmeasured


@dataclass(frozen=True)
class SourcingProfile:
    query: str
    total_supply: int
    origins: tuple = ()       # Share per country
    delivery: tuple = ()      # Share per speed bracket
    unmeasured_share: float = None   # supply not attributed to any listed country
    notes: tuple = field(default_factory=tuple)

    @property
    def domestic(self):
        return next((s for s in self.origins if s.label == "United States"), None)

    @property
    def fast_delivery(self):
        return next((s for s in self.delivery if s.label == "7"), None)


def to_share(label, listings, total):
    """One bracket count -> a Share, detecting the ignored-filter case."""
    if listings is None:
        return Share(label, 0, 0.0, "unmeasured")
    if total and listings == total:
        # Identical to unfiltered: Etsy ignored the parameter. Reporting 100%
        # here would claim every listing matches, which is the opposite of true.
        return Share(label, listings, 1.0, IGNORED)
    return Share(label, listings, (listings / total) if total else 0.0)


def build_profile(query, total_supply, origin_counts, delivery_counts, notes=()):
    """Pure assembly. `*_counts` map label -> listing count (None = unmeasured)."""
    origins = tuple(to_share(k, v, total_supply) for k, v in origin_counts.items())
    delivery = tuple(to_share(k, v, total_supply) for k, v in delivery_counts.items())

    measured = sum(s.listings for s in origins if s.status == "measured")
    unmeasured = None
    if total_supply:
        # What no listed country accounts for. Turkey lives in here.
        unmeasured = round(max(0.0, (total_supply - measured) / total_supply), 4)

    return SourcingProfile(query=query, total_supply=total_supply, origins=origins,
                           delivery=delivery, unmeasured_share=unmeasured,
                           notes=tuple(notes))


def read(profile):
    """Plain-language findings. Says what is *not* established as loudly as what is."""
    out = []
    dom = profile.domestic
    if dom and dom.status == "measured":
        if dom.share >= 0.70:
            out.append(f"Domestic niche — {dom.share:.0%} ships from the US. Fast "
                       f"domestic delivery is table stakes here, not a differentiator.")
        elif dom.share <= 0.30:
            out.append(f"Import-led — only {dom.share:.0%} ships from the US.")

    foreign = [s for s in profile.origins
               if s.label != "United States" and s.status == "measured"]
    big = [s for s in foreign if s.share >= IMPORT_DOMINANT]
    for s in big:
        out.append(f"{s.label} holds {s.share:.0%} of supply — competing on price "
                   f"against direct manufacturing is unlikely to work.")

    if profile.unmeasured_share and profile.unmeasured_share >= 0.10:
        out.append(f"{profile.unmeasured_share:.0%} of supply ships from somewhere "
                   f"Etsy's 77-country filter does not list (Turkey among them). "
                   f"That share is unattributed, not domestic.")

    fast = profile.fast_delivery
    if fast and fast.status == "measured":
        if fast.share <= FAST_DELIVERY_THIN:
            out.append(f"Only {fast.share:.0%} deliver within 7 days — speed is thin "
                       f"here. Worth testing as a gap, but D-10 still applies: thin "
                       f"supply is not demand until demand is shown inside the bracket.")
        else:
            out.append(f"{fast.share:.0%} already deliver within 7 days — speed is "
                       f"not an opening.")

    for s in (*profile.origins, *profile.delivery):
        if s.status == IGNORED:
            out.append(f"⚠️ '{s.label}' returned the unfiltered total — Etsy ignored "
                       f"that filter. Treat it as unmeasured, not as a match.")
    return out


# --- fetching -------------------------------------------------------------------------

# Etsy's ships-from filter takes GeoNames ids, not country codes. The list is
# discovered from the SERP rather than hardcoded: master_arbitrage pinned five
# countries by hand, which silently caps what any origin analysis can see.
GEONAME_RE = r'"displayName":"([^"]+)","geoname":"(\d+)"'

DEFAULT_COUNTRIES = ("United States", "United Kingdom", "Canada", "China", "India")
# Verified live 2026-08-15: Etsy accepts ONLY these. delivery_days=1 and =3 return
# the unfiltered total, i.e. they are silently ignored — caught by to_share().
DELIVERY_BRACKETS = ("7", "14", "21", "30")


def discover_geonames(public_api, query):
    """The countries Etsy will actually filter by, read off the SERP.

    Returns {display_name: geoname_id}. Empty on failure — callers must treat that
    as unmeasured rather than assuming the default five.
    """
    import re, urllib.parse
    url = "https://www.etsy.com/search?" + urllib.parse.urlencode(
        {"q": query, "explicit": "1"})
    try:
        html = public_api.session.request(
            "GET", url, headers=getattr(public_api, "headers", {}),
            platform="etsy").text
    except Exception:
        return {}
    i = html.find('"shipsFromProps"')
    if i < 0:
        return {}
    return dict(re.findall(GEONAME_RE, html[i:i + 8000].replace("\\", "")))


def fetch_profile(public_api, query, countries=DEFAULT_COUNTRIES,
                  brackets=DELIVERY_BRACKETS):
    """Measure origin and delivery shares for one query. One request per bracket.

    Every request is a free public SERP call, and only `total_results` is used —
    the listings themselves are discarded.
    """
    base = public_api.get_public_search(query)
    total = (base or {}).get("total_results")
    if not total:
        return build_profile(query, 0, {}, {},
                             notes=("unfiltered search returned no total",))

    geonames = discover_geonames(public_api, query)
    notes = []
    if not geonames:
        notes.append("could not read Etsy's country list; origins unmeasured")

    origin_counts = {}
    for name in countries:
        gid = geonames.get(name)
        if not gid:
            origin_counts[name] = None      # unmeasured, never 0
            continue
        d = public_api.get_public_search(query, filters={"locationQuery": gid})
        origin_counts[name] = (d or {}).get("total_results")

    delivery_counts = {}
    for days in brackets:
        d = public_api.get_public_search(query, filters={"delivery_days": days})
        delivery_counts[days] = (d or {}).get("total_results")

    if geonames and "Turkey" not in geonames and "Türkiye" not in geonames:
        notes.append("Turkey is absent from Etsy's filter list — Turkish sellers "
                     "fall into the unattributed remainder")

    return build_profile(query, total, origin_counts, delivery_counts, notes)


# --- lead time (délai) -----------------------------------------------------------------

def delivery_distribution(profile):
    """Turn the CUMULATIVE delivery brackets into a per-band distribution.

    `delivery_days=14` means "arrives within 14 days", so it *includes* the 7-day
    listings. Reading the raw brackets as bands would double-count the fast ones and
    understate how slow the tail really is.

    Returns [(band_label, share)] plus an explicit "over 30 days" remainder, which is
    the band that matters most for a gift with a deadline and the one no bracket
    reports directly.
    """
    got = {s.label: s for s in profile.delivery if s.status == "measured"}
    order = [b for b in ("7", "14", "21", "30") if b in got]
    if not order:
        return []

    out, previous = [], 0.0
    labels = {"7": "0-7 days", "14": "8-14 days", "21": "15-21 days", "30": "22-30 days"}
    for b in order:
        share = got[b].share
        out.append((labels[b], round(max(0.0, share - previous), 4)))
        previous = share
    out.append(("over 30 days", round(max(0.0, 1.0 - previous), 4)))
    return out


def median_band(profile):
    """The band the 50th-percentile listing falls in — the honest 'how long, typically'."""
    cumulative = 0.0
    for label, share in delivery_distribution(profile):
        cumulative += share
        if cumulative >= 0.50:
            return label
    return None


# --- per-listing origin ------------------------------------------------------------------

# Etsy ships the origin in the listing page's LD+JSON as
# shippingDetails.shippingOrigin{addressCountry, addressRegion}. There is NO per-listing
# lead time in the static HTML — "arrives by" is computed client-side against the
# buyer's address — so délai stays an aggregate measure via DELIVERY_BRACKETS.
ORIGIN_RE = (r'"shippingOrigin":\{[^}]*?"addressCountry":"([A-Z]{2})"'
             r'(?:[^}]*?"addressRegion":"([^"]*)")?')
SHIPS_FROM_RE = r"Ships from ([^.\"<]{3,60})"


def listing_origin(public_api, listing_id):
    """Where ONE listing actually ships from: {country, region, text} or None.

    Worth the request because a shop's NAME is not its origin. `TurkishTowelWeaving`
    sells "Turkish" towels and ships from East Hanover, NJ — inferring origin from
    branding would have been wrong, and confidently so.
    """
    import re as _re
    url = f"https://www.etsy.com/listing/{listing_id}"
    try:
        html = public_api.session.request(
            "GET", url, headers=getattr(public_api, "headers", {}),
            platform="etsy").text
    except Exception:
        return None

    m = _re.search(ORIGIN_RE, html)
    text = _re.search(SHIPS_FROM_RE, html)
    if not m and not text:
        return None
    return {
        "listing_id": str(listing_id),
        "country": m.group(1) if m else None,
        "region": (m.group(2) or None) if m else None,
        "text": text.group(1).strip() if text else None,
    }


# --- per-listing delivery estimate (the délai) --------------------------------------------

# Etsy renders it as:  Order today to get by <strong>Aug 24-28</strong>
# Two shapes: same-month "Aug 24-28" and cross-month "Aug 27-Sep 4". The second is the
# one a naive parser gets wrong, and it is also the one that matters — a range crossing
# a month boundary is the slow tail.
GET_BY_RE = r"Order today to get by\s*(?:<[^>]+>)*\s*([A-Z][a-z]{2}\s+\d{1,2}\s*[-–]\s*(?:[A-Z][a-z]{2}\s+)?\d{1,2})"
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_get_by(text, today=None):
    """'Aug 24-28' or 'Aug 27-Sep 4' -> {earliest, latest, days_min, days_max}.

    Returns None when it cannot parse. Never guesses a date: a wrong lead time would
    make a slow seller look fast, which is precisely the competitive read this is for.

    Etsy omits the year, so a range ending in a month EARLIER than it starts has rolled
    over into next year (Dec 28-Jan 5). Without that, the December case yields a
    negative lead time.
    """
    import re as _re
    from datetime import date, datetime
    if not text:
        return None
    m = _re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]{2})\s+)?(\d{1,2})",
                   text)
    if not m:
        return None
    start_mon, start_day, end_mon, end_day = m.groups()
    if start_mon not in _MONTHS or (end_mon and end_mon not in _MONTHS):
        return None

    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    year = today.year
    try:
        earliest = date(year, _MONTHS[start_mon], int(start_day))
        end_month = _MONTHS[end_mon] if end_mon else _MONTHS[start_mon]
        end_year = year + 1 if end_month < _MONTHS[start_mon] else year
        latest = date(end_year, end_month, int(end_day))
    except ValueError:
        return None

    # The estimate is always forward-looking; a start already behind us means the page
    # was rendered near a year boundary.
    if (earliest - today).days < -30:
        try:
            earliest = earliest.replace(year=year + 1)
            latest = latest.replace(year=latest.year + 1)
        except ValueError:
            return None

    return {
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "days_min": (earliest - today).days,
        "days_max": (latest - today).days,
        "text": m.group(0),
    }


def listing_shipping(public_api, listing_id, today=None):
    """Everything one listing says about shipping: origin, délai, returns, free shipping.

    This is the per-listing view the aggregate delivery_days brackets cannot give —
    those say what SHARE of a niche is fast, this says whether THIS competitor is.
    """
    import re as _re
    url = f"https://www.etsy.com/listing/{listing_id}"
    try:
        html = public_api.session.request(
            "GET", url, headers=getattr(public_api, "headers", {}),
            platform="etsy").text
    except Exception:
        return None

    origin = _re.search(ORIGIN_RE, html)
    ships_from = _re.search(r"Ships from:?\s*(?:<[^>]+>)*\s*([A-Za-z .'-]+,\s*[A-Z]{2})", html)
    get_by = _re.search(GET_BY_RE, html)

    return {
        "listing_id": str(listing_id),
        "country": origin.group(1) if origin else None,
        "region": (origin.group(2) or None) if origin else None,
        "ships_from": ships_from.group(1).strip() if ships_from else None,
        "delivery": parse_get_by(get_by.group(1), today) if get_by else None,
        # "accepted" / "not accepted" — a returns policy is a quality signal and a
        # cost the profit model does not yet carry.
        "returns_accepted": (True if _re.search(r"Returns &(?:amp;)? exchanges accepted", html)
                             else False if _re.search(r"Returns &(?:amp;)? exchanges not accepted", html)
                             else None),
        "free_shipping": bool(_re.search(r"\bFREE shipping\b", html, _re.I)) or None,
    }

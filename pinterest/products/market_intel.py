"""4. Market intelligence — who owns a category, and the taxonomy underneath it.

`top_products` returns real pins with a `merchant_name` on each: Target, Amazon, Walmart,
SheIn, Wayfair, independent Shopify stores. Counting them per category gives a
share-of-shelf reading for any vertical — no marketplace assumed, no seller identity
needed.

The second half of this module is the 383-entry taxonomy. It is not a flat list: every
entry carries `level`, `parent_product_category_id`, `children` and
`l2_product_category_ids`, which makes it a DAG (a node can hang off more than one L2
parent). That is a usable product classifier on its own — it is Pinterest's own clustering
of consumer goods, and nothing about it is Pinterest-specific once you have it.

Two hard rules the API enforces and this module respects:
  * the 14 level-1 verticals are parent-only ids — passing one as a product_category_id is
    a 400, every time
  * one bad id fails the whole call, so ids are validated before the request goes out

    .venv/Scripts/python.exe pinterest/products/market_intel.py "runner rugs"
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import VERTICALS
from pinterest.endpoints.local_math import event_summary, intent_ratio

STOPWORDS = {"and", "or", "the", "for", "with", "of", "&"}


# -- the taxonomy ------------------------------------------------------------------------
class Taxonomy:
    """The 383-node category DAG, fetched once and cached forever.

    Held as a class rather than a dict because every useful question about it is a
    traversal: what is this category's path, what sits under it, what does this product
    title look like.
    """

    def __init__(self, api, country="US"):
        self.raw = api.product_categories(country) or {}
        self.names = {cid: c.get("friendly_name") for cid, c in self.raw.items()}
        # Reverse index. The 14 level-1 verticals are referenced as parents but are NOT
        # entries in the 383-node map, so their `children` list does not exist and walking
        # down from "Fashion" returns nothing unless the edges are rebuilt from the child
        # side. Every L2 category names its vertical in parent_product_category_id.
        self._by_parent = {}
        for cid, c in self.raw.items():
            parent = c.get("parent_product_category_id")
            if parent:
                self._by_parent.setdefault(str(parent), []).append(cid)

    def name(self, cid):
        return self.names.get(str(cid)) or VERTICALS.get(str(cid)) or str(cid)

    def path(self, cid):
        """Root-to-node names. Walks `parent_product_category_id` until it leaves the map —
        the walk ends on a level-1 vertical, which is deliberately absent from the 383."""
        out, seen, cur = [], set(), str(cid)
        while cur and cur not in seen:
            seen.add(cur)
            out.append(self.name(cur))
            cur = (self.raw.get(cur) or {}).get("parent_product_category_id")
            if cur and cur not in self.raw:
                out.append(VERTICALS.get(str(cur)) or str(cur))
                break
        return list(reversed(out))

    def children(self, cid, deep=False):
        """Direct children, or the whole subtree with `deep`.

        Falls back to the reverse index when the node has no `children` key of its own,
        which is how a level-1 vertical becomes navigable downward at all.
        """
        cid = str(cid)
        kids = list((self.raw.get(cid) or {}).get("children") or self._by_parent.get(cid) or [])
        if not deep:
            return kids
        out, stack = [], list(kids)
        while stack:
            c = stack.pop()
            if c in out:
                continue
            out.append(c)
            stack.extend(self.children(c))
        return out

    def leaves(self):
        return [cid for cid, c in self.raw.items() if not c.get("children")]

    def search(self, text):
        """Substring match on friendly_name — the lookup a human actually does."""
        t = text.lower()
        return [(cid, n) for cid, n in self.names.items() if n and t in n.lower()]

    def classify(self, title, top=3):
        """Best-matching categories for a free-text product title.

        Scored on the share of the CATEGORY's words that the title covers, not the other
        way round: a long title should not be penalised, and a two-word category fully
        present in the title is a stronger signal than a five-word one half present.
        Deeper categories win ties, because a leaf is a more useful answer than its parent.
        """
        words = {w.strip(".,()") for w in title.lower().split()} - STOPWORDS
        scored = []
        for cid, name in self.names.items():
            if not name:
                continue
            cat_words = {w for w in name.lower().split()} - STOPWORDS
            if not cat_words:
                continue
            hit = len(cat_words & words) / len(cat_words)
            if hit:
                scored.append((hit, (self.raw.get(cid) or {}).get("level") or 0, cid, name))
        scored.sort(reverse=True)
        return [{"category_id": cid, "name": name, "score": round(s, 2),
                 "path": " > ".join(self.path(cid))} for s, _, cid, name in scored[:top]]


# -- the market ---------------------------------------------------------------------------
def merchant_share(api, category_id, country="US", event="OUTBOUND_CLICK"):
    """Share of a category's top pins by merchant. One request.

    Only OUTBOUND_CLICK returns rows on this endpoint — SAVE and ENGAGEMENT come back
    empty — so the reading is specifically "who captures the click", which is the closest
    thing to a purchase signal the surface offers.
    """
    pins = api.top_products(category_id, country=country, event=event) or []
    counts = Counter(p.get("merchant_name") or "(unattributed)" for p in pins)
    total = sum(counts.values()) or 1
    return {
        "category_id": str(category_id),
        "pins": total,
        "merchants": [{"merchant": m, "pins": n, "share": round(n / total, 3)}
                      for m, n in counts.most_common()],
        "concentration": round(max(counts.values()) / total, 3) if counts else None,
    }


def landscape(api, category_ids, country="US"):
    """Merchant share across several categories, plus who shows up in more than one.

    A merchant present across many categories is a platform; one that owns a single
    category outright is a specialist. Both are worth knowing and neither is visible from
    one category's page.
    """
    rows = [merchant_share(api, cid, country) for cid in category_ids]
    spread = Counter()
    for r in rows:
        for m in r["merchants"]:
            spread[m["merchant"]] += 1
    return {"categories": rows,
            "cross_category": [{"merchant": m, "categories": n}
                               for m, n in spread.most_common() if n > 1]}


def demand_table(api, country="US", event="OUTBOUND_CLICK"):
    """Every ranked category with both growth and relative volume, plus the intent ratio.

    One request. All three event summaries ride inside each row, so click-vs-save intent
    costs nothing extra — see local_math for why.
    """
    rows = api.top_categories(country=country, event=event) or []
    out = []
    for r in rows:
        summary = event_summary(r, event)
        out.append({
            "category_id": r["product_category"],
            "growth": summary.get("percent_growth"),
            "relative_volume": summary.get("percent_relative_volume"),
            "intent_ratio": intent_ratio(r),
            "related_terms": (r.get("related_search_trends") or [])[:8],
        })
    return out


def report(query="runner rugs", country="US"):
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}\n")
        tax = Taxonomy(api, country)
        print(f"Taxonomy: {len(tax.raw)} categories, {len(tax.leaves())} leaves\n")

        matches = tax.search(query)
        if not matches:
            print(f"No category named like {query!r}")
            return
        cid, name = matches[0]
        print(f"=== {name} ({cid}) — {' > '.join(tax.path(cid))} ===")

        share = merchant_share(api, cid, country)
        print(f"  {share['pins']} pins, top merchant holds {share['concentration']:.0%}")
        for m in share["merchants"][:8]:
            print(f"    {m['share']:>6.1%}  {m['pins']:>3}  {m['merchant']}")

        table = {r["category_id"]: r for r in demand_table(api, country)}
        row = table.get(cid)
        if row:
            ratio = f"{row['intent_ratio']:.2f}" if row["intent_ratio"] else "n/a"
            print(f"\n  growth {row['growth']}  relative volume {row['relative_volume']}  "
                  f"click/save intent {ratio}")
            print(f"  searched as: {', '.join(row['related_terms'][:6])}")

        print(f"\n=== classifier check ===")
        for c in tax.classify(f"handmade {query} for living room"):
            print(f"  {c['score']:.2f}  {c['name']:24} {c['path']}")


if __name__ == "__main__":
    report(sys.argv[1] if len(sys.argv) > 1 else "runner rugs")

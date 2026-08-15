"""Category from breadcrumbs — the field the blueprint work threw away.

The category decides which attribute filters exist, how buyers browse to a listing, and
where it competes. A wrong answer is expensive and a coin toss is not an answer, so a
thin or split sample refuses rather than picking the larger half.

Fixtures are the paths measured live 2026-08-15.

    .venv/Scripts/python.exe -m etsy.analytics.test_taxonomy
"""
from etsy.analytics.taxonomy import (category_consensus, known_categories,
                                     positioning_note)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


PARTY = ["Paper & Party Supplies", "Party Supplies", "Party Decor",
         "Garlands, Flags & Bunting"]
HOME = ["Home & Living", "Home Decor", "Wall Decor", "Wall Hangings"]
SEASONAL = ["Home & Living", "Home Decor", "Seasonal Decor"]

# --- agreement ---------------------------------------------------------------------
c = category_consensus([PARTY, PARTY, PARTY, PARTY])
check("a unanimous page one names the category", c["primary"] == "Paper & Party Supplies", c)
check("share is reported", c["primary_share"] == 1.0, c)
check("the full path is kept, not just the top level",
      c["full_path"] == PARTY, c["full_path"])
check("not flagged as split", c["is_split"] is False, c)
check("the note reads plainly", "page one agrees" in positioning_note(c), positioning_note(c))

# --- the real felt garland sample: 4 party, 2 home ----------------------------------
c = category_consensus([PARTY, PARTY, PARTY, PARTY, HOME, SEASONAL])
check("a 67% majority still names a primary",
      c["primary"] == "Paper & Party Supplies", c)
check("both top levels are counted",
      c["top_levels"] == {"Paper & Party Supplies": 4, "Home & Living": 2},
      c["top_levels"])
check("67% is above the split threshold", c["is_split"] is False, c)

# --- genuine disagreement is the interesting case ------------------------------------
c = category_consensus([PARTY, PARTY, PARTY, HOME, HOME, SEASONAL])
check("an even split is flagged", c["is_split"] is True, c)
note = positioning_note(c)
check("the note names both categories with counts", "vs" in note and "(3)" in note, note)
check("and points at the thinner one as the opening",
      "less crowded" in note, note)
# Collapsing this to a single winner would hide the most useful thing in it: two
# categories mean two sets of attribute filters and two crowding levels.

# --- refusals -------------------------------------------------------------------------
c = category_consensus([PARTY, HOME])
check("two listings is not a category decision", c["primary"] is None, c)
check("insufficient_sample is named", c["basis"] == "insufficient_sample", c)
check("no note for a refusal", positioning_note(c) is None)

check("empty input refuses", category_consensus([])["primary"] is None)
check("blank breadcrumbs are ignored, not counted",
      category_consensus([PARTY, [], [], PARTY])["basis"] == "insufficient_sample")
# A listing whose breadcrumb did not parse is not evidence of a category (N-02).

# --- the observed tree ----------------------------------------------------------------
tree = known_categories([PARTY, HOME])
check("every ancestor is recorded, not only leaves",
      ("Paper & Party Supplies",) in tree and ("Home & Living",) in tree, tree[:4])
check("deepest paths come first", len(tree[0]) >= len(tree[-1]), tree)
check("both branches survive", len(tree) == 8, len(tree))
# Built by observation rather than guessing taxonomy_id integers — which is how
# "Paper & Party Supplies" was missed entirely by the blind id probe.

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

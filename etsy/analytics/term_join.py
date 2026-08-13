"""
term_join.py

Layer: analytics/ (pure functions — no I/O, no imports from other layers)
Purpose: join a Pinterest term to an Etsy keyword so the two graphs can share data.

`pinterest/endpoints/overviews.md` §5 lists this as the join between the two node
sets — "lowercase, singularize, strip stopwords on both sides". Without it the
bridge writes "Mom Necklaces", the Etsy engine looks up "mom necklace", the exact
match misses, and the candidate is scored with no momentum at all. That is how a
free scoring dimension goes unused without anything reporting an error.

Key decision: **a wrong match is worse than no match.** Joining "dog collar" to
"cat collar" would import a different niche's momentum and present it as this
one's — a plausible wrong number, which is the failure this system is built to
avoid. So matching requires the full normalised content word set to be equal.
Word ORDER is allowed to differ ("necklace mom" == "mom necklace"), because that
carries no meaning here, but a missing or extra content word blocks the join.

Deliberately not fuzzy. No edit distance, no partial overlap, no "best guess"
scoring — those all produce confident wrong joins on short retail phrases where
one word IS the niche ("cat" vs "dog", "wedding" vs "birthday").
"""
import re

# Retail-search filler. These carry no niche meaning, and Pinterest and Etsy phrase
# them differently for the same idea ("gifts for mom" vs "mom gifts").
STOPWORDS = frozenset({
    "for", "the", "a", "an", "and", "or", "with", "to", "of", "in", "on",
    "your", "my", "his", "her", "their", "best", "top", "new",
})

# Endings where the plural is not a bare -s. Order matters: longest first.
_PLURAL_RULES = (
    ("ies", "y"),     # babies  -> baby
    ("ches", "ch"),   # watches -> watch
    ("shes", "sh"),   # dishes  -> dish
    ("xes", "x"),     # boxes   -> box
    ("zes", "z"),
    ("ses", "s"),     # dresses -> dress
)


def _singularise(word):
    """Best-effort singular. Conservative: when unsure, leave the word alone.

    A wrong stem ("dress" -> "dres") silently breaks every future match for that
    term, and nothing reports it — so the rules below refuse rather than guess.
    """
    if len(word) <= 3:
        return word
    for suffix, replacement in _PLURAL_RULES:
        if word.endswith(suffix):
            return word[: -len(suffix)] + replacement
    # A word already ending in -ss ("glass", "dress") is not a plural.
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize(term):
    """Canonical form of a search term, for comparison only — never for display.

    Lowercase, strip punctuation, singularise each word, drop stopwords.
    """
    if not term:
        return ""
    text = str(term).lower()
    # Apostrophes are DELETED, not spaced: "mom's" -> "moms" -> "mom". Spacing them
    # would leave a stray "s" token that blocks every match.
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [_singularise(w) for w in text.split() if w]
    content = [w for w in words if w not in STOPWORDS]
    # A term made only of stopwords ("for the") would normalise to nothing and then
    # match every other empty term. Keep the original words rather than collapse.
    return " ".join(content or words)


def content_words(term):
    """The normalised word SET — order-independent, for matching."""
    return frozenset(normalize(term).split())


def best_match(term, candidates):
    """The candidate whose content words exactly equal `term`'s, else None.

    Returns the candidate in its ORIGINAL form, because that is the key the caller
    needs to look the record back up.

    Exact set equality, not overlap: "necklace" must not claim "mom necklace", since
    the second is a narrower niche with different demand. Refusing here costs a
    missing momentum value; matching wrongly costs a wrong recommendation.
    """
    target = content_words(term)
    if not target:
        return None
    for candidate in candidates or []:
        if content_words(candidate) == target:
            return candidate
    return None

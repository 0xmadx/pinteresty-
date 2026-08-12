"""Offline test for P-3 — a defaulted CVR must not store as if measured. No network.

private_blueprint wrote through upsert_keyword, which stamps cvr_source='unspecified'
for every row, so a CVR the API returned and the 0.02 fallback were indistinguishable
once stored. This checks record_keyword carries the real provenance the engine now
passes, and that an "Unknown" price stores as None rather than a fabricated 0.0.

Run:  python -m core.test_keyword_provenance
"""
import os
import sys
import tempfile

from core.database import MarketDatabase

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def latest(db, keyword):
    rows = db.get_keyword_history(keyword) if hasattr(db, "get_keyword_history") else None
    return (rows[-1] if rows else None) or db.get_keyword(keyword)


def main():
    db = MarketDatabase(db_path=os.path.join(tempfile.mkdtemp(), "m.db"))

    # A measured CVR is tagged 'measured'.
    db.record_keyword(keyword="mom necklace", source="etsy_private", volume=9000,
                      competition=48000, cvr=0.031, cvr_source="measured",
                      price_low=12.5, price_high=28.0, price_basis="measured")
    row = latest(db, "mom necklace")
    check("a measured CVR stores cvr_source='measured'",
          row["cvr_source"] == "measured", f"got {row['cvr_source']}")
    check("the measured price is stored, not zeroed",
          row["median_price_low"] == 12.5)

    # A defaulted CVR is tagged 'default', and 0.02 is not mistaken for a measurement.
    db.record_keyword(keyword="rare term", source="etsy_private", volume=200,
                      competition=50, cvr=0.02, cvr_source="default",
                      price_low=None, price_high=None, price_basis="absent")
    row = latest(db, "rare term")
    check("a defaulted CVR stores cvr_source='default', never 'unspecified'",
          row["cvr_source"] == "default", f"got {row['cvr_source']}")
    check("an unknown price stores as NULL, not a fabricated 0.0",
          row["median_price_low"] is None, f"got {row['median_price_low']}")
    check("and price_basis says it was absent",
          row["price_basis"] == "absent", f"got {row['price_basis']}")

    # The two are now distinguishable in storage — the whole point of P-3.
    check("measured and defaulted CVRs are distinguishable once stored",
          latest(db, "mom necklace")["cvr_source"]
          != latest(db, "rare term")["cvr_source"])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

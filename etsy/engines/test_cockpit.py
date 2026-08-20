"""One candidate, three sources, and the disagreements that must survive combining.

The Cockpit is the screen the three-source design exists for. Its whole value is
that Pinterest, Etsy Private and Etsy Public are read SEPARATELY and their
conflicts reported — because they fail differently, and a blended score hides
exactly the case the operator needs: a perfectly-timed term nobody can rank for.

The other half of these tests is the trend, which is where this data is most
likely to produce a confident lie. Two readings minutes apart are not history, and
a change measured against a barely-successful reading describes our instrument.

    .venv/Scripts/python.exe -m etsy.engines.test_cockpit
"""
import os
import tempfile
from datetime import datetime, timezone

from core.database import MarketDatabase
from etsy.engines import cockpit

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def seed(path):
    db = MarketDatabase(db_path=path)
    db.record_trend(trend_name="christmas", source="pinterest_moments", country="US",
                    takeoff_timestamp="2026-10-28", peak_date="2026-12-09",
                    phase="approaching", takeoff_basis="measured")
    # A wall: real demand, impossible supply.
    db.record_keyword("christmas ornament", volume=25477, competition=1405731,
                      cvr=0.00027, cvr_source="measured", price_low=7.2,
                      price_high=8.8, collected_at="2026-08-19T12:00:00+00:00")
    # Rankable, and untimed.
    db.record_keyword("backpack name tag", volume=69874, competition=25031,
                      cvr=0.00279, cvr_source="measured", price_low=18.0,
                      price_high=22.0, collected_at="2026-08-19T12:00:00+00:00")
    # A page-one competition reading: one dimension decisive, others withheld, and
    # far more ranked ids than were sampled.
    db.record_keyword_competition(
        "christmas ornament", total_results=1405731, organic_sample=6,
        ranked_ids_count=41,
        saturation={
            "quality|star_seller": {"share": 1.0, "low": 0.61, "high": 1.0,
                                    "sample": 6, "can_discriminate": True},
            "free_shipping|true": {"share": 0.33, "low": 0.10, "high": 0.70,
                                   "sample": 6, "can_discriminate": False},
        })
    return db


def main():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "c.db")
    seed(path)

    # --- three sources, read apart ------------------------------------------------
    print()
    s = cockpit.build("christmas ornament", db_path=path, now=NOW)
    check("Pinterest answers when", s["timing"]["basis"] == "measured", s["timing"])
    check("Etsy Private answers demand", s["demand"]["volume"] == 25477)
    check("Etsy Public answers competition", s["supply"]["listings"] == 1405731)
    check("and they are separate keys, never pre-blended",
          {"timing", "demand", "supply"} <= set(s))

    # --- the disagreement is the output -------------------------------------------
    print()
    c = s["combined"]
    check("a well-timed wall raises a CONFLICT, not a middling score",
          len(c["conflicts"]) == 1, c["conflicts"])
    check("the conflict names both readings",
          "Pinterest" in c["conflicts"][0] and "cannot rank" in c["conflicts"][0])
    check("and the verdict is a plain no", c["call"] == "no", c["call"])
    check("with the blocker stated", any("cannot rank" in b for b in c["blockers"]))

    # --- a rankable, untimed term -----------------------------------------------------
    print()
    s2 = cockpit.build("backpack name tag", db_path=path, now=NOW)
    check("an unmatched term reports UNTIMED, not badly timed",
          s2["timing"]["basis"] == "unmeasured"
          and "not the same as badly timed" in s2["timing"]["note"])
    check("2.79 demand per listing is not a wall", s2["supply"]["is_wall"] is False)
    check("and the verdict says yes, with the timing caveat attached",
          s2["combined"]["call"] == "yes, but untimed", s2["combined"]["call"])
    check("no conflict is invented where none exists",
          s2["combined"]["conflicts"] == [], s2["combined"]["conflicts"])

    # --- a term never measured ----------------------------------------------------------
    print()
    s3 = cockpit.build("never seen", db_path=path, now=NOW)
    check("an unmeasured term does not crash", s3["demand"]["basis"] == "unmeasured")
    check("it says how to fix it", "settings_store term add" in s3["demand"]["note"])
    check("and the verdict is no, for lack of evidence rather than bad evidence",
          s3["combined"]["call"] == "no"
          and any("no demand measurement" in b for b in s3["combined"]["blockers"]),
          s3["combined"]["blockers"])

    # --- THE TREND, where a confident lie is easiest -------------------------------------
    print()
    p2 = os.path.join(tmp, "t.db")
    db = MarketDatabase(db_path=p2)
    # Five readings in one evening: five rows, no history.
    for i, minute in enumerate((0, 8, 20, 35, 50)):
        db.record_keyword("linen apron", volume=2293, competition=73883, cvr=0.0008,
                          cvr_source="measured", price_low=28.8, price_high=35.2,
                          collected_at=f"2026-08-19T23:{minute:02d}:00+00:00")
    t = cockpit.build("linen apron", db_path=p2, now=NOW)["demand"]["trend"]
    check("five readings on one evening are not a trend",
          t["basis"] == "unmeasured", t)
    check("and it says why, rather than reporting 0% change",
          "one reading" in t["note"], t["note"])

    # A degraded baseline. Real case: ceramic planter pot read 4,776 -> 589, an 88%
    # "collapse", where the older reading had fallen back to a default CVR.
    p3 = os.path.join(tmp, "d.db")
    db = MarketDatabase(db_path=p3)
    db.record_keyword("ceramic planter pot", volume=4776, competition=130673,
                      cvr=0.02, cvr_source="default",
                      collected_at="2026-08-13T03:00:00+00:00")
    db.record_keyword("ceramic planter pot", volume=589, competition=75769,
                      cvr=0.00009, cvr_source="measured",
                      collected_at="2026-08-19T23:00:00+00:00")
    t = cockpit.build("ceramic planter pot", db_path=p3, now=NOW)["demand"]["trend"]
    check("an 88% move against a DEGRADED baseline is refused, not reported",
          t["basis"] == "refused", t)
    check("and the refusal explains it would measure our instrument",
          "our own measurement" in t["note"], t["note"])

    # A real change, against a clean baseline, over a real gap.
    p4 = os.path.join(tmp, "r.db")
    db = MarketDatabase(db_path=p4)
    db.record_keyword("felt garland", volume=2000, competition=29000, cvr=0.0003,
                      cvr_source="measured", collected_at="2026-08-12T00:00:00+00:00")
    db.record_keyword("felt garland", volume=2727, competition=29017, cvr=0.0003,
                      cvr_source="measured", collected_at="2026-08-19T00:00:00+00:00")
    t = cockpit.build("felt garland", db_path=p4, now=NOW)["demand"]["trend"]
    check("a clean baseline over 7 days DOES produce a trend",
          t["basis"] == "measured", t)
    check("with the direction and both endpoints",
          t["change"] > 0 and t["from"] == 2000 and t["to"] == 2727, t)
    check("and it is flagged material, above the noise floor", t["material"] is True)

    # A move below the noise floor is reported and marked, not hidden.
    p5 = os.path.join(tmp, "n.db")
    db = MarketDatabase(db_path=p5)
    db.record_keyword("x", volume=1000, competition=5000, cvr=0.001,
                      cvr_source="measured", collected_at="2026-08-12T00:00:00+00:00")
    db.record_keyword("x", volume=1020, competition=5000, cvr=0.001,
                      cvr_source="measured", collected_at="2026-08-19T00:00:00+00:00")
    t = cockpit.build("x", db_path=p5, now=NOW)["demand"]["trend"]
    check("a 2% move is measured but flagged as noise, not called growth",
          t["basis"] == "measured" and t["material"] is False, t)

    # --- a default CVR is a blocker, not a footnote ----------------------------------------
    print()
    p6 = os.path.join(tmp, "g.db")
    db = MarketDatabase(db_path=p6)
    db.record_keyword("guessy", volume=50000, competition=10000, cvr=0.02,
                      cvr_source="default", price_low=30.0, price_high=40.0,
                      collected_at="2026-08-19T00:00:00+00:00")
    c6 = cockpit.build("guessy", db_path=p6, now=NOW)["combined"]
    check("a great ratio with a GUESSED CVR is still blocked",
          c6["call"] == "no", c6)
    check("and the guess is named as the reason",
          any("DEFAULT" in b for b in c6["blockers"]), c6["blockers"])

    # --- page-one competition is joined at read time, never merged --------------------
    print()
    comp = cockpit.build("christmas ornament", db_path=path, now=NOW)["supply"]["competition"]
    check("a stored saturation reading is attached to supply",
          comp["basis"] == "measured", comp)
    check("only DECISIVE dimensions are surfaced",
          [d["dimension"] + "=" + d["value"] for d in comp["decisive"]]
          == ["quality=star_seller"], comp["decisive"])
    check("a withheld dimension is counted, not shown as a share",
          comp["withheld"] == 1, comp)
    check("the upgrade path names the concrete next step",
          comp["upgrade"] and "41 ranked" in comp["upgrade"], comp["upgrade"])
    check("a term with no competition reading says unmeasured, not zero saturation",
          cockpit.build("backpack name tag", db_path=path, now=NOW)["supply"]
          .get("competition", {}).get("basis") == "unmeasured")

    # The saturation denominators must never touch the market-wide ones: page-one
    # star-seller is 100% of 6, market supply is 1.4M listings. They are different
    # units and the join keeps them apart.
    sup = cockpit.build("christmas ornament", db_path=path, now=NOW)["supply"]
    check("market supply and page-one share live in separate fields",
          sup["listings"] == 1405731 and comp["decisive"][0]["share"] == 1.0, sup)

    # --- the rendering keeps the order ------------------------------------------------------
    print()
    lines = cockpit.read(s)
    joined = "\n".join(lines)
    check("sources are printed before the verdict",
          joined.index("PINTEREST") < joined.index("ETSY PRIVATE")
          < joined.index("ETSY PUBLIC") < joined.index("VERDICT"))
    check("the disagreement is surfaced above the verdict",
          joined.index("SOURCES DISAGREE") < joined.index("VERDICT"))
    check("and every verdict carries that it is provisional",
          "provisional" in joined)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())

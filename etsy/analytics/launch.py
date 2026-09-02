"""Record a launch — the prediction half of the LEARN loop (M-3).

The launch itself happens outside this system: the operator lists a product on Etsy and
only then does a `listing_id` exist. This is the step that ties that id back to what the
system predicted when it recommended the niche.

    python -m etsy.analytics.launch --seed "mom necklace" --listing-id 1370681297

It reads the prediction snapshot `listing_generator` wrote beside the brief, so the
numbers recorded are the ones that were true **at the time of the decision**. Passing
`--score` / `--profit` overrides them; with no snapshot and no overrides it still records
the launch, with NULL predictions and a warning — a launch with no prediction is worth
less than one with, but far more than a launch nobody recorded.

Why not fabricate the prediction by re-querying now: volume, supply and SERP strength all
move. A "prediction" reconstructed after the outcome is known is not a prediction, and
scoring the model against it would flatter it silently.
"""
import argparse
import json
import os
import sys

from core.graph_db import GraphDB

PREDICTION_DIR = os.path.join("etsy", "data", "outputs")


def prediction_path(seed):
    return os.path.join(PREDICTION_DIR, f"{seed.replace(' ', '_')}.prediction.json")


def load_prediction(seed):
    """The snapshot written at generation time, or None if there isn't one."""
    path = prediction_path(seed)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def record(seed, listing_id, score=None, profit=None, product_type=None, notes=None,
           db=None, is_control=False):
    """Attach a real listing_id to the stored prediction. Returns the recorded row."""
    db = db or GraphDB()
    snapshot = load_prediction(seed)

    if snapshot is None and score is None and profit is None:
        print(f"[!] No prediction snapshot at {prediction_path(seed)} and no --score/"
              f"--profit given.")
        print(f"[!] Recording the launch with NULL predictions. The outcome will still "
              f"be tracked, but this launch cannot tell you whether the model was right.")

    db.record_launch(
        listing_id=str(listing_id),
        term_id=seed,
        predicted_score=score,
        predicted_profit=profit,
        product_type=product_type,
        is_control=is_control,
        notes=notes or (f"snapshot {snapshot['generated_at']}" if snapshot else None),
    )

    n = db.launch_count()
    print(f"[+] Recorded launch: listing {listing_id} for '{seed}'"
          + ("  [CONTROL]" if is_control else ""))
    if snapshot:
        print(f"    prediction from {snapshot['generated_at']}: "
              f"gap={snapshot.get('gap_score')} serp={snapshot.get('serp_score')} "
              f"volume={snapshot.get('volume')} supply={snapshot.get('supply')}")
    print(f"[+] {n} launch(es) recorded total.")
    if n < 10:
        print(f"[i] D-12 holds auto-tuning until 10 launches — {10 - n} to go. Below "
              f"that, outcomes cannot separate a good model from luck.")

    # B-04: without controls the loop only ever sees the model's own picks, so it can
    # measure precision but never recall. Nagging here rather than at calibration time,
    # because by then the sample is already fixed and cannot be repaired retroactively.
    ratio = db.control_ratio()
    if ratio is not None and ratio < 0.1:
        shortfall = max(1, int(round(0.1 * n)) - db.launch_count(controls_only=True))
        print(f"[!] Only {ratio:.0%} of launches are controls (target ~10%). "
              f"Launch {shortfall} deliberately mid/low-scored listing(s) with "
              f"--control, or calibration will only ever confirm what the model "
              f"already believes.")
    print(f"[i] Track its rank with: python -m etsy.analytics.rank_tracker")
    return db.get_launches(term_id=seed)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record a launched listing (M-3).")
    parser.add_argument("--seed", required=True,
                        help="The term the listing was launched against")
    parser.add_argument("--listing-id", required=True, help="The live Etsy listing id")
    parser.add_argument("--score", type=float, default=None,
                        help="Override the predicted opportunity score")
    parser.add_argument("--profit", type=float, default=None,
                        help="Override the predicted weekly profit")
    parser.add_argument("--product-type", default=None,
                        help="digital | physical | personalized")
    parser.add_argument("--control", action="store_true",
                        help="Mark as a CONTROL: a deliberate mid/low-scored launch. "
                             "Roughly 1 in 10 should be one — they are the only rows "
                             "that can show what the model wrongly rejected (B-04).")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args(argv)

    record(args.seed, args.listing_id, args.score, args.profit,
           args.product_type, args.notes, is_control=args.control)
    return 0


if __name__ == "__main__":
    sys.exit(main())


def record_result(seed, listing_id, score=None, profit=None, product_type=None,
                  notes=None, db=None, is_control=False):
    """`record()` as a RETURN VALUE rather than a wall of prints.

    Same write, structured output — so a surface other than the CLI can report what
    happened. `record()` prints and returns raw rows, which is right for a terminal
    and useless to MCP or a web app (D-64: the judgement belongs here, the envelope
    belongs to the caller).

    The two warnings are the point of the payload, not decoration:

      * **D-12** holds auto-tuning until 10 launches. Below that, outcomes cannot
        separate a good model from luck.
      * **B-04** — without deliberate mid/low-scored CONTROLS the loop only ever sees
        the model's own picks, so it can measure precision and never recall. It can
        never learn it was wrong to REJECT something. Nagged here rather than at
        calibration time, because by then the sample is fixed and cannot be repaired.
    """
    db = db or GraphDB()
    snapshot = load_prediction(seed)
    predictionless = snapshot is None and score is None and profit is None

    db.record_launch(
        listing_id=str(listing_id), term_id=seed,
        predicted_score=score, predicted_profit=profit,
        product_type=product_type, is_control=is_control,
        notes=notes or (f"snapshot {snapshot['generated_at']}" if snapshot else None),
    )

    n = db.launch_count()
    controls = db.launch_count(controls_only=True)
    ratio = db.control_ratio()
    warnings = []
    if predictionless:
        warnings.append(
            "Recorded with NULL predictions — no stored snapshot and no score/profit "
            "given. The OUTCOME will still be tracked, but this launch cannot tell "
            "you whether the model was right, which is the only reason to record it.")
    if n < 10:
        warnings.append(f"D-12 holds calibration until 10 launches — {10 - n} to go. "
                        f"Below that, outcomes cannot separate a good model from luck.")
    if ratio is not None and ratio < 0.1:
        short = max(1, int(round(0.1 * n)) - controls)
        warnings.append(
            f"Only {ratio:.0%} of launches are CONTROLS (target ~10%). Launch {short} "
            f"deliberately mid/low-scored listing(s) as controls, or calibration will "
            f"only ever confirm what the model already believes (B-04).")

    return {
        "listing_id": str(listing_id), "term": seed, "is_control": bool(is_control),
        "predicted_score": score, "predicted_profit": profit,
        "prediction_source": ("stored snapshot" if snapshot else
                              "caller-supplied" if not predictionless else "NONE"),
        "launches_total": n, "controls": controls,
        "control_ratio": ratio,
        "launches_until_calibration": max(0, 10 - n),
        "warnings": warnings,
        "basis": "measured",
        "next": "Rank tracking now includes this listing — it runs in the daily "
                "scheduler (job rank_check) and was returning [] until the first "
                "launch existed. Record outcomes with graph_db.record_launch_outcome.",
    }

"""The hunt — one command, no keyword typed.

    discover      Etsy's trending terms, ranked by winnability (not volume)
      → calendar  attach the seasonal deadline, if the term has one
      → gate      profit verdict at market prices
      → blueprint title, 13 tags, price, CTR checklist — for survivors ONLY

The ordering is the product. A blueprint is a instruction to go build something, so it
is generated only for candidates that are **winnable and profitable**. Printing one for
every trending term would be faster to write and would hand the operator a
confident-looking plan for a niche that loses money on every unit.

Measured 2026-08-15, this is not hypothetical: `first day of school sign` is the most
winnable term Etsy surfaced — 172,705 searches, 64,555 listings, the best CVR on the
board, seasonal, in season — and its median band tops out at $13.20, giving 13.9%
margin against a 35% floor. Offense finds it; the gate stops it. No blueprint.

    .venv/Scripts/python.exe -m etsy.analytics.hunt --profile "Felt decor"
"""
from etsy.analytics import discover, opportunity
from etsy.analytics.blueprint_support import material_for_term


def hunt(api, public_api, settings, profile_name, limit=8, calendar_rows=None,
         min_ratio=0.25):
    """Candidates → verdicts → blueprints for the ones worth building.

    `min_ratio` drops walls before any private-tier call is spent on them: a term with
    two million listings does not become winnable because the margin is good.
    """
    from etsy.api.private.api import parse_results_data

    def fetch(term):
        raw = api.get_results_data(term)
        return parse_results_data(raw) if raw else None

    candidates = discover.trending_candidates(api)
    if calendar_rows:
        candidates = discover.attach_moments(candidates, calendar_rows)
    ranked = discover.rank_by_opportunity(candidates[:limit * 2], fetch)

    results = []
    for candidate in ranked:
        win = candidate["winnability"]
        ratio = win.get("demand_per_listing")
        if ratio is None or ratio < min_ratio:
            results.append({**candidate, "stage": "rejected_unwinnable",
                            "reason": win.get("reason") or "could not be sized"})
            continue
        if len(results) >= limit and any(r.get("blueprint") for r in results):
            break

        data = fetch(candidate["term"])
        if not data:
            results.append({**candidate, "stage": "fetch_failed"})
            continue

        verdict = opportunity.evaluate(candidate["term"], data, settings, profile_name)
        if not verdict.get("verdict"):
            results.append({**candidate, "stage": "unjudged",
                            "reason": verdict.get("reason"), "market": verdict["market"]})
            continue
        if not verdict["verdict"]["go"]:
            # A rejection is only meaningful if the candidate was costed as the kind of
            # thing it actually is. One profile is applied to every candidate here, so
            # a digital term judged with a physical profile ("digital products" came
            # back at -142% margin with $4 COGS and 12 minutes of labour attached) is
            # not rejected — it is UNJUDGED, and saying otherwise would retire a real
            # opportunity for a reason that is an artefact of our own settings.
            impossible = verdict["verdict"]["profit_per_unit"] <= 0
            results.append({**candidate,
                            "stage": "unjudged" if impossible else "rejected_by_gate",
                            "verdict": verdict["verdict"],
                            "reason": ("; ".join(verdict["verdict"]["reasons"][:2])
                                       + (f" — but costed as '{profile_name}'; if this "
                                          f"is not that kind of product the verdict is "
                                          f"about the profile, not the niche"
                                          if impossible else ""))})
            continue

        # Survivor: worth the extra public calls a blueprint costs.
        results.append({**candidate, "stage": "blueprint",
                        "verdict": verdict["verdict"],
                        "blueprint": _blueprint_for(candidate["term"], data, public_api,
                                                    settings, profile_name)})
    return results


def _blueprint_for(term, data, public_api, settings, profile_name):
    from etsy.analytics import profit
    from etsy.generators import blueprint as bp

    # One SERP pass yields both: tags for the listing copy, breadcrumbs for where to
    # file it. Fetching the same pages twice to read two fields would be the obvious
    # waste, and breadcrumbs were previously discarded from calls already being made.
    consensus, category = material_for_term(public_api, term)
    kwargs = settings.verdict_kwargs(profile_name)

    def verdict_for_price(price):
        return profit.verdict(price=price, demand_units_per_week=0, **kwargs)

    return bp.build(term, data, consensus, verdict_for_price,
                    product_type=settings.profile(profile_name)["product_type"],
                    category=category)


def render(results):
    from etsy.generators import blueprint as bp

    lines, survivors = [], 0
    icon = {"blueprint": "🟢", "rejected_by_gate": "🔴", "rejected_unwinnable": "⬛",
            "unjudged": "⚪", "fetch_failed": "⚪"}
    lines.append("── CANDIDATES ──")
    for r in results:
        ratio = (r.get("winnability") or {}).get("demand_per_listing")
        ratio_text = f"{ratio:>6.2f}/listing" if ratio is not None else "     unsized"
        lines.append(f"{icon[r['stage']]} {ratio_text}  {r['term']:<28} {r['stage']}")
        if r.get("reason"):
            lines.append(f"{'':<16}   ↳ {r['reason']}")
        if r["stage"] == "blueprint":
            survivors += 1

    for r in results:
        if r["stage"] == "blueprint":
            lines.append("")
            lines.append(bp.render(r["blueprint"]))

    lines.append("")
    lines.append(f"── {survivors} of {len(results)} candidates survived to a blueprint ──")
    unjudged = sum(1 for r in results if r["stage"] == "unjudged")
    if unjudged:
        lines.append(f"   {unjudged} could not be judged — costed with a profile that "
                     f"may not describe them (see D-22: type must be DETECTED).")
    if not survivors:
        # Not a failure. A week where nothing clears the gate is information, and
        # manufacturing a recommendation to fill the screen is the one thing this
        # system exists not to do.
        lines.append("Nothing cleared both winnability and the profit gate this run. "
                     "That is an answer, not an empty screen.")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(prog="hunt")
    parser.add_argument("--profile", required=True, help="product profile from settings")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--no-calendar", action="store_true")
    args = parser.parse_args(argv)

    from core.preflight import PreflightFailed, require
    from core.settings_store import load
    from etsy.api.private.api import EtsyPrivateAPI
    from etsy.api.public.api import EtsyPublicAPI

    try:
        require("etsy", "etsy_private")
    except PreflightFailed as exc:
        print(exc)
        return 1

    settings = load()
    if args.profile not in settings.profiles():
        print(f"No product profile {args.profile!r}. Known: "
              f"{', '.join(settings.profiles()) or '(none)'}")
        return 1

    rows = None
    if not args.no_calendar:
        from etsy.analytics.calendar import build as build_calendar
        from pinterest.endpoints.api import PinterestTrendsAPI
        with PinterestTrendsAPI() as pin:
            rows = build_calendar(pin.moments_calendar(country="US"))

    results = hunt(EtsyPrivateAPI(), EtsyPublicAPI(), settings, args.profile,
                   limit=args.limit, calendar_rows=rows)
    print(render(results))

    basis = settings.basis()
    if basis["unconfirmed"]:
        print(f"\n⚠️  {len(basis['unconfirmed'])} fee/rate values are still defaults — "
              f"every verdict above is provisional.")
        print("    python -m core.settings_store show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

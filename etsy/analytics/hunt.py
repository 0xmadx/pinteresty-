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


def hunt(api, public_api, settings, limit=8, calendar_rows=None, min_ratio=0.25,
         llm=None, seed=None):
    """Candidates → typed → verdicts → blueprints for the ones worth building.

    Two front doors:
      * default — Etsy's 28 curated trending terms (head terms, one level deep)
      * `seed` — a recursive crawl from one keyword, which surfaces the winnable
        long-tail POCKETS the curated list never shows. This is the mixed engine: the
        crawl (hunter + data scientist) finds the pockets, and each then runs the full
        judgement pipeline — product type, profit gate, blueprint (analyst + SEO).

    Each candidate is costed with a profile matching its DETECTED product type (D-22),
    not one blanket profile. `min_ratio` drops walls before a private-tier call is spent
    on them. `llm` is the D-27 fallback for an ambiguous product type only.
    """
    from etsy.analytics.blueprint_support import resolve_product_type
    from etsy.api.private.api import parse_results_data

    def fetch(term):
        raw = api.get_results_data(term)
        return parse_results_data(raw) if raw else None

    if seed:
        # The crawl already sized every node (volume/supply inline), so pockets arrive
        # pre-ranked by winnability with no extra fetch. Only the winnable-enough ones
        # are worth the private results-data call each candidate below costs.
        from etsy.analytics import keyword_crawl
        nodes = keyword_crawl.crawl(api, seed, max_nodes=limit * 12, max_depth=3)
        pocket = keyword_crawl.pockets(nodes, min_ratio=min_ratio)
        candidates = [{"term": n["term"], "volume": n["volume"], "supply": n["supply"],
                       "categories": [f"from seed '{seed}'"], "basis": "seed_crawl"}
                      for n in pocket]
        if calendar_rows:
            candidates = discover.attach_moments(candidates, calendar_rows)
        ranked = discover.rank_expanded(candidates)
    else:
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

        # Type the candidate, then cost it with a profile that actually describes it.
        typed = resolve_product_type(public_api, candidate["term"], llm=llm)
        product_type = typed["product_type"]
        profile_name = settings.profile_for_type(product_type) if product_type else None
        if not profile_name:
            results.append({**candidate, "stage": "unjudged", "product_type": typed,
                            "reason": _no_profile_reason(settings, product_type, typed)})
            continue

        verdict = opportunity.evaluate(candidate["term"], data, settings, profile_name)
        if not verdict.get("verdict"):
            results.append({**candidate, "stage": "unjudged", "product_type": typed,
                            "reason": verdict.get("reason"), "market": verdict["market"]})
            continue
        if not verdict["verdict"]["go"]:
            results.append({**candidate, "stage": "rejected_by_gate",
                            "product_type": typed, "profile": profile_name,
                            "verdict": verdict["verdict"],
                            "reason": "; ".join(verdict["verdict"]["reasons"][:2])})
            continue

        # Survivor: worth the extra public calls a blueprint costs.
        results.append({**candidate, "stage": "blueprint", "product_type": typed,
                        "profile": profile_name, "verdict": verdict["verdict"],
                        "blueprint": _blueprint_for(candidate["term"], data, public_api,
                                                    settings, profile_name)})
    return results


def _no_profile_reason(settings, product_type, typed):
    """Why a candidate could not be costed — a missing-input problem, not a rejection."""
    if not product_type:
        return (f"product type undetermined ({typed['basis']}); cannot pick a profile "
                f"or a margin floor without it")
    others = settings.profiles_of_type(product_type)
    if not others:
        return (f"detected {product_type} ({typed['basis']}), but no {product_type} "
                f"profile exists — add one with settings_store")
    return (f"detected {product_type}, but {len(others)} {product_type} profiles exist "
            f"({', '.join(others)}); which one is a cost decision only you can make")


def _blueprint_for(term, data, public_api, settings, profile_name):
    from etsy.analytics import profit
    from etsy.generators import blueprint as bp

    # One SERP pass yields tags for the copy, breadcrumbs for where to file it, and the
    # product type (the third value, already consumed upstream to pick the profile).
    consensus, category, _ = material_for_term(public_api, term)
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
        pt = (r.get("product_type") or {}).get("product_type")
        basis = (r.get("product_type") or {}).get("basis")
        # A type read from listings is trusted; one guessed by the LLM is flagged with
        # '?', so a verdict resting on a guess is never mistaken for one resting on
        # measurement.
        type_text = f" [{pt}{'?' if basis == 'llm_fallback' else ''}]" if pt else ""
        lines.append(f"{icon[r['stage']]} {ratio_text}  {r['term']:<26}{type_text:<15} "
                     f"{r['stage']}")
        if r.get("reason"):
            lines.append(f"{'':<16}   ↳ {r['reason']}")
        if r["stage"] == "blueprint":
            survivors += 1

    for r in results:
        if r["stage"] == "blueprint":
            lines.append("")
            lines.append(bp.render(r["blueprint"]))

    # Show the detected type next to each judged candidate, so a rejection is legibly
    # about the niche costed as the right kind of thing, not an artefact of one profile.
    for r in results:
        pt = (r.get("product_type") or {}).get("product_type")
        if pt and r.get("profile"):
            basis = r["product_type"]["basis"]
            flag = " (llm-guessed)" if basis == "llm_fallback" else ""
            # annotate the already-printed line implicitly via the reason field instead
    lines.append("")
    lines.append(f"── {survivors} of {len(results)} candidates survived to a blueprint ──")
    unjudged = sum(1 for r in results if r["stage"] == "unjudged")
    if unjudged:
        lines.append(f"   {unjudged} could not be judged — type undetermined or no "
                     f"matching profile (see D-22: type must be DETECTED).")
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
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--seed", help="hunt the long-tail POCKETS around one keyword, "
                        "instead of Etsy's 28 curated trending terms")
    parser.add_argument("--no-calendar", action="store_true")
    parser.add_argument("--llm", action="store_true",
                        help="use DeepSeek to classify terms whose page-one type is "
                             "ambiguous (D-27 fallback; flagged in output)")
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
    if not settings.profiles():
        print("No product profiles defined. The hunt costs each candidate with a "
              "profile matching its detected type — add at least one:")
        print("  python -m core.settings_store profile add \"Digital printable\" "
              "--type digital")
        return 1

    llm = None
    if args.llm:
        from core.llm_client import LLMClient
        llm = LLMClient()

    rows = None
    if not args.no_calendar:
        from etsy.analytics.calendar import build as build_calendar
        from pinterest.endpoints.api import PinterestTrendsAPI
        with PinterestTrendsAPI() as pin:
            rows = build_calendar(pin.moments_calendar(country="US"))

    from etsy.api.private.api import SessionDown
    try:
        results = hunt(EtsyPrivateAPI(), EtsyPublicAPI(), settings,
                       limit=args.limit, calendar_rows=rows, llm=llm, seed=args.seed)
    except SessionDown as exc:
        # The session died mid-run (e.g. the browser was closed after preflight
        # passed). Report the real cause, not a half-finished hunt that looks like
        # "nothing is winnable".
        print(f"\n⛔ {exc}")
        return 1
    print(render(results))

    basis = settings.basis()
    if basis["unconfirmed"]:
        print(f"\n⚠️  {len(basis['unconfirmed'])} fee/rate values are still defaults — "
              f"every verdict above is provisional.")
        print("    python -m core.settings_store show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

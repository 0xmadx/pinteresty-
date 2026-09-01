"""The clock. Without it every signal here is a single reading, and a single reading
is a level, not a trend.

The system's whole thesis is time: a daily shop delta is the only *measured* sales
number it has, review velocity needs two readings a day apart, and LEARN needs launches
that have had time to succeed or fail. None of that accumulates on its own.

Design decisions that matter more than the code:

**Due-ness is measured from the last SUCCESSFUL run, and persisted.** Missing a day
must not silently skip that day's reading — it runs late instead. A scheduler that
fires "every 24h from now" quietly loses every window it was asleep for, and the gap is
invisible afterwards because the rows simply are not there.

**Each job declares which sessions it needs, and preflight refuses up front.** A run
that discovers halfway through that there is no seller session leaves a half-populated
sweep and a run log that reads like success.

**One job failing does not abort the others.** They are independent readings, and
losing the Pinterest bridge is no reason to skip the shop delta.

**No daemon.** `--once` runs whatever is due and exits, which is what Windows Task
Scheduler or a cron line should invoke. A long-lived loop is available for a session at
the desk, but nothing depends on it staying up.

    .venv/Scripts/python.exe -m core.scheduler --list
    .venv/Scripts/python.exe -m core.scheduler --once
    .venv/Scripts/python.exe -m core.scheduler --force shop_sweep
"""
import json
import pathlib
import traceback
from datetime import datetime, timedelta, timezone

STATE_PATH = pathlib.Path("config/scheduler_state.json")

# How many top-ranked candidates PER SEED get the intent check (D-43). Each costs one
# results-data call on the private tier, which authenticates as the operator's own
# seller account (D-29) — so this is a spend decision, not a tuning knob. 25 covers
# everything a reader looks at on the Discover screen; the tail is walls anyway.
INTENT_CHECK_TOP_N = 25

# Pinterest /metrics/ accepts roughly 50 terms per call. The surviving pool is far
# smaller than that in practice, so this is a ceiling rather than a batching loop.
PINTEREST_METRICS_BATCH = 50


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


class Job:
    """One recurring reading.

    `platforms` is what preflight must satisfy before the job runs — declared rather
    than discovered, so the refusal happens before any partial work.
    """

    def __init__(self, name, every_hours, run, platforms=(), description=""):
        self.name = name
        self.every_hours = every_hours
        self.run = run
        self.platforms = tuple(platforms)
        self.description = description


class Scheduler:
    def __init__(self, jobs, state_path=STATE_PATH):
        self.jobs = {j.name: j for j in jobs}
        self.state_path = pathlib.Path(state_path)
        self.state = self._load()

    def _load(self):
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # A corrupt state file must not stop the clock. Losing the schedule means
            # every job runs once now, which is safe; refusing to run means the
            # time-series silently stops, which is not.
            print("⚠️  scheduler state unreadable — treating every job as due")
            return {}

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def last_success(self, name):
        return _parse((self.state.get(name) or {}).get("last_success"))

    def due(self, now=None):
        """Jobs whose interval has elapsed since their last SUCCESS.

        A job that has never succeeded is always due — including one that has failed
        repeatedly, because a failing job is not a completed reading.
        """
        now = now or _now()
        out = []
        for name, job in self.jobs.items():
            last = self.last_success(name)
            if last is None or now - last >= timedelta(hours=job.every_hours):
                out.append(job)
        return out

    def run_job(self, job, now=None):
        """Run one job, recording the outcome either way.

        Preflight first: a missing session is a refusal, not a failure, and must not
        look like the job ran and found nothing.
        """
        from core.preflight import PreflightFailed, require

        now = now or _now()
        entry = self.state.setdefault(job.name, {})
        entry["last_attempt"] = now.isoformat()

        if job.platforms:
            try:
                require(*job.platforms)
            except PreflightFailed as exc:
                entry["last_status"] = "refused"
                entry["last_error"] = str(exc).splitlines()[0]
                self._save()
                return {"job": job.name, "status": "refused", "detail": str(exc)}

        try:
            result = job.run()
        except Exception as exc:                       # one job must not stop the rest
            entry["last_status"] = "failed"
            entry["last_error"] = f"{type(exc).__name__}: {exc}"
            entry["last_traceback"] = traceback.format_exc()[-1500:]
            self._save()
            return {"job": job.name, "status": "failed", "detail": str(exc)}

        entry["last_status"] = "ok"
        entry["last_success"] = now.isoformat()
        entry.pop("last_error", None)
        entry.pop("last_traceback", None)
        entry["last_result"] = _summarise(result)
        self._save()
        return {"job": job.name, "status": "ok", "result": result}

    def run_due(self, now=None):
        return [self.run_job(job, now) for job in self.due(now)]


def _summarise(result, limit=400):
    """Keep the state file readable — a full sweep result is pages of listing ids."""
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):
        text = str(result)
    return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------------
# The jobs themselves. Each is a thin wrapper so the scheduler stays testable without
# touching the network.

def job_shop_sweep():
    """Daily: shop totals + listing inventory + capped review counts, per tracked shop.

    Daily because the shop delta is a *difference between two counters*, and the window
    is only known if the readings are regular. `record_shop_observation` carries
    window_days precisely so an irregular gap cannot masquerade as a daily rate.
    """
    from core.database import MarketDatabase
    from core.settings_store import load
    from core.shop_scraper import ShopScraper
    from etsy.analytics import competitor_tracker as ct
    from etsy.api.public.api import EtsyPublicAPI

    settings = load()
    shops = settings.shop_names()
    if not shops:
        return {"skipped": "no tracked shops — add with: settings_store shop add NAME"}

    db, scraper = MarketDatabase(), ShopScraper(EtsyPublicAPI())
    terms = settings.terms()
    out = []
    for shop in shops:
        metrics = scraper.get_shop_metrics(shop)
        if metrics:
            db.record_shop_observation(shop, metrics["total_sales"],
                                       metrics["total_reviews"])
        out.append(ct.sweep_shop(db, scraper, shop, watched_terms=terms,
                                 shop_total_reviews=(metrics or {}).get("total_reviews")))
    return {"shops": len(out), "detail": out}


def job_keyword_sweep():
    """Daily: volume, supply, CVR and price band for every watched term.

    Daily because these are the inputs every verdict rests on, and a verdict that
    flips is only explainable if the inputs were being recorded on both sides of
    the flip. `keyword_observations` held ONE row before this job existed, which
    meant no term in the system had a history at all.

    Costs one private-API call per term. There is no quota on this endpoint
    (D-14: three consecutive distinct calls left remaining_quota at 15/15), so the
    cost is time, not allowance.

    A term that fails is recorded as a failure and the sweep continues — losing
    one term is no reason to lose the day's reading for the other five.
    """
    from core.database import MarketDatabase
    from core.settings_store import load
    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data

    terms = load().terms()
    if not terms:
        return {"skipped": "no watched terms — add with: settings_store term add TERM"}

    db, api = MarketDatabase(), EtsyPrivateAPI()
    recorded, failed, retried = [], [], []

    # SessionManager draws a RANDOM profile per request, so a pool holding one
    # healthy and one dead profile fails roughly half the time — per term, not per
    # run. One retry re-draws and usually lands on a different profile.
    #
    # This is a symptom fix and is labelled as one: the cause is that
    # cookie_vault.get_valid_account only checks freshness `if last_updated:`, so a
    # profile with no heartbeat is never aged out. Retrying around it keeps the
    # day's reading; it does not make the pool healthy. Never retry more than once
    # — a genuinely dead pool should fail fast and loudly, not spin.
    def fetch(term):
        try:
            return parse_results_data(api.get_results_data(term)) or {}
        except Exception:
            retried.append(term)
            return parse_results_data(api.get_results_data(term)) or {}

    for term in terms:
        try:
            # parse_results_data returns a FLAT dict — volume/supply/cvr/price_low —
            # not a nested stats block. Indexing a shape that does not exist yields
            # None for every field and writes a row of NULLs that reads as "we looked
            # and the market is unmeasured". That is the camelCase bug (D-24) in a new
            # costume, and it was committed here before this comment existed.
            data = fetch(term)
            volume = data.get("volume")
            if volume is None:
                # No volume means the call did not really succeed. Recording a row
                # of NULLs would put a reading in the history that says "we looked
                # and the market is unmeasured", which is not what happened.
                failed.append({"term": term, "why": "no searchVolume in response"})
                continue
            cvr = data.get("cvr")
            db.record_keyword(
                term, source="etsy_private", volume=volume,
                competition=data.get("supply"), cvr=cvr,
                cvr_source="measured" if cvr is not None else "default",
                price_low=data.get("price_low"),
                price_high=data.get("price_high"))
            recorded.append(term)
        except Exception as e:
            failed.append({"term": term, "why": f"{type(e).__name__}: {e}"})

    # --- Etsy's own seasonal curve, one BATCHED call for every term (D-45) ---------
    # chart-series-data takes the whole watch list at once, and its `series` block
    # carries a 12-month volume curve per term that every caller in this repo used to
    # discard. One request buys the second seasonal source JOIN 1 needs.
    seasonal = {}
    try:
        from etsy.api.private.api import parse_chart_series
        from etsy.analytics import seasonality as se
        curves = parse_chart_series(api.get_chart_series(terms, days=365))
        for term, curve in curves.items():
            prof = se.profile(curve)
            # Only measured profiles are stored; a refusal is not a reading.
            if db.record_seasonality(term, prof):
                seasonal[term] = f"{prof['verdict']} (peak {prof.get('peak_label')})"
    except Exception as e:
        # The demand readings above are already stored and are the job's main
        # product; seasonality is an addition, so a failure here degrades rather
        # than losing the sweep.
        seasonal = {"error": f"{type(e).__name__}: {e}"}

    return {"recorded": len(recorded), "terms": recorded, "failed": failed,
            "retried": retried, "seasonality": seasonal,
            "note": ("a retry means the vault served a dead profile; run "
                     "`python -m core.vault_status`") if retried else None}


def job_rank_check():
    """3x/week: where our launched listings actually rank.

    Not daily: rank is noisy hour to hour, and three readings a week is enough to see a
    trend without spending a request per listing per day on jitter.
    """
    from etsy.analytics.rank_tracker import track_ranks
    return track_ranks()


def job_discover():
    """Weekly: expand every watched term into its long-tail neighbourhood, ranked.

    This is the front door that finds terms the operator has NOT typed. Each
    watched seed is expanded through the LLM keyword endpoint, whose ~120 edges
    each carry their own volume and supply — so winnability is computable without a
    call per term, and one private request per seed produces a hundred ranked
    candidates.

    Weekly, not daily: the neighbourhood of a seed moves slowly, and the endpoint
    caches server-side, so a daily re-run would mostly re-read the same pool.

    Stores the whole ranked pool, walls included. "These 130 neighbours are all
    walls" is a real and useful answer — it is 130 dead-ends the operator does not
    have to type — so nothing is filtered out; the verdict column carries the
    winnable/contested/wall label and the reader decides.

    **Then the second gate (D-43).** The edges carry volume and supply but no CVR, so
    winnability alone cannot tell a rankable term from a merely-searched one. The top
    candidates per seed get one results-data call each, and each term's CVR is
    compared against the median of the terms measured beside it; one converting far
    below its peers is recorded `weak_intent` rather than leading the list. Bounded
    by `INTENT_CHECK_TOP_N` because that call spends the private tier (D-29).
    """
    from core.database import MarketDatabase
    from core.settings_store import load
    from etsy.analytics import discover
    from etsy.engines.calendar_engine import latest_moments
    from etsy.analytics import calendar as cal
    from etsy.api.private.api import EtsyPrivateAPI

    seeds = load().terms()
    if not seeds:
        return {"skipped": "no watched terms to expand"}

    db, api = MarketDatabase(), EtsyPrivateAPI()
    # The calendar rows, so a discovered term can be tagged with its moment.
    moments = cal.build(latest_moments(), terms=[], lead_weeks=6)

    from etsy.api.private.api import parse_results_data

    def fetch(term):
        raw = api.get_results_data(term)
        return parse_results_data(raw) if raw else None

    from datetime import datetime, timezone
    run_at = datetime.now(timezone.utc).isoformat()
    stored, weak, failed = 0, 0, []

    # --- rank every seed, and MEASURE the survivors, before judging any of them ----
    # The intent gate is relative, so the reference must be pooled across the whole
    # run. Judging per seed was tried and is wrong: a single seed rarely yields
    # MIN_POOL_FOR_INTENT rankable terms, so the gate refused on every one of them
    # and silently graded nothing (observed: 9 seeds, 1,359 candidates, 0 judged).
    per_seed, measured = [], {}
    for seed in seeds:
        try:
            cands = discover.expand_seed(api, seed)
        except Exception as e:
            failed.append({"seed": seed, "why": f"{type(e).__name__}: {e}"})
            continue
        ranked = discover.rank_expanded([c for c in cands if c.get("volume")])
        # Attach the seasonal moment where the term names one.
        ranked = discover.attach_moments(ranked, moments)
        # One private call per rankable candidate, bounded to the top of the ranking
        # — the only place the answer can still change a decision (D-29).
        measured.update(discover.measure_intent(ranked, fetch, INTENT_CHECK_TOP_N))
        per_seed.append((seed, ranked))

    # The reference: everything measured in this run PLUS every CVR the system has
    # measured before. The prior readings are free and already stored, and they make
    # the comparison steadier than one run's handful of survivors could.
    reference = discover.reference_median(measured.values(),
                                          extra_cvrs=db.measured_cvrs().values())

    judged = [(seed, discover.judge_intent(ranked, measured, reference))
              for seed, ranked in per_seed]

    # --- the third axis: is it RISING? (JOIN 2) -----------------------------------
    # Pinterest /metrics/ takes ~50 terms per call, and only the terms that survived
    # both Etsy gates are worth asking about — so this is ONE request for the whole
    # run, on a platform where no seller account is at risk.
    survivors = sorted({c["term"] for _, rows in judged for c in rows
                        if c.get("verdict") in ("winnable", "contested")})
    from etsy.analytics import momentum as mom
    momentum_index, momentum_note = {}, None
    if survivors:
        try:
            from pinterest.endpoints.api import PinterestTrendsAPI
            with PinterestTrendsAPI() as pin:
                momentum_index = mom.series_index(
                    pin.metrics(survivors[:PINTEREST_METRICS_BATCH], days=365))
        except Exception as e:
            # Pinterest is the one source with no seller account at stake, so a
            # failure here degrades the run rather than ending it: every Etsy
            # judgement above is already made and worth storing.
            momentum_note = f"momentum unavailable: {type(e).__name__}: {e}"

    rising = fading = 0
    for seed, rows in judged:
        for c in mom.attach(rows, momentum_index):
            w = c.get("winnability") or {}
            intent = c.get("intent") or {}
            m = c.get("momentum") or {}
            if intent.get("verdict") == "weak":
                weak += 1
            if m.get("verdict") == "rising":
                rising += 1
            elif m.get("verdict") == "fading":
                fading += 1
            db.record_discovered(
                c["term"], seed=seed, volume=c.get("volume"), supply=c.get("supply"),
                demand_per_listing=w.get("demand_per_listing"),
                # The MEASURED cvr where the intent gate fetched one; the edge never
                # carried it, so this column was NULL for every expanded term before.
                cvr=intent.get("cvr") if intent.get("cvr") is not None else w.get("cvr"),
                # The combined verdict, not the ratio's — a term that cannot convert
                # must not reach the operator labelled winnable. Momentum is stored
                # BESIDE it and never folded in: Pinterest tracks under half these
                # terms, so gating on it would reject terms for absence (N-02).
                verdict=c.get("verdict") or w.get("verdict"), moment=c.get("moment"),
                list_by=c.get("list_by"), timing=c.get("timing"),
                momentum=m.get("verdict") if m.get("basis") == "measured" else None,
                momentum_mom=m.get("mom"),
                collected_at=run_at)
            stored += 1

    winnable = sum(1 for r in db.latest_discovered(2000)
                   if r.get("verdict") in ("winnable", "contested"))
    return {"seeds": len(seeds), "candidates_stored": stored,
            "winnable_or_contested": winnable,
            # Terms the ratio gate would have promoted and the intent gate caught.
            "rejected_weak_intent": weak,
            # None means the gate REFUSED — too few measured CVRs to compare against.
            "intent_reference_cvr": reference,
            # Of the survivors Pinterest actually tracks. The rest are unmeasured,
            # which is not the same as flat.
            "momentum_checked": len(survivors),
            "momentum_known": len(momentum_index),
            "rising": rising, "fading": fading, "momentum_note": momentum_note,
            "failed": failed}


def job_competition_sweep():
    """Daily: page-one competition for every watched term, from the PUBLIC SERP.

    The private sweep gives demand and market-wide supply; this gives the shape of
    the competition a buyer actually meets — saturation of star-seller, free
    shipping, discount and rating, each with a confidence interval. One public
    request per term.

    Deliberately a SEPARATE job from keyword_sweep: public and private are
    different sessions, and a public 429 must not cost the private demand reading
    or vice versa. A term that fails is recorded and the sweep continues.

    The saturation here is a ~9-listing page-one sample and usually cannot separate
    thin from crowded — `card_saturation` says so per dimension. The ranked-id
    count is stored alongside so the Cockpit can show how much a deeper sample
    (listing_sample) could tighten it.
    """
    import urllib.parse
    from core.database import MarketDatabase
    from core.settings_store import load
    from etsy.analytics import card_saturation, sourcing
    from etsy.api.public.api import EtsyPublicAPI

    terms = load().terms()
    if not terms:
        return {"skipped": "no watched terms"}

    db, api = MarketDatabase(), EtsyPublicAPI()
    recorded, failed = [], []
    for term in terms:
        try:
            # Bypass the TTL cache: this is a scheduled reading and must be fresh,
            # and the parser fix for organic_listing_ids means cached blobs from
            # before it are stale in exactly the field we now need.
            url = "https://www.etsy.com/search?" + urllib.parse.urlencode(
                {"q": term, "explicit": "1"})
            html = api.session.request("GET", url, headers=api.headers,
                                       platform="etsy").text
            serp = api.parse_search_html(html, term)
            if not serp:
                failed.append({"term": term, "why": "SERP did not parse"})
                continue
            prof = card_saturation.profile(serp.get("cards"))
            organic = [c for c in (serp.get("cards") or []) if not c.get("is_ad")]
            # The lead-time (délai) distribution, from the delivery_days brackets —
            # trusted (D-32), 4 extra requests. countries=() skips the origin
            # sample, which is one request per listing and too heavy for a daily
            # sweep; origin stays on-demand via the sourcing MCP tool.
            dprofile = sourcing.fetch_profile(api, term, countries=())
            bands = sourcing.delivery_distribution(dprofile)
            db.record_keyword_competition(
                term,
                total_results=serp.get("total_results"),
                organic_sample=len(organic),
                ranked_ids_count=len(serp.get("organic_listing_ids") or []),
                saturation={f"{d}|{v}": m for (d, v), m in prof.items()},
                delivery_bands=[{"band": b, "share": sh} for b, sh in bands],
                median_delivery=sourcing.median_band(dprofile))
            recorded.append(term)
        except Exception as e:
            failed.append({"term": term, "why": f"{type(e).__name__}: {e}"})
    return {"recorded": len(recorded), "terms": recorded, "failed": failed}


def job_calendar():
    """Daily: recompute the calendar and record any verdict that moved.

    Cheap — it reads the database and makes no requests. Daily because `weeks_left`
    changes every day even when nothing else does, and a moment crossing from
    "list by" into "list now" is exactly the thing the operator must not miss.

    Recording it also gives verdict_log something to diff, so "christmas flipped to
    list-now on the 16th" becomes answerable later.
    """
    from etsy.analytics import verdict_log
    from etsy.engines import calendar_engine

    rows = calendar_engine.build()
    for row in rows:
        best = (row["evidence"] or [{}])[0]
        verdict_log.record(
            subject=f"moment:{row['moment']}",
            verdict=row["state"],
            inputs={"list_by": row["list_by"], "peak": row.get("peak"),
                    "weeks_left": row.get("weeks_left"),
                    "terms": len(row["evidence"]),
                    "actionable": row["actionable"],
                    "lead_term": best.get("term"),
                    "demand_per_listing": best.get("demand_per_listing")},
            basis="derived from measured takeoff dates and keyword observations",
            note=row["reason"])
    # The HTML/ics render used to happen here. Deleted with the UI (D-52) — the
    # judging above is the real work and it still runs daily, which is what makes
    # "christmas flipped to list-now on the 16th" answerable via verdict_history.
    urgent = [r["moment"] for r in rows if r["state"] == "list_now"]
    return {"moments": len(rows), "list_now": urgent,
            "actionable": [r["moment"] for r in rows if r["actionable"]]}


def job_pinterest_bridge():
    """Weekly: Pinterest momentum joined to the Etsy terms we care about.

    Weekly because Pinterest's own trend data is published weekly — sampling faster
    re-reads the same numbers and invents movement that is not there.
    """
    from pinterest.pipelines.trends_bridge import run
    return run()


def default_jobs():
    return [
        Job("shop_sweep", 24, job_shop_sweep, platforms=("etsy",),
            description="competitor shop totals, inventory and review counts"),
        Job("keyword_sweep", 24, job_keyword_sweep, platforms=("etsy_private",),
            description="volume, supply, CVR and price band for every watched term"),
        Job("competition_sweep", 24, job_competition_sweep, platforms=("etsy",),
            description="page-one saturation (star seller, free shipping, rating) per term"),
        Job("calendar", 24, job_calendar, platforms=(),
            description="recompute list-by dates and record verdict changes"),
        Job("rank_check", 56, job_rank_check, platforms=("etsy",),
            description="rank of our launched listings (~3x/week)"),
        Job("discover", 168, job_discover, platforms=("etsy_private",),
            description="expand watched terms into ranked long-tail candidates (weekly)"),
        Job("pinterest_bridge", 168, job_pinterest_bridge, platforms=("pinterest",),
            description="Pinterest momentum joined to watched terms (weekly)"),
    ]


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(prog="scheduler")
    parser.add_argument("--list", action="store_true", help="show jobs and when due")
    parser.add_argument("--once", action="store_true", help="run everything due, then exit")
    parser.add_argument("--force", metavar="JOB", help="run one job regardless of due-ness")
    parser.add_argument("--state", default=str(STATE_PATH))
    args = parser.parse_args(argv)

    sched = Scheduler(default_jobs(), args.state)

    if args.force:
        if args.force not in sched.jobs:
            print(f"Unknown job {args.force!r}. Known: {', '.join(sched.jobs)}")
            return 1
        outcome = sched.run_job(sched.jobs[args.force])
        print(f"{outcome['status']}: {outcome.get('detail') or outcome.get('result')}")
        return 0 if outcome["status"] == "ok" else 1

    if args.once:
        due = sched.due()
        if not due:
            print("Nothing due.")
            return 0
        print(f"{len(due)} job(s) due: {', '.join(j.name for j in due)}\n")
        failures = 0
        for outcome in sched.run_due():
            mark = {"ok": "✅", "failed": "❌", "refused": "⛔"}[outcome["status"]]
            print(f"{mark} {outcome['job']}: {outcome['status']}")
            if outcome["status"] != "ok":
                failures += 1
                for line in str(outcome.get("detail", "")).splitlines()[:4]:
                    print(f"      {line}")
        return 1 if failures else 0

    # default: --list
    now = _now()
    due = {j.name for j in sched.due(now)}
    print(f"{'job':<18} {'every':<9} {'last success':<22} {'status':<9} due")
    for name, job in sched.jobs.items():
        entry = sched.state.get(name) or {}
        last = entry.get("last_success", "never")
        if last != "never":
            last = last[:19]
        print(f"{name:<18} {job.every_hours:>4}h    {last:<22} "
              f"{entry.get('last_status', '-'):<9} {'YES' if name in due else ''}")
        if entry.get("last_error"):
            print(f"    last error: {entry['last_error'][:90]}")

    from core.settings_store import load
    settings = load()
    print(f"\ntracked shops: {', '.join(settings.shop_names()) or '(none)'}")
    print(f"watched terms: {len(settings.terms())}")
    warning = settings.survivorship_warning()
    if warning:
        print(f"\n⚠️  {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

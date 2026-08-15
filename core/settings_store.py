"""Operator settings — the numbers every profit verdict depends on (D-23, D-26).

Two tiers:

    GLOBAL              fee schedule, hourly rate, weekly hours, margin floors
    PRODUCT PROFILES    named: "Ceramic mug" -> cogs 8.50, ship 4.20, 3 min labour

`profit.verdict()` already accepts exactly the per-product shape, so this is storage
plus a picker — with one addition that is the point of the module.

**Every value is tagged confirmed or default.** A verdict computed from placeholder
fees is arithmetically identical to one computed from the operator's real numbers, and
today nothing distinguishes them. That is this system's defining failure — a plausible
wrong number — sitting directly under the go/no-go. So settings track which fields a
human actually confirmed, and `basis()` reports the weakest link, exactly as the
freshness floor reports the oldest input (B-10).

⚠️ **No LLM ever fills these in** (D-27). It may classify a product type or read a
price off a supplier page the operator pastes. An invented COGS flows straight into a
go/no-go.

    .venv/Scripts/python.exe -m core.settings_store show
    .venv/Scripts/python.exe -m core.settings_store set operator.hourly_rate 30
    .venv/Scripts/python.exe -m core.settings_store profile add "Ceramic mug" \
        --type physical --cogs 8.50 --shipping 4.20 --labour 3
"""
import json
import pathlib
from datetime import datetime, timezone

from etsy.analytics.profit import (FeeSchedule, MarginFloors, Operator, PRODUCT_TYPES,
                                   ProfitConfig)

DEFAULT_PATH = pathlib.Path("config/settings.json")

# Fields whose value changes a verdict. Anything here that is still a default makes the
# verdict provisional — these are the ones worth nagging about.
VERDICT_CRITICAL = (
    "fees.transaction_rate", "fees.processing_rate", "fees.processing_flat",
    "fees.listing_fee", "operator.hourly_rate", "operator.labor_hours_per_week",
)


def _defaults():
    """Seeded from profit.py so there is exactly one source of truth for the numbers."""
    fees, operator, floors = FeeSchedule(), Operator(), MarginFloors()
    return {
        "version": 1,
        "global": {
            "fees": {k: getattr(fees, k) for k in
                     ("verified", "listing_fee", "transaction_rate", "processing_rate",
                      "processing_flat", "offsite_rate_under_10k", "offsite_rate_over_10k")},
            "operator": {"hourly_rate": operator.hourly_rate,
                         "labor_hours_per_week": operator.labor_hours_per_week},
            "floors": {t: getattr(floors, t) for t in PRODUCT_TYPES},
        },
        # Dotted paths the operator has explicitly confirmed. Absent = still a guess.
        "confirmed": [],
        "product_profiles": {},
        # Competitor shops to sweep (D-25). `tier` is the operator's own note, and it
        # exists to make survivorship visible: a list of nothing but stars teaches what
        # winners do, not what works (B-01). Nothing enforces a mix — it cannot be
        # measured from the outside — but an all-star list should be obvious at a
        # glance rather than buried in a config.
        "tracked_shops": [],
        # Niches being considered. Competitor listings are matched against these so a
        # rival launching into one is visible.
        "watched_terms": [],
    }


class Settings:
    def __init__(self, data, path=DEFAULT_PATH):
        self.data = data
        self.path = pathlib.Path(path)

    # -- persistence ---------------------------------------------------------------
    @classmethod
    def load(cls, path=DEFAULT_PATH):
        path = pathlib.Path(path)
        if not path.exists():
            return cls(_defaults(), path)
        data = json.loads(path.read_text(encoding="utf-8"))
        # Merge forward: a settings file written before a field existed must not make
        # that field vanish, or the loader silently reverts to a hardcoded default with
        # no record that it did.
        merged = _defaults()
        for section, values in (data.get("global") or {}).items():
            merged["global"].setdefault(section, {}).update(values)
        merged["confirmed"] = data.get("confirmed", [])
        merged["product_profiles"] = data.get("product_profiles", {})
        merged["tracked_shops"] = data.get("tracked_shops", [])
        merged["watched_terms"] = data.get("watched_terms", [])
        return cls(merged, path)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        return self.path

    # -- reading and writing single values ------------------------------------------
    def get(self, dotted):
        section, _, key = dotted.partition(".")
        return self.data["global"][section][key]

    def set(self, dotted, value):
        """Set a global value and mark it confirmed — a human chose it deliberately."""
        section, _, key = dotted.partition(".")
        if section not in self.data["global"] or key not in self.data["global"][section]:
            raise KeyError(f"Unknown setting '{dotted}'. Try: python -m core.settings_store show")
        current = self.data["global"][section][key]
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            value = float(value)
        self.data["global"][section][key] = value
        if dotted not in self.data["confirmed"]:
            self.data["confirmed"].append(dotted)
        self.data.setdefault("updated", {})[dotted] = datetime.now(timezone.utc).isoformat()
        return value

    def is_confirmed(self, dotted):
        return dotted in self.data["confirmed"]

    # -- provenance -----------------------------------------------------------------
    def basis(self):
        """What a verdict built on these settings is actually worth.

        `unconfirmed` is the honest caveat to print next to any go/no-go: these are
        the numbers nobody has checked.
        """
        unconfirmed = [f for f in VERDICT_CRITICAL if not self.is_confirmed(f)]
        return {
            "basis": "operator" if not unconfirmed else "default",
            "unconfirmed": unconfirmed,
            "fee_schedule_verified": self.get("fees.verified"),
        }

    # -- the ProfitConfig profit.py wants -------------------------------------------
    def profit_config(self):
        """The config profit.py wants, carrying its own provenance.

        Every verdict built from this reports `provisional: True` until the
        verdict-critical fields are confirmed, so a go/no-go can never quietly rest on
        placeholder fees.
        """
        g = self.data["global"]
        b = self.basis()
        return ProfitConfig(
            fees=FeeSchedule(**g["fees"]),
            operator=Operator(**g["operator"]),
            floors=MarginFloors(**g["floors"]),
            settings_basis=b["basis"],
            unconfirmed_settings=tuple(b["unconfirmed"]),
        )

    def verdict_kwargs(self, profile_name):
        """Everything `profit.verdict()` needs for one named product, config included.

            v = profit.verdict(price=24.0, demand_units_per_week=12,
                               **settings.verdict_kwargs("Ceramic mug"))
        """
        return {**self.profile(profile_name), "config": self.profit_config()}

    # -- product profiles -----------------------------------------------------------
    def add_profile(self, name, product_type, cogs=0.0, shipping_cost=0.0,
                    shipping_charged=0.0, labor_minutes=0.0, notes=None):
        if product_type not in PRODUCT_TYPES:
            raise ValueError(f"product_type must be one of {PRODUCT_TYPES}, got {product_type!r}")
        for label, amount in (("cogs", cogs), ("shipping_cost", shipping_cost),
                              ("shipping_charged", shipping_charged),
                              ("labor_minutes", labor_minutes)):
            if amount < 0:
                raise ValueError(f"{label} cannot be negative")
        if product_type == "personalized" and not labor_minutes:
            # The labour minutes ARE the capacity ceiling for personalized goods, and
            # the ceiling is usually what binds. Zero here silently promises unlimited
            # weekly volume, which is the most expensive possible wrong number.
            raise ValueError(
                "a personalized profile needs labor_minutes — it sets the weekly "
                "capacity ceiling, and 0 means 'unlimited', which is never true by hand")
        self.data["product_profiles"][name] = {
            "product_type": product_type, "cogs": float(cogs),
            "shipping_cost": float(shipping_cost),
            "shipping_charged": float(shipping_charged),
            "labor_minutes": float(labor_minutes), "notes": notes,
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        return self.data["product_profiles"][name]

    def profile(self, name):
        """Keyword arguments for `profit.verdict()`. Raises if the profile is unknown —
        a missing profile must never silently become a zero-cost one."""
        try:
            p = dict(self.data["product_profiles"][name])
        except KeyError:
            known = ", ".join(sorted(self.data["product_profiles"])) or "(none defined)"
            raise KeyError(f"No product profile named {name!r}. Known: {known}") from None
        p.pop("notes", None)
        p.pop("updated", None)
        return p

    def profiles(self):
        return dict(self.data["product_profiles"])

    # -- what the scheduler sweeps ----------------------------------------------------
    def add_shop(self, name, tier=None, notes=None):
        """Track a competitor shop. `tier` is a free-text note, e.g. 'star', 'mid'."""
        shops = [s for s in self.data["tracked_shops"] if s["name"] != name]
        shops.append({"name": name, "tier": tier, "notes": notes,
                      "added": datetime.now(timezone.utc).isoformat()})
        self.data["tracked_shops"] = shops
        return shops

    def shops(self):
        return list(self.data["tracked_shops"])

    def shop_names(self):
        return [s["name"] for s in self.data["tracked_shops"]]

    def add_term(self, term):
        if term not in self.data["watched_terms"]:
            self.data["watched_terms"].append(term)
        return self.data["watched_terms"]

    def terms(self):
        return list(self.data["watched_terms"])

    def survivorship_warning(self):
        """Is the tracked set all winners? Returns a warning string, or None.

        Not a blocker — the operator may have good reason — but an all-star roster
        silently answers "what do successful shops do" while appearing to answer "what
        works", which is B-01 rebuilt inside the one dataset meant to escape it.
        """
        shops = self.shops()
        if len(shops) < 2:
            return None
        tiers = [(s.get("tier") or "").lower() for s in shops]
        if any(t in ("mid", "mid-tier", "small", "new") for t in tiers):
            return None
        return (f"All {len(shops)} tracked shops are stars or untiered. Tracking only "
                f"winners teaches what winners do, not what works (B-01). Add a shop "
                f"in the low hundreds of sales so failures are visible too.")


def load(path=DEFAULT_PATH):
    return Settings.load(path)


# ---------------------------------------------------------------------------------
def _cmd_show(settings):
    b = settings.basis()
    print(f"Settings: {settings.path}"
          f"{'' if settings.path.exists() else '  (not created yet — showing defaults)'}\n")
    for section, values in settings.data["global"].items():
        print(f"[{section}]")
        for key, value in values.items():
            dotted = f"{section}.{key}"
            mark = "✓" if settings.is_confirmed(dotted) else " "
            note = "" if settings.is_confirmed(dotted) else "  ← default, unverified"
            print(f"  {mark} {dotted:<34} {value}{note}")
        print()

    profiles = settings.profiles()
    print(f"[product profiles]  {len(profiles)} defined")
    for name, p in sorted(profiles.items()):
        print(f"    {name:<24} {p['product_type']:<13} cogs {p['cogs']:<7} "
              f"ship {p['shipping_cost']:<7} labour {p['labor_minutes']} min")
    if not profiles:
        print("    (none — every candidate will be priced as if it cost nothing to make)")

    print(f"\nbasis: {b['basis']}")
    if b["unconfirmed"]:
        print(f"⚠️  {len(b['unconfirmed'])} verdict-critical value(s) are still defaults:")
        for f in b["unconfirmed"]:
            print(f"      {f}")
        print("    Any go/no-go built on these is provisional. Confirm with:")
        print("      python -m core.settings_store set <field> <value>")
        print("    Confirming a default at its current value is fine — it records that")
        print("    a human checked it, which is the part that is missing.")
    return 0


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(prog="settings_store")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("show")
    sub.add_parser("init")
    s = sub.add_parser("set")
    s.add_argument("field")
    s.add_argument("value")
    p = sub.add_parser("profile")
    psub = p.add_subparsers(dest="pcmd")
    pa = psub.add_parser("add")
    pa.add_argument("name")
    pa.add_argument("--type", required=True, choices=PRODUCT_TYPES)
    pa.add_argument("--cogs", type=float, default=0.0)
    pa.add_argument("--shipping", type=float, default=0.0)
    pa.add_argument("--shipping-charged", type=float, default=0.0)
    pa.add_argument("--labour", type=float, default=0.0)
    pa.add_argument("--notes")
    psub.add_parser("list")

    sh = sub.add_parser("shop")
    shsub = sh.add_subparsers(dest="shcmd")
    sha = shsub.add_parser("add")
    sha.add_argument("name")
    sha.add_argument("--tier", help="star / mid / small — your own note (see B-01)")
    sha.add_argument("--notes")
    shsub.add_parser("list")

    tm = sub.add_parser("term")
    tmsub = tm.add_subparsers(dest="tmcmd")
    tma = tmsub.add_parser("add")
    tma.add_argument("term")
    tmsub.add_parser("list")

    args = parser.parse_args(argv)
    settings = Settings.load(args.path)

    if args.cmd == "init":
        print(f"Wrote {settings.save()}")
        return _cmd_show(settings)
    if args.cmd == "set":
        value = settings.set(args.field, args.value)
        settings.save()
        print(f"{args.field} = {value}  (confirmed)")
        remaining = settings.basis()["unconfirmed"]
        print(f"{len(remaining)} verdict-critical value(s) still unconfirmed."
              if remaining else "All verdict-critical values are now confirmed.")
        return 0
    if args.cmd == "shop":
        if args.shcmd == "add":
            settings.add_shop(args.name, args.tier, args.notes)
            settings.save()
            print(f"Tracking {args.name!r}"
                  f"{f' ({args.tier})' if args.tier else ''}.")
            warning = settings.survivorship_warning()
            if warning:
                print(f"\n⚠️  {warning}")
            return 0
        for shop in settings.shops():
            print(f"{shop['name']:<24} tier={shop.get('tier') or '-'}")
        return 0
    if args.cmd == "term":
        if args.tmcmd == "add":
            settings.add_term(args.term)
            settings.save()
            print(f"Watching {args.term!r}. {len(settings.terms())} term(s) total.")
            return 0
        for term in settings.terms():
            print(term)
        return 0
    if args.cmd == "profile":
        if args.pcmd == "add":
            settings.add_profile(args.name, args.type, args.cogs, args.shipping,
                                 args.shipping_charged, args.labour, args.notes)
            settings.save()
            print(f"Profile {args.name!r} saved.")
            return 0
        for name, prof in sorted(settings.profiles().items()):
            print(f"{name:<24} {prof}")
        return 0
    return _cmd_show(settings)


if __name__ == "__main__":
    raise SystemExit(main())

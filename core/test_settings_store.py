"""Settings, and the provenance that keeps a verdict honest.

The failure being prevented: `verdict()` returns the same shape whether its fees came
from the operator or from this repo's placeholders. Arithmetically identical, worth
completely different amounts of trust. Everything below exists to make that difference
visible at the point of use.

Offline, no config file touched — each test builds its own in a temp path.

    .venv/Scripts/python.exe -m core.test_settings_store
"""
import json
import pathlib
import tempfile

from core.settings_store import Settings, VERDICT_CRITICAL, _defaults
from etsy.analytics import profit

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def fresh(path=None):
    return Settings(_defaults(), path or (pathlib.Path(tempfile.mkdtemp()) / "s.json"))


def raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return False
    except exc:
        return True


# --- defaults are usable but never trusted ---------------------------------------
s = fresh()
b = s.basis()
check("defaults report basis 'default'", b["basis"] == "default", b)
check("every verdict-critical field starts unconfirmed",
      set(b["unconfirmed"]) == set(VERDICT_CRITICAL), b["unconfirmed"])
check("defaults still produce a working config",
      isinstance(s.profit_config(), profit.ProfitConfig))

# --- confirming is an act, not a value change ------------------------------------
# Confirming a default AT ITS CURRENT VALUE must still count: the missing thing was a
# human checking it, not a different number.
s = fresh()
before = s.get("fees.transaction_rate")
s.set("fees.transaction_rate", before)
check("re-confirming an unchanged default marks it confirmed",
      s.is_confirmed("fees.transaction_rate"))
check("and does not alter the value", s.get("fees.transaction_rate") == before)

s.set("operator.hourly_rate", 30)
check("set coerces numeric strings", s.get("operator.hourly_rate") == 30.0,
      s.get("operator.hourly_rate"))
check("unknown fields are rejected, not silently created",
      raises(KeyError, s.set, "operator.nonexistent", 1))

# --- provenance reaches the verdict ----------------------------------------------
s = fresh()
s.add_profile("Digital printable", "digital")
v = profit.verdict(price=6.0, demand_units_per_week=20,
                   **s.verdict_kwargs("Digital printable"))
check("a verdict on defaults is flagged provisional", v["provisional"] is True, v["provisional"])
check("and names what was not confirmed", len(v["unconfirmed_settings"]) == len(VERDICT_CRITICAL),
      v["unconfirmed_settings"])

before_confirming = v["profit_per_unit"]
for field in VERDICT_CRITICAL:
    s.set(field, s.get(field))          # same values, now checked by a human
v = profit.verdict(price=6.0, demand_units_per_week=20,
                   **s.verdict_kwargs("Digital printable"))
check("once confirmed, the verdict is no longer provisional", v["provisional"] is False,
      v["provisional"])
check("basis reads 'operator'", v["settings_basis"] == "operator", v["settings_basis"])
# Confirmation must move the trust label and nothing else. If the arithmetic shifted,
# `confirm` would be silently editing the model rather than vouching for it.
check("confirming changes trust, not the number",
      v["profit_per_unit"] == before_confirming,
      f"{before_confirming} -> {v['profit_per_unit']}")

# --- product profiles ------------------------------------------------------------
s = fresh()
s.add_profile("Ceramic mug", "physical", cogs=8.5, shipping_cost=4.2, labor_minutes=3)
p = s.profile("Ceramic mug")
check("profile round-trips", p["cogs"] == 8.5 and p["labor_minutes"] == 3.0, p)
check("profile is verdict-ready (no stray keys)",
      set(p) == {"product_type", "cogs", "shipping_cost", "shipping_charged",
                 "labor_minutes"}, set(p))

check("an unknown profile raises rather than costing nothing",
      raises(KeyError, s.profile, "Nonexistent"))
# Silently defaulting to a zero-cost profile would turn every unmatched candidate into
# a guaranteed 'go' — the most expensive possible failure in this system.

check("an invalid product type is refused",
      raises(ValueError, s.add_profile, "x", "vapourware"))
check("negative costs are refused",
      raises(ValueError, s.add_profile, "x", "physical", -1))
check("a personalized profile without labour is refused",
      raises(ValueError, s.add_profile, "sign", "personalized", 12, 0, 0, 0))
# labor_minutes IS the weekly capacity ceiling for personalized goods; 0 silently
# promises unlimited output.

s.add_profile("Custom sign", "personalized", cogs=12, labor_minutes=45)
v = profit.verdict(price=48.0, demand_units_per_week=100, **s.verdict_kwargs("Custom sign"))
check("labour drives the capacity ceiling", v["weekly_capacity"] == 20, v["weekly_capacity"])
check("and the ceiling binds, not demand", v["capped_units_per_week"] == 20,
      v["capped_units_per_week"])
check("capacity-bound is reported", v["capacity_bound"] is True)
check("weekly profit uses the capped units, never raw demand",
      v["weekly_profit"] == round(v["profit_per_unit"] * 20, 4), v["weekly_profit"])

# --- persistence -----------------------------------------------------------------
path = pathlib.Path(tempfile.mkdtemp()) / "settings.json"
s = fresh(path)
s.set("operator.hourly_rate", 42)
s.add_profile("Mug", "physical", cogs=3)
s.save()
again = Settings.load(path)
check("values persist", again.get("operator.hourly_rate") == 42.0)
check("confirmations persist", again.is_confirmed("operator.hourly_rate"))
check("profiles persist", again.profile("Mug")["cogs"] == 3.0)

# A file written before a field existed must not make that field disappear — the
# loader would otherwise fall back to a hardcoded default with no record it had.
partial = pathlib.Path(tempfile.mkdtemp()) / "old.json"
partial.write_text(json.dumps({
    "version": 1,
    "global": {"operator": {"hourly_rate": 99.0}},
    "confirmed": ["operator.hourly_rate"],
    "product_profiles": {},
}), encoding="utf-8")
old = Settings.load(partial)
check("older files keep their confirmed values", old.get("operator.hourly_rate") == 99.0)
check("and gain missing fields from defaults",
      old.get("fees.transaction_rate") == 0.065, old.get("fees.transaction_rate"))
check("newly-added fields are NOT silently marked confirmed",
      not old.is_confirmed("fees.transaction_rate"))

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

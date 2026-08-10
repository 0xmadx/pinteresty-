"""One entry point for the eight standalone Pinterest products.

    .venv/Scripts/python.exe pinterest/products/cli.py                       # list them
    .venv/Scripts/python.exe pinterest/products/cli.py keywords "halloween nails"
    .venv/Scripts/python.exe pinterest/products/cli.py calendar US --ics
    .venv/Scripts/python.exe pinterest/products/cli.py targeting
    .venv/Scripts/python.exe pinterest/products/cli.py market "runner rugs"
    .venv/Scripts/python.exe pinterest/products/cli.py history --weeks 12
    .venv/Scripts/python.exe pinterest/products/cli.py audience "grill recipes" "prom hair"
    .venv/Scripts/python.exe pinterest/products/cli.py moodboard --html
    .venv/Scripts/python.exe pinterest/products/cli.py alerts --refresh

Each module is also runnable directly; this exists so the eight are discoverable as one
thing rather than eight files someone has to know about.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.products import (ad_targeting, alerts, audience, content_calendar, history,
                                keyword_research, market_intel, moodboard)

def _after(args, flag):
    """The value following `flag`, or None. Keeps the flag handling in one place."""
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


COMMANDS = {
    # depth is a flag, not a positional: an unquoted multi-word seed would otherwise be
    # parsed as (seed, depth) and blow up on int("nails").
    "keywords":  ("1  keyword research for any niche  [--depth N]",
                  lambda a: keyword_research.report(
                      " ".join(x for x in a if not x.startswith("-")
                               and x != _after(a, "--depth")) or "halloween nails",
                      depth=int(_after(a, "--depth") or 1))),
    "calendar":  ("2  seasonal content calendar (+ .ics)",
                  lambda a: content_calendar.report(
                      next((x for x in a if not x.startswith("-")), "US"),
                      ics="--ics" in a, with_terms="--terms" in a)),
    "targeting": ("3  Pinterest Ads interest x demographic brief",
                  lambda a: ad_targeting.report(a[0] if a and not a[0].startswith("-") else "US")),
    "market":    ("4  merchant landscape + 383-node taxonomy",
                  lambda a: market_intel.report(" ".join(a) or "runner rugs")),
    "history":   ("5  the weekly archive Pinterest does not offer  [--weeks N|--term T]",
                  lambda a: history.report(weeks=int(_after(a, "--weeks") or 8),
                                           term=_after(a, "--term"))),
    "audience":  ("6  who searches a term, by age and gender",
                  lambda a: audience.report(a or None)),
    "moodboard": ("7  trend moodboards with colour palettes (+ .html)",
                  lambda a: moodboard.report(
                      html="--html" in a,
                      interest=next((x for x in a if not x.startswith("-")), None))),
    "alerts":    ("8  week-over-week momentum feed",
                  lambda a: alerts.report(
                      preset=next((x for x in a if not x.startswith("-")), "growing"),
                      refresh="--refresh" in a)),
}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.split("\n\n")[0])
        print()
        for name, (blurb, _) in COMMANDS.items():
            print(f"  {name:11} {blurb}")
        return 0 if not argv else 1
    _, run = COMMANDS[argv[0]]
    run(argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

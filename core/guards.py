"""The single guard boundary (DECISION_LOG.md D-06).

Scrapers must tolerate markup they did not expect — one changed CSS class should not
abort a 50-keyword crawl. The repo's answer was `except Exception: pass`, which tolerates
the failure by *erasing* it: a run where every parse failed printed exactly what a run
where every parse succeeded printed, and the missing fields looked like fields the site
genuinely did not have.

That is this system's defining failure mode. `GOAL.md`: a plausible wrong number that
looks authoritative is worse than an error.

So: keep going, but keep the receipt.

    with soft_parse("listing.price", listing_id=lid):
        price = float(offers["lowPrice"])

The exception is swallowed exactly as before, and recorded. At the end of a run:

    report_failures()      # -> prints a grouped summary, returns the count

A parse that fails every time is then visible as a broken selector rather than as an
empty result set. Nothing here retries, logs to disk, or raises — it only refuses to
let a failure be silent.
"""
from collections import Counter
from contextlib import contextmanager

# Module-level so a caller that forgets to pass a collector still cannot lose the
# failure. Cleared per run by reset_failures().
_FAILURES = []


class ParseFailure:
    __slots__ = ("label", "error_type", "message", "context")

    def __init__(self, label, error_type, message, context):
        self.label = label
        self.error_type = error_type
        self.message = message
        self.context = context

    def __repr__(self):
        ctx = f" {self.context}" if self.context else ""
        return f"<ParseFailure {self.label}: {self.error_type}: {self.message}{ctx}>"


@contextmanager
def soft_parse(label, collector=None, **context):
    """Swallow a parse error the way `except: pass` did — but record it.

    `label` names the field being parsed ("listing.price", "search.breadcrumb"), not the
    module; failures are grouped by it, so it should be stable across calls.

    Deliberately catches broad `Exception`: these blocks wrap third-party HTML and JSON
    where the failure modes are genuinely open-ended. What was wrong before was not the
    breadth of the catch, it was the silence. KeyboardInterrupt and SystemExit derive
    from BaseException and still propagate.
    """
    try:
        yield
    except Exception as exc:
        failure = ParseFailure(label, type(exc).__name__, str(exc), context)
        (collector if collector is not None else _FAILURES).append(failure)


def failures(collector=None):
    return list(collector if collector is not None else _FAILURES)


def reset_failures(collector=None):
    """Call at the start of a run so counts describe that run only."""
    target = collector if collector is not None else _FAILURES
    target.clear()


def summarise_failures(collector=None):
    """label -> count, most frequent first."""
    return Counter(f.label for f in failures(collector)).most_common()


def report_failures(collector=None, prefix="  ", total_attempts=None):
    """Print a grouped summary. Returns the failure count so a caller can branch.

    Prints nothing when there is nothing wrong — the point is that a clean run and a
    broken run no longer look identical, not that every run grows a report.
    """
    found = failures(collector)
    if not found:
        return 0

    print(f"{prefix}[!] {len(found)} parse failure(s) were tolerated:")
    for label, count in summarise_failures(collector):
        sample = next(f for f in found if f.label == label)
        detail = f"{sample.error_type}: {sample.message}" if sample.message else sample.error_type
        print(f"{prefix}    {count:>4}x {label} — e.g. {detail}")
        if sample.context:
            print(f"{prefix}         context: {sample.context}")

    # A selector that fails on everything is broken, not unlucky. Worth saying out loud,
    # because the symptom (an empty field) is indistinguishable from a real absence.
    if total_attempts:
        for label, count in summarise_failures(collector):
            if count >= total_attempts:
                print(f"{prefix}    ⚠️  '{label}' failed on EVERY attempt — treat the "
                      f"field as unmeasured, not as absent. The selector has likely changed.")
    return len(found)

"""One-way mirror: the shared vault -> this project's private vault.

WHY THIS EXISTS
---------------
The Chrome extension, the Go cookie server and the Redis container all belong to
this repo. A second project (`Desktop\\pinterest-apify`) is a guest on that
infrastructure: it points at the same `redis://localhost:6379/0` and reads
`cookie:pinterest:*` written by the same extension.

Sharing one keyspace means each project's session management reaches into the
other's. Concretely, before this module existed:

  * `vault_status.plan_prune` iterated ("etsy", "etsy_private", "pinterest") and
    would happily delete profiles the other project depends on.
  * `cookie_vault` evicts a profile it judges signed-out or stale — for every
    platform, including theirs.
  * their eviction of a shared profile silently shrinks our pool.

None of that is a bug in either project. It is two owners of one mutable store.

THE SEPARATION, AND WHAT IT DELIBERATELY DOES NOT CHANGE
--------------------------------------------------------
The WRITE side stays exactly as it is. One browser, one extension, one Go server,
writing to db 0 — because that is the constraint the operator stated and because
changing it would require touching the extension and the Go server, which both
projects depend on.

What changes is that this project stops READING db 0 directly. It reads a private
database (db 1 by default), and this module copies into it. So:

    Chrome ─► extension ─► Go server ─► db 0  ◄── pinterest-apify reads this
                                          │
                                     (mirror, one-way)
                                          ▼
                                        db 1  ◄── everything in this repo reads this

Our evictions, prunes and leases now happen in db 1 and cannot reach their data.
Their evictions cannot shrink our pool. Nothing on their side changes at all.

ONE-WAY IS ENFORCED, NOT ASSUMED
--------------------------------
`sync()` opens the source with a client it only ever reads from, and every write
goes to the destination. A bug that writes to the source would defeat the entire
purpose, so the source client is kept in a separate variable named for what it is
and never passed to a write helper.

WHAT ABOUT OUR LOCAL EVICTIONS
------------------------------
If we evict a profile in db 1 and the mirror blindly re-copied it, the eviction
would last until the next sync — which is worse than no eviction, because the
failure would come and go. So a profile we marked invalid is only readmitted when
the source has a STRICTLY NEWER heartbeat than the copy we hold: i.e. the operator
actually re-logged in and the extension beamed fresh cookies. A re-login heals it;
a stale profile stays evicted.
"""
import json
import os
import time

import redis

from core.settings import ScraperConfig

# The shared vault the Go server writes to. Never written by this project.
SOURCE_URL = os.environ.get("VAULT_SOURCE_URL", "redis://localhost:6379/0")

# Platforms this project owns a COPY of. Pinterest is included because this repo
# uses Pinterest momentum itself (the weekly trends bridge) — mirroring it means we
# hold our own copy of those sessions rather than sharing the other project's.
MIRRORED = ("etsy", "etsy_private", "pinterest")

# Hash fields worth copying. Everything the Go server writes, plus the fields our
# own vault adds. `is_valid` is deliberately NOT copied — see readmit logic.
COPIED_FIELDS = ("cookies_json", "user_agent", "last_updated", "csrf_token",
                 "shop_id", "proxy")


def _beat(data):
    try:
        return float(data.get("last_updated") or 0)
    except (ValueError, TypeError):
        return 0.0


MAX_MIRROR_AGE = 120.0
_last_sync = 0.0


def sync_if_stale(max_age=MAX_MIRROR_AGE):
    """Refresh the mirror at most once per `max_age` seconds. Safe to call anywhere.

    **Why this exists at all.** Nothing refreshes db 1 on its own, and the lag is
    not harmless: measured 2026-08-25, db 0 held a profile last beaten 189s ago
    while our copy of the same profile read 320s — past the 300s eviction line. The
    pool then looks EMPTY while the Chrome extension is beaming perfectly good
    cookies, and an agent relays "0 usable sessions, profiles are stale" to the
    operator. The mirror is the thing that is stale, not the sessions.

    Rather than remembering to sync at each of ~26 runnable entry points (a list
    that was already wrong twice — the CLI tools, then the MCP server), the API
    clients call this in their constructors. One call site per client, and every
    current and future entry point inherits it.

    Throttled because a client may be built in a loop, and unconditional: a
    failure is swallowed. An unreachable mirror is not an empty pool — we may hold
    a perfectly good copy — so the caller's own vault check decides.
    """
    global _last_sync
    now = time.time()
    if now - _last_sync < max_age:
        return False
    _last_sync = now
    try:
        sync()
        return True
    except Exception:
        return False


def sync(source_url=None, dest_url=None, platforms=MIRRORED, verbose=False):
    """Copy sessions from the shared vault into this project's private one.

    Returns a summary. Never writes to the source, never deletes from the
    destination — a profile that disappears upstream is left in place here until
    our own vault judges it unusable, so the other project retiring a session
    cannot empty our pool mid-run.
    """
    source_url = source_url or SOURCE_URL
    dest_url = dest_url or ScraperConfig().REDIS_URL

    if source_url == dest_url:
        # Not an error worth raising — it is the un-separated configuration, and
        # saying so plainly is more useful than failing. But it must be visible:
        # in this state every guarantee in this module's docstring is void.
        return {"skipped": "source and destination are the same database — this "
                           "project is NOT separated from the shared vault. Set "
                           "REDIS_URL to a different db index (e.g. .../1).",
                "source": source_url, "dest": dest_url, "copied": 0}

    src = redis.Redis.from_url(source_url, decode_responses=True)   # READ ONLY
    dst = redis.Redis.from_url(dest_url, decode_responses=True)
    src.ping()
    dst.ping()

    copied, readmitted, held_back, skipped = 0, [], [], []

    for platform in platforms:
        upstream_pool = set(src.smembers(f"valid_profiles:{platform}") or [])

        for key in src.scan_iter(f"cookie:{platform}:*"):
            profile_id = key.split(":", 2)[2]
            data = src.hgetall(key)
            if not data:
                continue

            dest_key = f"cookie:{platform}:{profile_id}"
            mine = dst.hgetall(dest_key) or {}

            mapping = {f: data[f] for f in COPIED_FIELDS if data.get(f) is not None}
            if not mapping:
                skipped.append(f"{platform}/{profile_id}: nothing to copy")
                continue

            fresher = _beat(data) > _beat(mine)
            locally_evicted = mine.get("is_valid") == "0"

            if locally_evicted and not fresher:
                # We judged this one unusable and nothing new has arrived. Copying
                # it back would resurrect a known-bad session on every sync, so the
                # failure would come and go instead of staying fixed.
                held_back.append(f"{platform}/{profile_id}")
                continue

            dst.hset(dest_key, mapping=mapping)
            copied += 1

            if profile_id in upstream_pool:
                if locally_evicted and fresher:
                    # A genuine re-login upstream. Clear our verdict and let it back
                    # in — the operator fixed the thing we complained about.
                    dst.hset(dest_key, "is_valid", "1")
                    readmitted.append(f"{platform}/{profile_id}")
                if not locally_evicted:
                    dst.hset(dest_key, "is_valid", "1")
                dst.sadd(f"valid_profiles:{platform}", profile_id)

    summary = {"source": source_url, "dest": dest_url, "platforms": list(platforms),
               "copied": copied, "readmitted": readmitted,
               "held_back_locally_evicted": held_back, "skipped": skipped}
    if verbose:
        print(f"[mirror] {copied} profile(s) copied from {source_url} -> {dest_url}")
        for r in readmitted:
            print(f"[mirror] readmitted {r} — upstream heartbeat is newer than our "
                  f"eviction, so the operator re-logged in")
        for h in held_back:
            print(f"[mirror] held back {h} — evicted locally and nothing newer "
                  f"upstream")
    return summary


def is_separated(dest_url=None, source_url=None):
    """True when this project reads a different database from the shared vault."""
    return (dest_url or ScraperConfig().REDIS_URL) != (source_url or SOURCE_URL)


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="vault_mirror")
    parser.add_argument("--source", default=None)
    parser.add_argument("--dest", default=None)
    parser.add_argument("--platforms", default=",".join(MIRRORED))
    args = parser.parse_args()

    platforms = tuple(p.strip() for p in args.platforms.split(",") if p.strip())
    result = sync(args.source, args.dest, platforms, verbose=True)

    if result.get("skipped"):
        print(f"\n⚠️  {result['skipped']}")
        return 1

    print(f"\n  source (shared, read-only): {result['source']}")
    print(f"  dest   (this project only): {result['dest']}")
    print(f"  copied: {result['copied']}   readmitted: {len(result['readmitted'])}   "
          f"held back: {len(result['held_back_locally_evicted'])}")
    print("\n  The other project keeps using the source untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The mirror must be one-way, and must not undo our own evictions.

Two projects share one Chrome extension, one Go cookie server and one Redis. This
module's whole job is to give THIS project a private copy so its evictions, prunes
and leases cannot reach the other project's data — and so the other project's
cannot shrink our pool.

Every guarantee below is one that, if it silently broke, would look like the
separation was working right up until something odd happened in the other project.

    .venv/Scripts/python.exe -m core.test_vault_mirror
"""
import json

from core.vault_mirror import COPIED_FIELDS, sync

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}  {detail}")


class FakeRedis:
    """Enough of Redis for the mirror, and it RECORDS every write."""

    def __init__(self, hashes=None, sets=None, name="?"):
        self.hashes = {k: dict(v) for k, v in (hashes or {}).items()}
        self.sets = {k: set(v) for k, v in (sets or {}).items()}
        self.name = name
        self.writes = []

    def ping(self):
        return True

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def scan_iter(self, match):
        prefix = match.rstrip("*")
        return [k for k in list(self.hashes) if k.startswith(prefix)]

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, field=None, value=None, mapping=None):
        self.writes.append(("hset", key))
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update(mapping)
        elif field is not None:
            h[field] = value

    def sadd(self, key, member):
        self.writes.append(("sadd", key))
        self.sets.setdefault(key, set()).add(member)

    def srem(self, key, member):
        self.writes.append(("srem", key))
        self.sets.get(key, set()).discard(member)

    def delete(self, key):
        self.writes.append(("delete", key))
        self.hashes.pop(key, None)


def run(src, dst, platforms=("etsy",)):
    """Drive sync() against two fakes by patching the client factory."""
    import core.vault_mirror as vm
    real = vm.redis.Redis.from_url
    calls = {"n": 0}

    def factory(url, decode_responses=True):
        calls["n"] += 1
        return src if calls["n"] == 1 else dst

    vm.redis.Redis.from_url = factory
    try:
        return sync("redis://x/0", "redis://x/1", platforms)
    finally:
        vm.redis.Redis.from_url = real


COOKIES = json.dumps({"session-key-www": "x"})


def main():
    # --- the copy happens ----------------------------------------------------------
    print()
    src = FakeRedis(
        hashes={"cookie:etsy:p1": {"cookies_json": COOKIES, "last_updated": "1000",
                                   "user_agent": "UA"}},
        sets={"valid_profiles:etsy": {"p1"}}, name="src")
    dst = FakeRedis(name="dst")
    result = run(src, dst)
    check("a profile is copied", result["copied"] == 1, result)
    check("its cookies come with it",
          dst.hashes["cookie:etsy:p1"]["cookies_json"] == COOKIES)
    check("and it lands in our valid pool", "p1" in dst.sets["valid_profiles:etsy"])

    # --- ONE WAY. this is the whole point ---------------------------------------------
    check("the SOURCE is never written to — not one call", src.writes == [], src.writes)

    # --- our eviction survives a sync --------------------------------------------------
    # If the mirror re-copied a profile we judged unusable, the eviction would last
    # until the next sync and the failure would come and go rather than stay fixed.
    print()
    src = FakeRedis(
        hashes={"cookie:etsy:bad": {"cookies_json": COOKIES, "last_updated": "1000"}},
        sets={"valid_profiles:etsy": {"bad"}}, name="src")
    dst = FakeRedis(
        hashes={"cookie:etsy:bad": {"cookies_json": COOKIES, "last_updated": "1000",
                                    "is_valid": "0"}},
        sets={"valid_profiles:etsy": set()}, name="dst")
    result = run(src, dst)
    check("a locally evicted profile is NOT re-copied",
          result["held_back_locally_evicted"] == ["etsy/bad"], result)
    check("and is NOT put back in our pool",
          "bad" not in dst.sets.get("valid_profiles:etsy", set()))
    check("its eviction verdict stands", dst.hashes["cookie:etsy:bad"]["is_valid"] == "0")

    # --- but a genuine re-login heals it ------------------------------------------------
    print()
    src = FakeRedis(
        hashes={"cookie:etsy:bad": {"cookies_json": COOKIES, "last_updated": "9999"}},
        sets={"valid_profiles:etsy": {"bad"}}, name="src")
    dst = FakeRedis(
        hashes={"cookie:etsy:bad": {"cookies_json": COOKIES, "last_updated": "1000",
                                    "is_valid": "0"}},
        sets={"valid_profiles:etsy": set()}, name="dst")
    result = run(src, dst)
    check("a NEWER upstream heartbeat readmits it — the operator re-logged in",
          result["readmitted"] == ["etsy/bad"], result)
    check("and it is valid again", dst.hashes["cookie:etsy:bad"]["is_valid"] == "1")
    check("and back in our pool", "bad" in dst.sets["valid_profiles:etsy"])

    # --- their retirement cannot empty our pool -------------------------------------------
    # The other project evicting a shared profile removes it from THEIR pool. Ours
    # must not follow: mid-run, that would be a session disappearing underneath us
    # for reasons that have nothing to do with us.
    print()
    src = FakeRedis(
        hashes={"cookie:etsy:p1": {"cookies_json": COOKIES, "last_updated": "1000"}},
        sets={"valid_profiles:etsy": set()}, name="src")     # they dropped it
    dst = FakeRedis(
        hashes={"cookie:etsy:p1": {"cookies_json": COOKIES, "last_updated": "1000"}},
        sets={"valid_profiles:etsy": {"p1"}}, name="dst")    # we still hold it
    run(src, dst)
    check("a profile they retired stays in OUR pool",
          "p1" in dst.sets["valid_profiles:etsy"])
    check("the mirror never removes from our pool",
          not any(op == "srem" for op, _ in dst.writes), dst.writes)

    # --- an unseparated configuration is reported, not silently accepted -------------------
    print()
    result = sync("redis://x/0", "redis://x/0", ("etsy",))
    check("identical source and dest is refused as not-separated",
          "NOT separated" in (result.get("skipped") or ""), result)
    check("and nothing is copied in that state", result["copied"] == 0)

    # --- field coverage ---------------------------------------------------------------------
    print()
    check("seller fields are mirrored, or the private tier cannot authenticate",
          "csrf_token" in COPIED_FIELDS and "shop_id" in COPIED_FIELDS)
    check("the user_agent travels with the cookies it was born with",
          "user_agent" in COPIED_FIELDS)
    check("is_valid is NOT blindly copied — our verdict is ours",
          "is_valid" not in COPIED_FIELDS)

    # --- another project's identities never enter this pool -----------------------
    # `Desktop\pinterest-apify` writes AdsPower jars as `ads_<user_id>` into the same
    # db 0. Measured 2026-08-25: 7 of our 9 pinterest profiles were its, not ours.
    # Different browsers, different proxies, different IPs — a ban earned by their
    # traffic would land in our pool. Separate projects, separate sessions.
    print()
    from core.vault_mirror import is_foreign, purge_foreign  # noqa: E402

    check("an AdsPower jar is recognised as foreign", is_foreign("ads_k1fx40wf"))
    check("an extension jar is ours", not is_foreign("profile_p5ewxsodn"))
    check("the manually-seeded seller jar is ours", not is_foreign("private_seller_1"))
    check("a missing id does not crash the check", not is_foreign(None))

    src = FakeRedis(
        hashes={"cookie:pinterest:profile_mine": {"cookies_json": "{}", "last_updated": "100"},
                "cookie:pinterest:ads_k1fx40wf": {"cookies_json": "{}", "last_updated": "999"}},
        sets={"valid_profiles:pinterest": ["profile_mine", "ads_k1fx40wf"]}, name="src")
    dst = FakeRedis(name="dst")
    result = run(src, dst, platforms=("pinterest",))

    check("our own profile is mirrored",
          "cookie:pinterest:profile_mine" in dst.hashes, list(dst.hashes))
    check("the foreign profile is NOT mirrored, despite a fresher heartbeat",
          "cookie:pinterest:ads_k1fx40wf" not in dst.hashes, list(dst.hashes))
    check("and it never reaches our valid pool",
          "ads_k1fx40wf" not in dst.sets.get("valid_profiles:pinterest", []),
          dst.sets)
    check("the skip is reported, not silent",
          any("ads_k1fx40wf" in f for f in result.get("foreign_skipped", [])), result)
    # Freshness must not override ownership: theirs is newer (999 vs 100) and still
    # excluded, because the question is whose it is, not how recent.

    # --- and ones copied in BEFORE the rule existed get cleaned out ---------------
    print()
    stale = FakeRedis(
        hashes={"cookie:pinterest:ads_old": {"cookies_json": "{}"},
                "cookie:pinterest:profile_mine": {"cookies_json": "{}"}},
        sets={"valid_profiles:pinterest": ["ads_old", "profile_mine"]}, name="dst")
    removed = purge_foreign(stale, platforms=("pinterest",))
    check("a foreign jar already in our vault is purged",
          "cookie:pinterest:ads_old" not in stale.hashes, list(stale.hashes))
    check("and removed from the pool",
          "ads_old" not in stale.sets.get("valid_profiles:pinterest", []), stale.sets)
    check("our own profile survives the purge",
          "cookie:pinterest:profile_mine" in stale.hashes, list(stale.hashes))
    check("the purge reports what it removed",
          any("ads_old" in r for r in removed), removed)
    # Enforcing only on the way in would leave pre-rule copies in the pool for ever,
    # since sync never deletes from the destination.

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())

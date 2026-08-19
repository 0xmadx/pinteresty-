"""What kind of "no" is this? — and which ones may burn a session.

Exists because the old failover asked ONE question ("is there DataDome text, or is
it a 429?") and evicted the profile whenever the answer was yes. That conflated
three situations with three different correct responses:

  * a 429 means the session is FINE and we asked too fast. Evicting on it threw
    away a healthy session over a timing problem — and with one seller profile in
    the pool, that is the entire private tier gone until Chrome re-beams.
  * a 401/403 from OUR malformed request means the session is fine and the code is
    wrong. Evicting on it retires a good seller account over a missing header and
    sends the operator to re-login for nothing.
  * a genuinely dead cookie is the only case where eviction is right.

`etsy_private` authenticates as the operator's own seller account (D-29), so the
expensive direction of this error is destroying a working one.

    .venv/Scripts/python.exe -m core.test_session_classify
"""
from core.session_manager import (AUTH_EXPIRED, BLOCKED, EVICTABLE, MALFORMED, OK,
                                  RATE_LIMITED, classify)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}  {detail}")


class Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def main():
    print()
    check("a 200 is ok", classify(Resp(200)) == OK)
    check("a 429 is rate_limited, never blocked",
          classify(Resp(429)) == RATE_LIMITED, classify(Resp(429)))
    check("a rate limit must NOT be evictable — the session is healthy",
          RATE_LIMITED not in EVICTABLE)

    print()
    check("a bare 401 is a dead session",
          classify(Resp(401)) == AUTH_EXPIRED, classify(Resp(401)))
    check("a bare 403 is a dead session",
          classify(Resp(403)) == AUTH_EXPIRED, classify(Resp(403)))
    check("auth_expired IS evictable — that is the case eviction is for",
          AUTH_EXPIRED in EVICTABLE)

    print()
    check("a captcha page is a block, not an expiry",
          classify(Resp(403, "please complete the captcha")) == BLOCKED)
    check("DataDome is a block",
          classify(Resp(403, "<script>datadome</script>")) == BLOCKED)
    check("the captcha delivery host is a block",
          classify(Resp(401, "geo.captcha-delivery.com/x")) == BLOCKED)
    check("blocked IS evictable", BLOCKED in EVICTABLE)

    print()
    # The case that protects the seller account from OUR bugs.
    check("'invalid resource request' is OUR bug, not a dead session",
          classify(Resp(403, "Invalid Resource Request")) == MALFORMED,
          classify(Resp(403, "Invalid Resource Request")))
    check("malformed is NOT evictable — a code bug may never burn a session",
          MALFORMED not in EVICTABLE)
    check("case does not matter when reading the body",
          classify(Resp(403, "INVALID REQUEST")) == MALFORMED)

    print()
    check("a 500 is the server's problem, not the session's",
          classify(Resp(500)) == OK, classify(Resp(500)))
    check("a 503 likewise", classify(Resp(503)) == OK)

    print()
    # Precedence: a body carrying BOTH signals is a block. Bot detection is the
    # more consequential reading, and a captcha page can mention anything.
    check("captcha wins over the malformed phrasing when both appear",
          classify(Resp(403, "invalid request — captcha required")) == BLOCKED)
    check("a missing body does not crash the classifier",
          classify(Resp(401, None)) == AUTH_EXPIRED)

    print()
    check("exactly two verdicts may evict", set(EVICTABLE) == {AUTH_EXPIRED, BLOCKED},
          EVICTABLE)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())

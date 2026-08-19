"""Read-only Printify catalog client.

Printify sits at the END of this system's funnel, not the start. The analysis
decides *what* to make; Printify answers *what it costs to make it*. So this
client is deliberately small: it does not browse, it does not discover niches,
and it is never a source of demand signal.

WHAT THE CATALOG API GIVES (verified on the wire 2026-08-19, operator's token):

    blueprints            2,059 products
    print_providers       who can make one
    variants              sizes/colours/print areas  — NO PRICE FIELD
    shipping              per-country cost + handling time   ✅

WHAT IT DOES NOT GIVE — and this is the important half:

    production cost. There is no price on a catalog variant. `cost` exists only
    on a PRODUCT object, i.e. after something has been created in a shop. The
    Premium-subscription discount likewise cannot be read from the catalog.
    v2 catalog endpoints 404 on a personal access token.

    So `blueprint_cost()` does not exist and must not be invented. COGS enters
    this system as an operator-confirmed number (D-27: no figure the operator
    has not confirmed is treated as fact), and pod_costing keeps it None until
    they supply it rather than defaulting to something plausible.

No writes. The token carries products.write and orders.write; nothing here uses
them. Creating a product to read its cost is an account modification and is the
operator's call, not this module's.
"""
import os
import requests

BASE = "https://api.printify.com/v1"
# Printify's documented ceiling. Recorded so a future caller sizing a sweep has
# the real number rather than guessing.
RATE_LIMIT_PER_MINUTE = 600


class PrintifyError(RuntimeError):
    pass


class PrintifyClient:
    """Thin catalog reader. Every method returns parsed JSON or raises."""

    def __init__(self, token=None, session=None):
        self.token = token or os.getenv("PRINTIFY_API_TOKEN")
        if not self.token:
            raise PrintifyError(
                "PRINTIFY_API_TOKEN is not set. It lives in .env (untracked); "
                "this client never falls back to an unauthenticated call, because "
                "a silent 401 would look like an empty catalog.")
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {self.token}",
                        "User-Agent": "etsy-scrapper/1.0"}

    def _get(self, path, **params):
        r = self.session.get(BASE + path, headers=self.headers,
                             params=params or None, timeout=30)
        if r.status_code == 401:
            raise PrintifyError("Printify rejected the token (401) — it may have "
                                "expired or been revoked.")
        if r.status_code != 200:
            raise PrintifyError(f"{path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # --- catalog ----------------------------------------------------------------------
    def blueprints(self):
        return self._get("/catalog/blueprints.json")

    def print_providers(self, blueprint_id):
        return self._get(f"/catalog/blueprints/{blueprint_id}/print_providers.json")

    def variants(self, blueprint_id, provider_id):
        return self._get(
            f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        ).get("variants", [])

    def shipping(self, blueprint_id, provider_id):
        return self._get(
            f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/shipping.json")

    # --- account (read only) ------------------------------------------------------------
    def shops(self):
        return self._get("/shops.json")

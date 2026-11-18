"""Model-provider proxy: /model-providers/* -> Velaris /providers/* (KAN-18). Rules in gateway/velaris_proxy.py.

The provider registry (kind, base URL, key, sensitivity levels, usage) lives in Velaris, which makes the model calls.
Velaris requires the model_admin role for every one of these routes (owner and admin, core/velaris/roles.py), so a
member or viewer is refused there as well. Keys travel in the body of add/rotate only; the ledger entry holds field
NAMES and ids, never values, and Velaris never sends a key back (only the last four characters).
"""
from __future__ import annotations

from aether_os.gateway.velaris_proxy import Route as R, build_router

ROUTES = (
    R("GET", "/usage", "providers.usage"),                       # before "/{pid}" routes: order matters
    R("GET", "", "providers.list"),
    R("POST", "", "providers.create", log=("id", "kind", "preset")),
    R("PUT", "/{pid}", "providers.update"),
    R("POST", "/{pid}/rotate", "providers.rotate"),
    R("DELETE", "/{pid}", "providers.delete"),
    R("POST", "/{pid}/test", "providers.test", ledger=False),     # one cheap call, nothing changes
    R("GET", "/{pid}/models", "providers.models"),
    R("POST", "/{pid}/models/refresh", "providers.models.refresh", ledger=False),
)
router = build_router("/model-providers", "/providers", ROUTES, "velaris-providers")

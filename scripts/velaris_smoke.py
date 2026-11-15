#!/usr/bin/env python3.11
"""Live signed AetherOS -> Velaris smoke test (KAN-112): one correctly signed GET /trace/verify must answer 200.

    VELARIS_API_URL=... VELARIS_API_SECRET=... VELARIS_IDENTITY_PRIVATE_KEY_PEM=... \
        python3.11 scripts/velaris_smoke.py --org <AetherOS organisation id>

--org must equal Velaris's VELARIS_ORG, or Velaris refuses (that refusal is itself reported). Read-only; writes one trace
entry on the Velaris side. Exit 0 = pass, 1 = fail, 2 = Velaris is not configured here (nothing to test).
Run by deploy/deploy.sh after the health check when VELARIS_API_URL is set.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # the directory that contains the aether_os package

from aether_os.core.velaris.client import Identity, VelarisClient, VelarisUnavailable  # noqa: E402


async def check(client: VelarisClient, org: str) -> Tuple[bool, str]:
    """(passed, one-line reason). Never raises for an unreachable or refusing Velaris."""
    try:
        status, body = await client.request(Identity(user_id="deploy-smoke", org_id=org, org_role="owner"), "GET", "/trace/verify")
    except VelarisUnavailable as e:
        return False, f"Velaris unavailable: {e}"
    if status != 200:
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
        return False, f"HTTP {status} {code or ''}".strip()
    return True, "signed request accepted (HTTP 200)"


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    args = ap.parse_args(argv)
    try:
        client = VelarisClient.from_env(timeout=15)
    except VelarisUnavailable as e:
        print(f"SKIP: {e}")
        return 2
    ok, why = asyncio.run(check(client, args.org))
    print(("PASS: " if ok else "FAIL: ") + why)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

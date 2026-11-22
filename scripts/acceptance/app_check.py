"""Click-through check of a generated app's Live App preview: the acceptance gate for "the app is usable" (KAN-114).

Pipeline gates prove that stages pass; they never drove the generated UI against its backend. On 22 Nov 2026 runs 17,
18 and 20 were "fully green" while the generated app's pages crashed or called endpoints the backend never built. Run
this after every acceptance run; "green" means every check below passes.

Usage: python scripts/acceptance/app_check.py <dashboard_password_file> <run_id> <out_dir>
Env:   AETHER_BASE_URL     - the install, e.g. https://<host> (required)
       AETHER_ADMIN_EMAIL  - dashboard admin (default admin@aetheros.ai)
       APP_PW              - the generated app's preview admin password (preview_credentials.json of the run)
       APP_EMAIL           - the generated app's preview admin (default admin@example.com)
Needs: pip install playwright && playwright install chromium (run from an operator machine, not inside the API).

Signs in to the AetherOS dashboard ONCE (session saved to out_dir/dash_state.json, reused while valid), opens the
preview through /dashboard/preview-open/<run>, signs in to the generated app, then checks:
  C1 real UI (not the API-explorer fallback)       C2 sign-in reaches an authenticated page that did not crash
  C3 every sidebar page loads with no API call >=400  C4 at least one list shows rows the API returned
  C5 a record can be created through a "New ..." form (a POST answered 2xx)
Prints one PASS/FAIL line per check and writes a screenshot per page.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path



def text(page, n=400):
    return re.sub(r"\s+", " ", page.locator("body").inner_text())[:n]


_CRASH_RE = re.compile(r"Something went wrong|Failed to load", re.IGNORECASE)


def base_origin(url: str) -> str:
    """scheme://host of a URL (sidebar hrefs are root-relative)."""
    m = re.match(r"https?://[^/]+", url)
    return m.group(0) if m else ""


def crashed(body: str) -> bool:
    """True when the page shows the app's error boundary or a load failure instead of content."""
    return bool(_CRASH_RE.search(body))


def main(pw_file: str, rid: str, out: str) -> int:
    from playwright.sync_api import sync_playwright   # lazy: importing this module must not need a browser
    base = os.environ["AETHER_BASE_URL"].rstrip("/")
    dash_email = os.environ.get("AETHER_ADMIN_EMAIL", "admin@aetheros.ai")
    app_email = os.environ.get("APP_EMAIL", "admin@example.com")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state = out_dir / "dash_state.json"
    app_pw = os.environ["APP_PW"]
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900},
                            storage_state=str(state) if state.exists() else None)
        page = ctx.new_page()
        page.goto(base + "/dashboard/", wait_until="networkidle")
        if "/login" in page.url:
            page.locator('input[type="email"]').first.fill(dash_email)
            page.locator('input[type="password"]').first.fill(Path(pw_file).read_text().strip())
            page.locator('button[type="submit"]').first.click()
            page.wait_for_timeout(4000)
            if "/login" in page.url:
                print("ABORT dashboard sign-in failed:", text(page, 200))
                return 2
            ctx.storage_state(path=str(state))
        api = []
        page.on("response", lambda r: "/app-preview/api/" in r.url and api.append(
            (r.request.method, r.url.split("/app-preview")[1].split("?")[0], r.status)))
        page.goto(f"{base}/dashboard/preview-open/{rid}")
        page.wait_for_url(re.compile(r"\.preview\."), timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out_dir / "c1_landing.png"))
        body = text(page, 2000)
        results["C1 real UI"] = "API ENDPOINTS" not in body and "Preview Mode" not in body and len(body) > 20
        # C2 sign in
        if page.locator('input[type="email"]').count():
            page.locator('input[type="email"]').first.fill(app_email)
            page.locator('input[type="password"]').first.fill(app_pw)
            page.locator('button[type="submit"]').first.click()
            page.wait_for_timeout(5000)
        page.screenshot(path=str(out_dir / "c2_after_login.png"))
        # Run 22: the landing page crashed into the error boundary right after sign-in and C2 still passed.
        landing = text(page, 2000)
        results["C2 sign-in"] = ("/login" not in page.url and page.locator('input[type="password"]').count() == 0
                                 and not crashed(landing))
        if crashed(landing):
            print("  C2 landing page crashed:", landing[:200])
        # C3/C4 sidebar pages
        links = []
        for a in page.locator("nav a, aside a").all():
            href = a.get_attribute("href") or ""
            label = a.inner_text().strip()
            if href.startswith("/app-preview/") and label and href not in [h for _, h in links]:
                links.append((label, href))
        bad_pages, rows_seen = [], False
        home = page.url
        crashes = []
        page.on("pageerror", lambda e: crashes.append(str(e)[:200]))
        for label, href in links[:8]:
            api.clear()
            crashes.clear()
            if not page.locator(f'a[href="{href}"]').count():       # a crashed page has no sidebar: go back first
                page.goto(home)
                page.wait_for_timeout(3000)
            try:
                page.locator(f'a[href="{href}"]').first.click(timeout=10000)
            except Exception as exc:
                bad_pages.append((label, f"link not clickable: {str(exc)[:80]}"))
                continue
            page.wait_for_timeout(3500)
            slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:20]
            page.screenshot(path=str(out_dir / f"c3_{slug}.png"))
            failed = [c for c in api if c[2] >= 400]
            body_now = text(page, 300)
            if failed or crashes or crashed(body_now):
                bad_pages.append((label, failed[:3] or crashes[:1] or body_now[:80]))
            if page.locator("table tbody tr").count() > 0 and any(m == "GET" and s < 300 for m, _, s in api):
                rows_seen = True
            print(f"  page {label!r}: {len(api)} API calls, failed={failed[:2]}, rows={page.locator('table tbody tr').count()}")
        for label, why in bad_pages:
            print(f"  BROKEN {label!r}: {why}")
        results["C3 pages load"] = bool(links) and not bad_pages
        results["C4 data from API"] = rows_seen
        # C5 create through a form
        # The landing page may be a stats dashboard with no create button (run 23): try each sidebar page in turn.
        created = False
        new_sel = 'a:has-text("New"), button:has-text("New"), button:has-text("Add"), a:has-text("Add")'
        new = page.locator(new_sel).first
        for _label, href in [("home", home)] + links[:8]:
            page.goto(href if href.startswith("http") else base_origin(page.url) + href)
            page.wait_for_timeout(3000)
            new = page.locator(new_sel).first
            if new.count():
                print(f"  C5 create button on {_label!r}")
                break
        api.clear()
        if new.count():
            new.click()
            page.wait_for_timeout(2500)
            for inp in page.locator('form input:visible, [role="dialog"] input:visible').all():
                kind = (inp.get_attribute("type") or "text").lower()
                if kind in ("text", "email", "search", ""):
                    inp.fill("Acceptance check item")
                elif kind == "date":
                    inp.fill("2030-01-01")
                elif kind == "number":
                    inp.fill("1")
            for sel in page.locator('form select:visible, [role="dialog"] select:visible').all():
                opts = sel.locator("option").all()
                if len(opts) > 1:
                    sel.select_option(index=1)
            page.screenshot(path=str(out_dir / "c5_form.png"))
            page.locator('form button[type="submit"], [role="dialog"] button:has-text("Save"), '
                         '[role="dialog"] button:has-text("Create")').first.click()
            page.wait_for_timeout(4000)
            page.screenshot(path=str(out_dir / "c5_after_submit.png"))
            created = any(m == "POST" and 200 <= s < 300 for m, _, s in api)
            print("  create calls:", [c for c in api if c[0] in ("POST", "PUT", "PATCH")][:3])
        results["C5 create via form"] = created
        b.close()
    for k, v in results.items():
        print(("PASS " if v else "FAIL ") + k)
    (out_dir / "result.json").write_text(json.dumps(results, indent=2))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))

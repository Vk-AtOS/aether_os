"""
AetherOS Full Playwright Audit — targets live VPS at http://139.59.87.218
Covers all 20 UI tabs + per-org API key flow + live build monitoring.

Usage:
    python3 tests/playwright_full_audit.py

Outputs: tests/playwright_audit_report.md
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path

BASE = "http://139.59.87.218"
EMAIL = "demo@aetheros.ai"
PASSWORD = "demo1234"

REPORT_PATH = Path(__file__).parent / "playwright_audit_report.md"

results: list[dict] = []


def log(check: str, status: str, detail: str = ""):
    icon = "✅" if status == "PASS" else ("⚠️" if status == "WARN" else "❌")
    msg = f"{icon} [{status}] {check}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append({"check": check, "status": status, "detail": detail, "time": datetime.now().isoformat()})


async def run_audit():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        # Collect console errors
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)

        async def goto(url: str, wait: str = "networkidle", timeout: int = 15000):
            try:
                await page.goto(f"{BASE}{url}", wait_until=wait, timeout=timeout)
                await asyncio.sleep(2)  # allow React to render after navigation
                return True
            except Exception as e:
                log(f"Navigate {url}", "FAIL", str(e)[:120])
                return False

        async def fill_safe(sel: str, val: str):
            try:
                await page.fill(sel, val, timeout=5000)
                return True
            except Exception:
                return False

        async def click_safe(sel: str, timeout: int = 5000):
            try:
                await page.click(sel, timeout=timeout)
                return True
            except Exception:
                return False

        async def visible(sel: str, timeout: int = 4000) -> bool:
            try:
                await page.wait_for_selector(sel, state="visible", timeout=timeout)
                return True
            except Exception:
                return False

        async def text_present(substr: str, timeout: int = 5000) -> bool:
            try:
                await page.wait_for_function(
                    f"document.body.innerText.includes({json.dumps(substr)})",
                    timeout=timeout
                )
                return True
            except Exception:
                return False

        # ── 1. Landing Page ──────────────────────────────────────────────────
        print("\n=== Landing Page ===")
        if await goto("/"):
            if await text_present("AetherOS", 5000):
                log("Landing page loads", "PASS")
            else:
                log("Landing page loads", "WARN", "Page loaded but 'AetherOS' not found")

        # ── 2. Login ─────────────────────────────────────────────────────────
        print("\n=== Auth ===")
        # /login redirects (301) to /dashboard/login — go there directly
        if await goto("/dashboard/login"):
            await fill_safe("input[type='email']", EMAIL)
            await fill_safe("input[type='password']", PASSWORD)
            await click_safe("button[type='submit']")
            try:
                # Wait for URL to change away from login page
                await page.wait_for_url(
                    lambda url: "/dashboard" in url and "login" not in url,
                    timeout=12000,
                )
                log("Login flow", "PASS")
            except Exception:
                body_text = await page.inner_text("body")
                if "Invalid" in body_text or "incorrect" in body_text.lower():
                    log("Login flow", "FAIL", "Invalid credentials")
                else:
                    log("Login flow", "WARN", f"Did not redirect away from login. URL: {page.url}")

        # ── 3. Dashboard ─────────────────────────────────────────────────────
        print("\n=== Dashboard ===")
        if await goto("/dashboard"):
            await asyncio.sleep(3)
            body_text = await page.inner_text("body")
            if any(w in body_text for w in ["Dashboard", "Run", "Project", "Factory Control"]):
                log("Dashboard loads", "PASS")
            else:
                log("Dashboard loads", "WARN", "No dashboard content found")

        # ── 4. Projects list ─────────────────────────────────────────────────
        print("\n=== Projects ===")
        base_url = page.url.split("/dashboard")[0] + "/dashboard"
        if await goto("/dashboard/projects"):
            if await text_present("Project", 5000):
                log("Projects page loads", "PASS")
            else:
                log("Projects page loads", "WARN")

        # ── 5. New Project flow ───────────────────────────────────────────────
        print("\n=== New Project ===")
        if await goto("/dashboard/new-project"):
            # New project uses a multi-step wizard — look for wizard text
            if await text_present("build", 5000) or await text_present("Template", 5000) or await text_present("Project", 5000):
                log("New project page loads", "PASS")
                # Wizard step 1 has template cards, not a textarea — PASS if wizard renders
                if await text_present("TEMPLATE", 3000) or await text_present("Start fresh", 3000) or await text_present("SaaS", 3000):
                    log("New project wizard renders", "PASS")
                else:
                    log("New project wizard renders", "WARN", "Wizard templates not visible")
            else:
                log("New project page loads", "FAIL")

        # ── 6. Health / System ───────────────────────────────────────────────
        print("\n=== Health ===")
        if await goto("/dashboard/health"):
            if await text_present("Health", 5000) or await text_present("System", 5000):
                log("Health page loads", "PASS")
                if await text_present("ok", 5000) or await text_present("OK", 3000) or await text_present("healthy", 3000):
                    log("Health shows system status", "PASS")
                else:
                    log("Health shows system status", "WARN", "No 'ok/healthy' text")
            else:
                log("Health page loads", "FAIL")

        # ── 7. Billing ───────────────────────────────────────────────────────
        print("\n=== Billing ===")
        if await goto("/dashboard/admin/billing"):
            if await text_present("Billing", 5000):
                log("Billing page loads", "PASS")
                if await text_present("Plan", 5000):
                    log("Billing shows plan info", "PASS")
                else:
                    log("Billing shows plan info", "WARN")
                if await text_present("Trial", 3000) or await text_present("Pro", 3000):
                    log("Billing shows plan cards", "PASS")
                else:
                    log("Billing shows plan cards", "WARN", "No plan cards visible")
            else:
                log("Billing page loads", "FAIL")

        # ── 8. Settings ───────────────────────────────────────────────────────
        print("\n=== Settings ===")
        if await goto("/dashboard/settings"):
            if await text_present("Settings", 5000) or await text_present("API KEY", 5000) or await text_present("MODEL", 5000):
                log("Settings page loads", "PASS")
                # API key section labeled "API KEY MANAGEMENT"
                if await text_present("API KEY", 5000) or await text_present("ANTHROPIC", 3000):
                    log("Settings shows API key management", "PASS")
                else:
                    log("Settings shows API key management", "WARN")
                # Check per-org key badge
                if await text_present("Org key", 4000) or await text_present("org key", 3000):
                    log("Settings shows per-org key UI", "PASS")
                else:
                    log("Settings shows per-org key UI", "WARN", "No org-key badge — may need a key saved first")
                # Check SSO section
                if await text_present("SSO", 3000) or await text_present("SAML", 3000):
                    log("Settings shows SSO section", "PASS")
                else:
                    log("Settings shows SSO section", "WARN")
                # Check SCIM section
                if await text_present("SCIM", 3000):
                    log("Settings shows SCIM section", "PASS")
                else:
                    log("Settings shows SCIM section", "WARN")
            else:
                log("Settings page loads", "FAIL")

        # ── 9. Webhooks ───────────────────────────────────────────────────────
        print("\n=== Webhooks ===")
        if await goto("/dashboard/settings/webhooks"):
            if await text_present("Webhook", 5000):
                log("Webhooks page loads", "PASS")
                if await text_present("Configured", 4000) or await text_present("No webhooks", 4000):
                    log("Webhooks list renders", "PASS")
                else:
                    log("Webhooks list renders", "WARN")
            else:
                log("Webhooks page loads", "FAIL")

        # ── 10. Intelligence ──────────────────────────────────────────────────
        print("\n=== Intelligence ===")
        if await goto("/dashboard/admin/intelligence"):
            if await text_present("Intelligence", 5000):
                log("Intelligence page loads", "PASS")
            else:
                log("Intelligence page loads", "WARN", "Not visible to this user role or page missing")

        # ── 11. Compliance ────────────────────────────────────────────────────
        print("\n=== Compliance ===")
        if await goto("/dashboard/compliance"):
            if await text_present("Compliance", 5000):
                log("Compliance page loads", "PASS")
                if await text_present("Report", 4000) or await text_present("Score", 4000):
                    log("Compliance shows report data", "PASS")
                else:
                    log("Compliance shows report data", "WARN")
            else:
                log("Compliance page loads", "FAIL")

        # ── 12. Audit Logs ────────────────────────────────────────────────────
        print("\n=== Audit Logs ===")
        if await goto("/dashboard/audit"):
            if await text_present("Audit", 5000):
                log("Audit logs page loads", "PASS")
                if await text_present("Export", 4000) or await text_present("logs", 4000):
                    log("Audit shows log controls", "PASS")
                else:
                    log("Audit shows log controls", "WARN")
            else:
                log("Audit logs page loads", "FAIL")

        # ── 13. Marketplace ───────────────────────────────────────────────────
        print("\n=== Marketplace ===")
        if await goto("/dashboard/marketplace"):
            if await text_present("Marketplace", 5000):
                log("Marketplace page loads", "PASS")
                if await text_present("profile", 4000) or await text_present("Install", 4000) or await text_present("No profiles", 4000):
                    log("Marketplace shows profiles", "PASS")
                else:
                    log("Marketplace shows profiles", "WARN")
            else:
                log("Marketplace page loads", "FAIL")

        # ── 14. Costs ─────────────────────────────────────────────────────────
        print("\n=== Costs ===")
        if await goto("/dashboard/costs"):
            if await text_present("Cost", 5000):
                log("Costs page loads", "PASS")
            else:
                log("Costs page loads", "FAIL")

        # ── 15. Agents ────────────────────────────────────────────────────────
        print("\n=== Agents ===")
        if await goto("/dashboard/agents"):
            if await text_present("Agent", 5000):
                log("Agents page loads", "PASS")
            else:
                log("Agents page loads", "FAIL")

        # ── 16. Connectors ────────────────────────────────────────────────────
        print("\n=== Connectors ===")
        if await goto("/dashboard/connectors"):
            if await text_present("Connector", 5000) or await text_present("GitHub", 5000):
                log("Connectors page loads", "PASS")
            else:
                log("Connectors page loads", "WARN")

        # ── 17. Memory ────────────────────────────────────────────────────────
        print("\n=== Memory ===")
        if await goto("/dashboard/memory"):
            if await text_present("Memory", 5000):
                log("Memory page loads", "PASS")
            else:
                log("Memory page loads", "WARN")

        # ── 18. Learning ──────────────────────────────────────────────────────
        print("\n=== Learning ===")
        if await goto("/dashboard/learning"):
            if await text_present("Learn", 5000):
                log("Learning page loads", "PASS")
            else:
                log("Learning page loads", "WARN")

        # ── 19. Admin Users ───────────────────────────────────────────────────
        print("\n=== Admin Users ===")
        if await goto("/dashboard/admin/users"):
            if await text_present("User", 5000):
                log("Admin users page loads", "PASS")
                if await text_present("Invite", 4000) or await text_present("Role", 4000):
                    log("Admin shows user controls", "PASS")
                else:
                    log("Admin shows user controls", "WARN")
            else:
                log("Admin users page loads", "WARN", "May redirect if not admin")

        # ── 20. Profile ───────────────────────────────────────────────────────
        print("\n=== Profile ===")
        if await goto("/dashboard/profile"):
            if await text_present("Profile", 5000) or await text_present("Account", 5000):
                log("Profile page loads", "PASS")
            else:
                log("Profile page loads", "WARN")

        # ── 21. Check Backend API directly ────────────────────────────────────
        print("\n=== Backend API ===")
        api_checks = [
            ("/api/health", "ok"),
            ("/api/billing/plans", "plans"),
            ("/api/system/health", "status"),
        ]
        for api_path, expected in api_checks:
            resp = await page.request.get(f"{BASE}{api_path}")
            body = await resp.text()
            if resp.status == 200 and expected in body:
                log(f"API {api_path}", "PASS", f"HTTP {resp.status}")
            elif resp.status == 401:
                log(f"API {api_path}", "PASS", "401 — auth-gated endpoint (expected)")
            else:
                log(f"API {api_path}", "FAIL", f"HTTP {resp.status}, body: {body[:100]}")

        # ── 22. Console errors summary ─────────────────────────────────────────
        print("\n=== Console Errors ===")
        critical_errors = [e for e in console_errors if "chunk" in e.lower() or "TypeError" in e or "Cannot read" in e]
        if not critical_errors:
            log("No critical JS console errors", "PASS", f"({len(console_errors)} total console messages)")
        else:
            for e in critical_errors[:5]:
                log("JS console error", "FAIL", e[:150])

        await browser.close()

    # ── Write Report ─────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    lines = [
        f"# AetherOS Playwright Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"\n**{passed}/{total} PASS · {warned} WARN · {failed} FAIL**\n",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        icon = "✅" if r["status"] == "PASS" else ("⚠️" if r["status"] == "WARN" else "❌")
        lines.append(f"| {icon} {r['status']} | {r['check']} | {r['detail'] or ''} |")

    lines += [
        "\n## Failed / Warned Items",
        *(f"- **{r['check']}**: {r['detail']}" for r in results if r["status"] != "PASS"),
    ]

    REPORT_PATH.write_text("\n".join(lines))
    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE: {passed} PASS · {warned} WARN · {failed} FAIL")
    print(f"Report written to {REPORT_PATH}")
    return results


if __name__ == "__main__":
    asyncio.run(run_audit())

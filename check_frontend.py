import asyncio
from playwright.async_api import async_playwright
import sys

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Listen for console messages
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        
        # Listen for page errors (crashes)
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(err.message))

        print("Navigating to login page...")
        await page.goto("http://localhost:8081/dashboard/login")
        await page.wait_for_timeout(2000)

        print("Performing login...")
        await page.fill('input[type="email"]', "admin@aetheros.ai")
        await page.fill('input[type="password"]', "password123")
        await page.click('button:has-text("START FACTORY")')
        
        await page.wait_for_url("**/dashboard*")
        await page.wait_for_timeout(5000) # Wait for data to load

        print(f"Current URL: {page.url}")
        
        # Check for blank screen
        content = await page.content()
        if "root" in content and len(content) < 1000:
            print("WARNING: Possible blank screen detected (root element empty or very small).")
        
        if console_errors:
            print("\nConsole Errors found:")
            for err in console_errors:
                print(f"  - {err}")
        
        if page_errors:
            print("\nPage Errors (Crashes) found:")
            for err in page_errors:
                print(f"  - {err}")

        # Screenshot for evidence
        await page.screenshot(path="audit_screenshot.png")
        print("\nScreenshot saved to audit_screenshot.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

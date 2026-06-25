import asyncio
from playwright.async_api import async_playwright

async def run_test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("Navigating to login page...")
        await page.goto("http://127.0.0.1:8001/login")
        
        # In case it redirects to /login
        if "/login" in page.url:
            print("Already at login page.")
        
        print("Filling credentials...")
        await page.fill("input[name='username']", "admin")
        await page.fill("input[name='password']", "admin_password")
        
        print("Submitting login...")
        await page.click("button[type='submit']")
        
        await page.wait_for_url("**/dashboard")
        print(f"Successfully logged in. Current URL: {page.url}")
        
        print("Verifying dashboard content...")
        await page.wait_for_selector(".table-container")
        
        title = await page.inner_text("h1")
        print(f"Dashboard Title: {title}")
        
        # Wait for rows to be populated (if they are populated via JS)
        await asyncio.sleep(2) 
        
        jobs_count = await page.locator("#jobs-tbody tr").count()
        print(f"Found {jobs_count} job rows.")
        
        # Take a screenshot
        await page.screenshot(path="dashboard_test.png")
        print("Screenshot saved to dashboard_test.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_test())

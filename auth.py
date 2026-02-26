"""
Phase 0: Authentication
- Logs in via Playwright at auth.glintsolar.com
- Extracts session cookies
- Returns a cookie dict usable by httpx for all subsequent API calls
"""
import asyncio
from playwright.async_api import async_playwright
import config


async def playwright_login(email: str, password: str) -> dict[str, str]:
    """
    Logs into Glint Solar and returns session cookies.
    Cookies are extracted after successful login and validated via /sessions/whoami.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("[auth] Navigating to login page...")
        await page.goto(f"{config.AUTH_BASE}/login")
        await page.wait_for_load_state("networkidle")

        print("[auth] Filling credentials...")
        await page.fill('input[type="email"]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"]')

        # Wait for redirect to main app — indicates successful login
        await page.wait_for_url(f"{config.API_BASE}/**", timeout=15_000)
        print("[auth] Login successful. Extracting cookies...")

        raw_cookies = await context.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}

        await browser.close()

    return cookies


async def validate_session(client) -> bool:
    """
    Hits /sessions/whoami to confirm the cookie session is valid.
    Returns True if the session is active.
    """
    r = await client.get(f"{config.AUTH_BASE}/sessions/whoami")
    if r.status_code == 200:
        identity = r.json()
        print(f"[auth] Session valid — user: {identity.get('identity', {}).get('traits', {}).get('email', 'unknown')}")
        return True
    print(f"[auth] Session invalid — status {r.status_code}")
    return False

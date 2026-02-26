"""
Phase 0: Authentication
- Logs in via Playwright at auth.glintsolar.com
- Extracts session cookies
- Returns a cookie dict usable by httpx for all subsequent API calls
"""
import asyncio
from playwright.async_api import async_playwright
import config


async def playwright_login(
    email: str, password: str
) -> tuple[dict[str, str], dict]:
    """
    Logs into Glint Solar and returns (cookies_for_httpx, playwright_storage_state).

    cookies_for_httpx  — {name: value} dict passed directly to httpx.AsyncClient
    playwright_storage_state — full Playwright state dict; pass to
        browser.new_context(storage_state=...) in Phase 3 to restore the session
        without re-authenticating.
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
        await page.click('button:has-text("Log in")')

        # Wait for redirect to main app — indicates successful login
        try:
            await page.wait_for_url(f"{config.API_BASE}/**", timeout=15_000)
            await asyncio.sleep(3)  # allow post-redirect auth state to fully settle
        except Exception:
            await page.screenshot(path="output/auth_failure.png")
            raise RuntimeError(
                "Login did not redirect to app — screenshot saved to output/auth_failure.png. "
                "Possible causes: wrong credentials, MFA prompt, CAPTCHA, or rate limit."
            )
        print("[auth] Login successful. Extracting cookies and storage state...")

        storage_state = await context.storage_state()
        raw_cookies = await context.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}

        await browser.close()

    return cookies, storage_state


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

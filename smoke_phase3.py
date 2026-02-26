"""
Phase 3 smoke test — runs the installed capacity flow for one parcel
against the configured PROJECT_URL. No Phase 1/2 needed.

Usage: python smoke_phase3.py
"""
import asyncio
from playwright.async_api import async_playwright
from auth import playwright_login
from installed_capacity import get_installed_capacity
import config


async def main():
    print("=== Phase 0: Auth ===")
    _, storage_state = await playwright_login(config.EMAIL, config.PASSWORD)

    print("\n=== Phase 3: Installed Capacity (smoke test) ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=storage_state)
        try:
            parcel = {"parcel_id": "smoke_test"}
            result = await get_installed_capacity(context, parcel)
            print(f"\nResult: {result} kW")
        finally:
            await browser.close()


asyncio.run(main())

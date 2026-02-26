"""
Headed browser session for capturing Phase 3 DOM selectors.
Run with: python capture_selectors.py
"""
import asyncio
from playwright.async_api import async_playwright
import config


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(config.AUTH_BASE)
        input("Log in, navigate to a parcel with buildable area, then press Enter to close...")


asyncio.run(run())

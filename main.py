"""
Glint Solar Prospecting Agent — main entry point.
Run: python main.py

Phases:
  0  Auth         — Playwright login → persistent BrowserContext + httpx cookies
  1a Tile enum    — PBF tile decode → parcel IDs
  1b Properties   — parcel-properties API → metadata
  2  Buildable    — buildable-area-async POST → S3 poll → shapely calc
  3  Capacity     — Playwright DOM: Copy to project → New Analysis → read kW
  4  Export       — write output/parcels.csv

Phase 3 note: Installed capacity is computed client-side by Glint's JS bundles.
It never appears in any API response. Playwright is required to read the DOM value.
Screenshots of every Phase 3 step are saved to output/screenshots/ for audit.
"""
import asyncio
import os
import pandas as pd
import httpx
from playwright.async_api import async_playwright

import config
from auth import validate_session
from tiles import enumerate_parcel_ids
from parcels import fetch_all_parcel_properties, get_parcel_geometry
from buildable_area import run_buildable_area
from installed_capacity import get_installed_capacity, copy_to_project


async def playwright_login_and_get_cookies(playwright) -> tuple:
    """
    Logs in via Playwright, returns (context, cookies_dict).
    The context is kept open for Phase 3 reuse.
    """
    from auth import playwright_login
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    print("[auth] Navigating to login page...")
    await page.goto(f"{config.AUTH_BASE}/login")
    await page.wait_for_load_state("networkidle")
    await page.fill('input[type="email"]', config.EMAIL)
    await page.fill('input[type="password"]', config.PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(f"{config.API_BASE}/**", timeout=15_000)
    print("[auth] Login successful.")

    raw_cookies = await context.cookies()
    cookies = {c["name"]: c["value"] for c in raw_cookies}
    await page.close()
    return context, cookies


async def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.SCREENSHOT_DIR, exist_ok=True)

    async with async_playwright() as playwright:

        # ── Phase 0: Auth ──────────────────────────────────────────────────────
        print("\n=== Phase 0: Authentication ===")
        pw_context, cookies = await playwright_login_and_get_cookies(playwright)

        async with httpx.AsyncClient(cookies=cookies, timeout=30.0) as client:
            session_ok = await validate_session(client)
            if not session_ok:
                raise RuntimeError("Session validation failed — check credentials.")

            # ── Phase 1a: Tile Enumeration ───────────────────────────────────
            print("\n=== Phase 1a: Tile Enumeration ===")
            parcel_ids = await enumerate_parcel_ids(client)
            if not parcel_ids:
                print("No parcel IDs found — check bounding box and tile auth.")
                return

            # ── Phase 1b: Parcel Properties ──────────────────────────────────
            print(f"\n=== Phase 1b: Parcel Properties ({len(parcel_ids)} parcels) ===")
            parcels = await fetch_all_parcel_properties(client, parcel_ids)

            # ── Phase 2: Buildable Area ──────────────────────────────────────
            print(f"\n=== Phase 2: Buildable Area ({len(parcels)} parcels) ===")
            geometries: dict[str, dict] = {}
            for i, parcel in enumerate(parcels, 1):
                pid = parcel["parcel_id"]
                print(f"[{i}/{len(parcels)}] Buildable area for {pid}...")
                geometry = await get_parcel_geometry(client, pid)
                if not geometry:
                    continue
                geometries[pid] = geometry
                await run_buildable_area(client, parcel, geometry)

            # Filter to parcels with meaningful buildable area before Phase 3
            buildable_parcels = [
                p for p in parcels
                if (p.get("buildable_area_acres") or 0) > 0
            ]
            print(f"[main] {len(buildable_parcels)} parcels have buildable area > 0")

            # ── Phase 3: Installed Capacity (Playwright DOM) ─────────────────
            print(f"\n=== Phase 3: Installed Capacity ({len(buildable_parcels)} parcels) ===")
            print("[main] Using Playwright — installed capacity is computed client-side by Glint's JS.")
            for i, parcel in enumerate(buildable_parcels, 1):
                pid = parcel["parcel_id"]
                print(f"[{i}/{len(buildable_parcels)}] Phase 3 for {pid}...")

                # Copy buildable area into a new project
                project_id = await copy_to_project(
                    pw_context, parcel, geometries.get(pid)
                )
                if project_id:
                    parcel["project_id"] = project_id
                    parcel["installed_capacity_kw"] = await get_installed_capacity(
                        pw_context, parcel
                    )
                else:
                    print(f"[main] Skipping capacity for {pid} — project creation failed")

        # ── Phase 4: Export ───────────────────────────────────────────────────
        print(f"\n=== Phase 4: Exporting CSV ===")
        column_order = [
            "parcel_id",
            "owner_name",
            "parcel_address",
            "mail_address",
            "total_area_acres",
            "land_use",
            "assessed_value",
            "buildable_area_acres",
            "buildable_pct",
            "installed_capacity_kw",
            "lat",
            "lon",
        ]
        df = pd.DataFrame(parcels)
        for col in column_order:
            if col not in df.columns:
                df[col] = None
        df = df[column_order]
        df.to_csv(config.OUTPUT_CSV, index=False)
        print(f"Saved {len(df)} parcels → {config.OUTPUT_CSV}")
        print(df.describe())


if __name__ == "__main__":
    asyncio.run(main())

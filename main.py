"""
Glint Solar Prospecting Agent — main entry point.
Run: python main.py

Phases:
  0  Auth         — Playwright login → extract cookies
  1a Tile enum    — PBF tile decode → parcel IDs
  1b Properties   — parcel-properties API → metadata
  2  Buildable    — buildable-area-async POST → S3 poll → shapely calc
  3  Capacity     — installed capacity (STUB — see installed_capacity.py)
  4  Export       — write output/parcels.csv
"""
import asyncio
import os
import pandas as pd
import httpx

import config
from auth import playwright_login, validate_session
from tiles import enumerate_parcel_ids
from parcels import fetch_all_parcel_properties, get_parcel_geometry
from buildable_area import run_buildable_area
from installed_capacity import get_installed_capacity


async def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # ── Phase 0: Auth ─────────────────────────────────────────────────────────
    print("\n=== Phase 0: Authentication ===")
    cookies = await playwright_login(config.EMAIL, config.PASSWORD)

    async with httpx.AsyncClient(cookies=cookies, timeout=30.0) as client:
        session_ok = await validate_session(client)
        if not session_ok:
            raise RuntimeError("Session validation failed — check credentials and cookie extraction.")

        # ── Phase 1a: Tile Enumeration ─────────────────────────────────────────
        print("\n=== Phase 1a: Tile Enumeration ===")
        parcel_ids = await enumerate_parcel_ids(client)
        if not parcel_ids:
            print("No parcel IDs found — check bounding box and tile auth.")
            return

        # ── Phase 1b: Parcel Properties ────────────────────────────────────────
        print(f"\n=== Phase 1b: Parcel Properties ({len(parcel_ids)} parcels) ===")
        parcels = await fetch_all_parcel_properties(client, parcel_ids)

        # ── Phase 2: Buildable Area ────────────────────────────────────────────
        print(f"\n=== Phase 2: Buildable Area ({len(parcels)} parcels) ===")
        for i, parcel in enumerate(parcels, 1):
            print(f"[{i}/{len(parcels)}] Running buildable area for {parcel['parcel_id']}...")
            geometry = await get_parcel_geometry(client, parcel["parcel_id"])
            if not geometry:
                continue
            await run_buildable_area(client, parcel, geometry)

        # ── Phase 3: Installed Capacity (Stub) ────────────────────────────────
        print(f"\n=== Phase 3: Installed Capacity (stub) ===")
        for parcel in parcels:
            parcel["installed_capacity_kw"] = await get_installed_capacity(client, parcel)

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
        df = pd.DataFrame(parcels)[column_order]
        df.to_csv(config.OUTPUT_CSV, index=False)
        print(f"Saved {len(df)} parcels to {config.OUTPUT_CSV}")
        print(df.describe())


if __name__ == "__main__":
    asyncio.run(main())

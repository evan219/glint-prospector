"""
Glint Solar Prospecting Agent — main entry point.
Run: python main.py

Phases:
  0  Auth         — Playwright login → extract cookies + storage state
  1  Project      — GET /api/objects → extract parcel IDs from the project
  3  Per-parcel   — for each parcel: show/hide via objects API → run buildable
                    area via UI → capture S3 result for acres → New Analysis kW
  4  Export       — write output/parcels.csv
"""
import asyncio
import os
import pandas as pd
import httpx

import config
from auth import playwright_login, validate_session
from objects import get_project_objects, get_parcels
from installed_capacity import get_all_installed_capacities


async def main():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # ── Phase 0: Auth ─────────────────────────────────────────────────────────
    print("\n=== Phase 0: Authentication ===")
    cookies, storage_state = await playwright_login(config.EMAIL, config.PASSWORD)

    async with httpx.AsyncClient(cookies=cookies, timeout=30.0) as client:
        session_ok = await validate_session(client)
        if not session_ok:
            raise RuntimeError(
                "Session validation failed — check credentials and cookie extraction."
            )

        # ── Phase 1: Project Object Enumeration ───────────────────────────────
        print(f"\n=== Phase 1: Project Parcels (project: {config.PROJECT_ID}) ===")
        all_objects = await get_project_objects(client, config.PROJECT_ID)
        project_parcels = get_parcels(all_objects)
        if not project_parcels:
            print("No parcels found in project — add parcels in the Glint UI and re-run.")
            return

        parcels = [
            {
                "parcel_id": obj["title"][len("Parcel "):].strip(),
                "total_area_acres": None,
                "buildable_area_acres": None,
                "buildable_pct": None,
                "installed_capacity_kw": None,
            }
            for obj in project_parcels
            if obj.get("title", "").startswith("Parcel ")
        ]
        print(f"[project] {len(parcels)} parcel(s): {[p['parcel_id'] for p in parcels]}")

    # ── Phase 3: Per-Parcel Analysis ──────────────────────────────────────────
    print(f"\n=== Phase 3: Per-Parcel Analysis ({len(parcels)} parcels) ===")
    async with httpx.AsyncClient(cookies=cookies, timeout=30.0) as phase3_client:
        await get_all_installed_capacities(storage_state, phase3_client, parcels)

    # ── Phase 4: Export ───────────────────────────────────────────────────────
    print("\n=== Phase 4: Exporting CSV ===")
    column_order = [
        "parcel_id",
        "buildable_area_acres",
        "buildable_pct",
        "installed_capacity_kw",
        "kw_agent_reported",
        "kw_verified",
        "kw_match",
    ]
    # Ensure new columns exist even if Phase 3 was skipped.
    for p in parcels:
        p.setdefault("kw_agent_reported", None)
        p.setdefault("kw_verified", None)
        p.setdefault("kw_match", None)
    df = pd.DataFrame(parcels)[column_order]
    df.to_csv(config.OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} parcels to {config.OUTPUT_CSV}")
    print(df.to_string())


if __name__ == "__main__":
    asyncio.run(main())

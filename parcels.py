"""
Phase 1b: Parcel Properties & Geometry
- Fetches parcel-properties (lightweight metadata) for each parcel ID
- Fetches parcel GeoJSON geometry (needed as input to buildable-area)
"""
import asyncio
import httpx
import config


def _params(parcel_id: str, include_geo: bool = False) -> dict:
    base = {
        "packageId": config.PACKAGE_ID_STATE,
        "id": parcel_id,
        "version": config.PARCEL_VERSION,
    }
    if not include_geo:
        base["orgId"] = config.ORG_ID
    return base


async def get_parcel_properties(client: httpx.AsyncClient, parcel_id: str) -> dict | None:
    """
    Fetches lightweight parcel metadata. Returns a normalized dict or None on error.
    """
    r = await client.get(
        f"{config.API_BASE}/api/parcels/parcel-properties",
        params=_params(parcel_id),
    )
    if r.status_code != 200:
        print(f"[parcels] parcel-properties failed for {parcel_id}: {r.status_code}")
        return None

    data = r.json()
    return {
        "parcel_id": data.get("parcel_id", parcel_id),
        "owner_name": data.get("ownership_info", ""),
        "parcel_address": data.get("parcel_address", ""),
        "mail_address": data.get("mail_address", ""),
        "total_area_acres": round(data.get("area", 0) / 4046.86, 2),
        "land_use": data.get("land_use", ""),
        "assessed_value": data.get("tot_val", None),
        # lat/lon populated below if present
        "lat": data.get("lat") or data.get("latitude"),
        "lon": data.get("lon") or data.get("longitude"),
        # Phase 2 & 3 fields filled in later
        "buildable_area_acres": None,
        "buildable_pct": None,
        "installed_capacity_kw": None,
    }


async def get_parcel_geometry(client: httpx.AsyncClient, parcel_id: str) -> dict | None:
    """
    Fetches the GeoJSON polygon for a parcel. Required as input for buildable-area POST.
    """
    r = await client.get(
        f"{config.API_BASE}/api/parcels/parcel-geometry",
        params={
            "id": parcel_id,
            "packageId": config.PACKAGE_ID_STATE,
            "version": config.PARCEL_VERSION,
        },
    )
    if r.status_code != 200:
        print(f"[parcels] parcel-geometry failed for {parcel_id}: {r.status_code}")
        return None
    return r.json()


async def fetch_all_parcel_properties(
    client: httpx.AsyncClient, parcel_ids: list[str]
) -> list[dict]:
    """
    Fetches parcel-properties for all IDs concurrently (batched).
    Returns list of non-None results.
    """
    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_PARCEL_CALLS)

    async def fetch_one(pid: str):
        async with semaphore:
            return await get_parcel_properties(client, pid)

    results = await asyncio.gather(*[fetch_one(pid) for pid in parcel_ids])
    valid = [r for r in results if r is not None]
    print(f"[parcels] Fetched properties for {len(valid)}/{len(parcel_ids)} parcels")
    return valid

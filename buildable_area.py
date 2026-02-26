"""
Phase 2: Buildable Area Analysis
- POSTs to buildable-area-async to kick off the job
- Polls S3 until the result GeoJSON appears (or timeout)
- Calculates total buildable acres using shapely
"""
import asyncio
import httpx
from shapely.geometry import shape
import config


async def post_buildable_area(
    client: httpx.AsyncClient,
    geometry: dict,
    parcel_id: str,
) -> str | None:
    """
    Kicks off a buildable-area-async job. Returns the requestId UUID or None on failure.
    geometry: GeoJSON geometry dict from parcel-geometry API.
    """
    body = {
        "constraints": config.BUILDABLE_CONSTRAINTS,
        "geometries": [geometry],
        "withS3Upload": True,
    }
    params = {
        "orgId": config.ORG_ID,
        "portfolioId": config.PORTFOLIO_ID,
    }
    r = await client.post(
        f"{config.API_BASE}/api/geo-insights-v2/buildable-area-async",
        json=body,
        params=params,
    )
    if r.status_code not in (200, 202):
        print(f"[buildable] POST failed for {parcel_id}: {r.status_code} — {r.text[:200]}")
        return None

    data = r.json()
    request_id = data.get("requestId")
    print(f"[buildable] Job submitted for {parcel_id} — requestId: {request_id}")
    return request_id


async def poll_s3_result(request_id: str) -> dict | None:
    """
    Polls the S3 result URL until the GeoJSON file is ready (HTTP 200) or timeout.
    Returns the parsed GeoJSON FeatureCollection or None on timeout.
    """
    url = (
        f"{config.S3_BASE}/{config.PORTFOLIO_ID}"
        f"/buildable-area/{request_id}.json"
    )
    async with httpx.AsyncClient() as s3_client:
        for attempt in range(config.S3_POLL_MAX_ATTEMPTS):
            r = await s3_client.get(url)
            if r.status_code == 200:
                print(f"[buildable] Result ready after {attempt + 1} poll(s)")
                return r.json()
            await asyncio.sleep(config.S3_POLL_INTERVAL_SECONDS)

    print(f"[buildable] Timeout waiting for requestId {request_id}")
    return None


def calculate_buildable_acres(geojson: dict) -> float:
    """
    Sums the area of all features in a GeoJSON FeatureCollection.
    Returns total buildable area in acres.
    """
    total_sqm = sum(
        shape(feature["geometry"]).area
        for feature in geojson.get("features", [])
    )
    return round(total_sqm / 4046.86, 2)


async def run_buildable_area(
    client: httpx.AsyncClient,
    parcel: dict,
    geometry: dict,
) -> dict:
    """
    Full Phase 2 flow for a single parcel.
    Mutates and returns the parcel dict with buildable_area_acres and buildable_pct filled in.
    """
    request_id = await post_buildable_area(client, geometry, parcel["parcel_id"])
    if not request_id:
        return parcel

    result = await poll_s3_result(request_id)
    if not result:
        return parcel

    buildable_acres = calculate_buildable_acres(result)
    total_acres = parcel.get("total_area_acres") or 1
    parcel["buildable_area_acres"] = buildable_acres
    parcel["buildable_pct"] = round(buildable_acres / total_acres * 100, 1) if total_acres else 0

    return parcel

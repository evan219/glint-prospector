"""
Phase 2: Buildable Area Analysis
- POSTs to buildable-area-async to kick off the job
- Polls S3 until the result GeoJSON appears (or timeout)
- Calculates total buildable acres using shapely
"""
import asyncio
import httpx
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform
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
    async with httpx.AsyncClient(timeout=30.0) as s3_client:
        for attempt in range(config.S3_POLL_MAX_ATTEMPTS):
            r = await s3_client.get(url)
            if r.status_code == 200:
                print(f"[buildable] Result ready after {attempt + 1} poll(s)")
                return r.json()
            await asyncio.sleep(config.S3_POLL_INTERVAL_SECONDS)

    print(f"[buildable] Timeout waiting for requestId {request_id}")
    return None


def _utm_transformer() -> object:
    """
    Returns a WGS84 → UTM transformer for the configured bounding box centroid.
    GeoJSON coordinates are in geographic degrees; shapely.area on geographic coords
    returns sq-degrees, not sq-metres — reprojection to UTM is required for accuracy.
    """
    lon = (config.BBOX["lon_min"] + config.BBOX["lon_max"]) / 2
    lat = (config.BBOX["lat_min"] + config.BBOX["lat_max"]) / 2
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform


def calculate_buildable_acres(geojson: dict) -> float:
    """
    Sums the area of all features in a GeoJSON FeatureCollection.
    Reprojects WGS84 → UTM so shapely computes square metres, not square degrees.
    Returns total buildable area in acres.
    """
    features = geojson.get("features", [])
    if not features:
        return 0.0
    transformer = _utm_transformer()
    total_sqm = sum(
        shp_transform(transformer, shape(f["geometry"])).area
        for f in features
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
    total_acres = parcel.get("total_area_acres") or 0
    parcel["buildable_area_acres"] = buildable_acres
    parcel["buildable_pct"] = round(buildable_acres / total_acres * 100, 1) if total_acres else None

    return parcel

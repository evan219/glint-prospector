"""
Phase 1a: PBF Tile Enumeration
- Converts a lat/lon bounding box to Mapbox tile coordinates at a given zoom
- Downloads PBF tiles from Glint's API (auth required)
- Decodes tiles with mapbox-vector-tile to extract parcel IDs
"""
import math
import asyncio
import httpx
import mapbox_vector_tile
import config


def lat_lon_to_tile(lat: float, lon: float, z: int) -> tuple[int, int, int]:
    """Convert lat/lon to (z, x, y) tile coordinates using the slippy map formula."""
    x = int((lon + 180) / 360 * 2**z)
    y = int(
        (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
        / 2
        * 2**z
    )
    return z, x, y


def bbox_to_tile_range(bbox: dict, z: int) -> list[tuple[int, int]]:
    """
    Returns all (x, y) tile coords that cover the given bounding box at zoom z.
    bbox keys: lat_min, lat_max, lon_min, lon_max
    """
    _, x_min, y_max = lat_lon_to_tile(bbox["lat_min"], bbox["lon_min"], z)
    _, x_max, y_min = lat_lon_to_tile(bbox["lat_max"], bbox["lon_max"], z)
    tiles = [
        (x, y)
        for x in range(x_min, x_max + 1)
        for y in range(y_min, y_max + 1)
    ]
    print(f"[tiles] Bounding box maps to {len(tiles)} tiles at zoom {z}")
    return tiles


async def fetch_tile(client: httpx.AsyncClient, z: int, x: int, y: int) -> bytes | None:
    """Download a single PBF tile. Returns raw bytes or None on failure."""
    url = (
        f"{config.API_BASE}/api/pkg/parcels_{config.PARCEL_VERSION}"
        f"/{z}/{x}/{y}.pbf?packageId={config.PACKAGE_ID_NATIONAL}"
    )
    r = await client.get(url)
    if r.status_code == 200:
        return r.content
    print(f"[tiles] Tile ({z}/{x}/{y}) returned {r.status_code} — skipping")
    return None


def decode_parcel_ids(pbf_bytes: bytes) -> list[str]:
    """
    Decodes a PBF tile and returns unique parcel IDs found in the 'parcels' layer.
    Relevant fields: parcel_id, ownership_info, area, land_use, tot_val, zoning
    """
    tile = mapbox_vector_tile.decode(pbf_bytes)
    layer = tile.get("main", {})
    features = layer.get("features", [])
    ids = []
    for feature in features:
        props = feature.get("properties", {})
        pid = props.get("parcel_id") or props.get("id")
        if pid:
            ids.append(str(pid))
    return list(set(ids))


async def enumerate_parcel_ids(client: httpx.AsyncClient) -> list[str]:
    """
    Full Phase 1a flow: download all tiles for the configured bbox and extract parcel IDs.
    """
    tiles = bbox_to_tile_range(config.BBOX, config.TILE_ZOOM)
    all_ids: set[str] = set()

    async def process_tile(x: int, y: int):
        data = await fetch_tile(client, config.TILE_ZOOM, x, y)
        if data:
            ids = decode_parcel_ids(data)
            all_ids.update(ids)

    # Process tiles concurrently in batches to avoid hammering the server
    batch_size = 10
    for i in range(0, len(tiles), batch_size):
        batch = tiles[i : i + batch_size]
        await asyncio.gather(*[process_tile(x, y) for x, y in batch])

    print(f"[tiles] Found {len(all_ids)} unique parcel IDs across {len(tiles)} tiles")
    return list(all_ids)

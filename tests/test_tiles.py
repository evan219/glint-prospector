"""
Unit tests for tiles.py — tile coordinate math and parcel ID decoding.
No network calls; all tests are deterministic.
"""
import pytest
from tiles import lat_lon_to_tile, bbox_to_tile_range


class TestLatLonToTile:
    """Verify the slippy-map tile formula against known values."""

    def test_new_york_zoom13(self):
        # 42°N, -78°W, z=13 → verified by running the formula directly
        z, x, y = lat_lon_to_tile(42.0, -78.0, 13)
        assert z == 13
        assert x == 2321
        assert y == 3041

    def test_antimeridian_east(self):
        # 0°N, 180°E — eastern edge of the map
        z, x, y = lat_lon_to_tile(0.0, 179.9, 8)
        assert z == 8
        assert x == 255  # 2^8 - 1

    def test_origin_zoom0(self):
        # Zoom 0 — entire world is one tile
        z, x, y = lat_lon_to_tile(0.0, 0.0, 0)
        assert z == 0
        assert x == 0
        assert y == 0

    def test_returns_tuple(self):
        result = lat_lon_to_tile(42.0, -78.0, 13)
        assert isinstance(result, tuple)
        assert len(result) == 3


class TestBboxToTileRange:
    """Verify bounding box → tile set coverage."""

    BBOX_SMALL = {
        "lat_min": 42.00,
        "lat_max": 42.01,
        "lon_min": -78.01,
        "lon_max": -78.00,
    }

    def test_returns_list(self):
        tiles = bbox_to_tile_range(self.BBOX_SMALL, z=13)
        assert isinstance(tiles, list)

    def test_all_tiles_covered(self):
        # Every tile in the range must be within the expected x/y bounds
        z = 13
        tiles = bbox_to_tile_range(self.BBOX_SMALL, z=z)
        xs = [x for x, _ in tiles]
        ys = [y for _, y in tiles]
        _, x_sw, y_sw = lat_lon_to_tile(
            self.BBOX_SMALL["lat_min"], self.BBOX_SMALL["lon_min"], z
        )
        _, x_ne, y_ne = lat_lon_to_tile(
            self.BBOX_SMALL["lat_max"], self.BBOX_SMALL["lon_max"], z
        )
        assert min(xs) >= min(x_sw, x_ne)
        assert max(xs) <= max(x_sw, x_ne)
        assert min(ys) >= min(y_sw, y_ne)
        assert max(ys) <= max(y_sw, y_ne)

    def test_configured_bbox_tile_count(self):
        # The default bbox (Allegany County area) at zoom 13 should produce
        # a reasonable number of tiles — not 0, not thousands
        bbox = {
            "lat_min": 42.00,
            "lat_max": 42.30,
            "lon_min": -78.10,
            "lon_max": -77.70,
        }
        tiles = bbox_to_tile_range(bbox, z=13)
        # 0.4° lat × 0.3° lon at z=13 ≈ 25–50 tiles
        assert 10 < len(tiles) < 200, f"Unexpected tile count: {len(tiles)}"

    def test_no_duplicate_tiles(self):
        bbox = {
            "lat_min": 42.00,
            "lat_max": 42.30,
            "lon_min": -78.10,
            "lon_max": -77.70,
        }
        tiles = bbox_to_tile_range(bbox, z=13)
        assert len(tiles) == len(set(tiles))

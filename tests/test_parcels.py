"""
Unit tests for parcels.py — parcel property parsing and concurrency.
Uses httpx mock transport so no network calls are made.
"""
import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from parcels import get_parcel_properties, fetch_all_parcel_properties


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(response_map: dict) -> httpx.AsyncClient:
    """
    Build an httpx.AsyncClient backed by a mock transport.
    response_map: {url_substring: (status_code, json_body)}
    """
    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            url_str = str(request.url)
            for key, (status, body) in response_map.items():
                if key in url_str:
                    return httpx.Response(
                        status_code=status,
                        content=json.dumps(body).encode(),
                        headers={"content-type": "application/json"},
                    )
            return httpx.Response(404, content=b"{}")

    return httpx.AsyncClient(transport=MockTransport())


SAMPLE_PARCEL_API_RESPONSE = {
    "parcel_id": "USNY_12345",
    "ownership_info": "SMITH JOHN",
    "parcel_address": "123 MAIN ST",
    "mail_address": "PO BOX 1",
    "area": 101171.41,       # sq metres ≈ 25 acres
    "land_use": "Residential",
    "tot_val": 250000,
    "lat": 42.1234,
    "lon": -77.9876,
}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGetParcelProperties:

    @pytest.mark.asyncio
    async def test_happy_path(self):
        client = _make_client({
            "parcel-properties": (200, SAMPLE_PARCEL_API_RESPONSE)
        })
        result = await get_parcel_properties(client, "USNY_12345")
        assert result is not None
        assert result["parcel_id"] == "USNY_12345"
        assert result["owner_name"] == "SMITH JOHN"
        assert result["parcel_address"] == "123 MAIN ST"
        assert result["mail_address"] == "PO BOX 1"
        assert result["land_use"] == "Residential"
        assert result["assessed_value"] == 250000
        assert result["lat"] == pytest.approx(42.1234)
        assert result["lon"] == pytest.approx(-77.9876)

    @pytest.mark.asyncio
    async def test_area_converted_to_acres(self):
        # 4046.86 sq m = exactly 1 acre
        response = {**SAMPLE_PARCEL_API_RESPONSE, "area": 4046.86}
        client = _make_client({"parcel-properties": (200, response)})
        result = await get_parcel_properties(client, "USNY_12345")
        assert result["total_area_acres"] == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        client = _make_client({"parcel-properties": (500, {})})
        result = await get_parcel_properties(client, "USNY_BAD")
        assert result is None

    @pytest.mark.asyncio
    async def test_404_returns_none(self):
        client = _make_client({})  # nothing matches → 404
        result = await get_parcel_properties(client, "USNY_MISSING")
        assert result is None

    @pytest.mark.asyncio
    async def test_phase2_3_fields_initialised_to_none(self):
        client = _make_client({
            "parcel-properties": (200, SAMPLE_PARCEL_API_RESPONSE)
        })
        result = await get_parcel_properties(client, "USNY_12345")
        assert result["buildable_area_acres"] is None
        assert result["buildable_pct"] is None
        assert result["installed_capacity_kw"] is None

    @pytest.mark.asyncio
    async def test_missing_lat_lon_returns_none(self):
        response = {k: v for k, v in SAMPLE_PARCEL_API_RESPONSE.items()
                    if k not in ("lat", "lon")}
        client = _make_client({"parcel-properties": (200, response)})
        result = await get_parcel_properties(client, "USNY_12345")
        assert result["lat"] is None
        assert result["lon"] is None


class TestFetchAllParcelProperties:

    @pytest.mark.asyncio
    async def test_returns_only_successful_results(self):
        """Failed parcel IDs (404/500) are filtered from results."""
        def make_response(pid):
            if pid == "USNY_BAD":
                return (500, {})
            return (200, {**SAMPLE_PARCEL_API_RESPONSE, "parcel_id": pid})

        response_map = {}
        for pid in ["USNY_1", "USNY_2", "USNY_BAD", "USNY_3"]:
            response_map[f"id={pid}"] = make_response(pid)

        client = _make_client(response_map)
        results = await fetch_all_parcel_properties(
            client, ["USNY_1", "USNY_2", "USNY_BAD", "USNY_3"]
        )
        assert len(results) == 3
        ids = {r["parcel_id"] for r in results}
        assert "USNY_BAD" not in ids

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_list(self):
        client = _make_client({})
        results = await fetch_all_parcel_properties(client, [])
        assert results == []

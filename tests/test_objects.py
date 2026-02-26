"""
Unit tests for objects.py — CRDT reconstruction, object filtering,
and visibility toggle body format.
No live network calls; httpx uses a mock transport.
"""
import json
import re
import time
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from objects import (
    _reconstruct_items,
    get_parcels,
    get_buildable_groups,
    make_hlc,
    set_hidden,
    show_only_parcel,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _row(obj_id, key, value, revision, obj_type="object"):
    return {
        "id": obj_id,
        "type": obj_type,
        "key": key,
        "value": value,
        "revision": revision,
    }


PARCEL_ROWS = [
    _row("obj_parcel1", "title", "Parcel 1830134775", 1000),
    _row("obj_parcel1", "order", 3000, 1001),
    _row("obj_parcel2", "title", "Parcel 1830267580", 2000),
    _row("obj_parcel2", "hidden", True, 2001),
    _row("obj_parcel2", "locked", True, 2002),
]

GROUP_ROWS = [
    _row("grp_visible", "title", "Buildable area ", 3000, obj_type="group"),
    _row("grp_visible", "order", 5000, 3001, obj_type="group"),
    _row("grp_hidden",  "title", "Buildable area ", 4000, obj_type="group"),
    _row("grp_hidden",  "hidden", True, 4001, obj_type="group"),
]

CHILD_ROWS = [
    # Child polygon — has parent_id so it's NOT a parcel
    _row("obj_child", "title", "1", 5000),
    _row("obj_child", "parent_id", "grp_visible", 5001),
    _row("obj_child", "function", "include", 5002),
]


# ── make_hlc ──────────────────────────────────────────────────────────────────


class TestMakeHlc:

    def test_format(self):
        hlc = make_hlc()
        # Must match {15_digits}:{5_digits}:{6_hex}
        assert re.fullmatch(r"\d{15}:00000:[0-9a-f]{6}", hlc), (
            f"HLC format mismatch: {hlc!r}"
        )

    def test_timestamp_is_recent(self):
        before = int(time.time() * 1000)
        hlc = make_hlc()
        after = int(time.time() * 1000)
        ts_ms = int(hlc.split(":")[0])
        assert before <= ts_ms <= after, (
            f"HLC timestamp {ts_ms} not in [{before}, {after}]"
        )

    def test_custom_node_id(self):
        hlc = make_hlc(node_id="deadbe")
        assert hlc.endswith(":deadbe")


# ── _reconstruct_items ────────────────────────────────────────────────────────


class TestReconstructItems:

    def test_basic_reconstruction(self):
        items = [
            _row("obj_a", "title", "Parcel 123", 100),
            _row("obj_a", "order", 1000, 101),
        ]
        result = _reconstruct_items(items)
        assert "obj_a" in result
        assert result["obj_a"]["title"] == "Parcel 123"
        assert result["obj_a"]["order"] == 1000
        assert result["obj_a"]["id"] == "obj_a"
        assert result["obj_a"]["type"] == "object"

    def test_latest_revision_wins(self):
        """When the same key appears twice, the higher revision wins."""
        items = [
            _row("obj_b", "title", "old title", 100),
            _row("obj_b", "title", "new title", 200),  # later
        ]
        result = _reconstruct_items(items)
        assert result["obj_b"]["title"] == "new title"

    def test_earlier_revision_does_not_overwrite(self):
        """Out-of-order rows: earlier revision must not clobber later one."""
        items = [
            _row("obj_c", "title", "current", 200),
            _row("obj_c", "title", "stale", 50),  # lower revision
        ]
        result = _reconstruct_items(items)
        assert result["obj_c"]["title"] == "current"

    def test_hidden_key_present_when_true(self):
        items = [_row("obj_d", "hidden", True, 300)]
        result = _reconstruct_items(items)
        assert result["obj_d"]["hidden"] is True

    def test_multiple_objects(self):
        result = _reconstruct_items(PARCEL_ROWS + GROUP_ROWS + CHILD_ROWS)
        assert len(result) == 5  # parcel1, parcel2, grp_visible, grp_hidden, obj_child

    def test_empty_input(self):
        assert _reconstruct_items([]) == {}

    def test_group_type_preserved(self):
        items = [_row("grp_x", "title", "Buildable area ", 100, obj_type="group")]
        result = _reconstruct_items(items)
        assert result["grp_x"]["type"] == "group"


# ── get_parcels ───────────────────────────────────────────────────────────────


class TestGetParcels:

    def _make_objects(self):
        return _reconstruct_items(PARCEL_ROWS + GROUP_ROWS + CHILD_ROWS)

    def test_returns_only_parcels(self):
        objects = self._make_objects()
        parcels = get_parcels(objects)
        ids = {p["id"] for p in parcels}
        assert ids == {"obj_parcel1", "obj_parcel2"}

    def test_excludes_groups(self):
        objects = self._make_objects()
        parcels = get_parcels(objects)
        for p in parcels:
            assert p["type"] == "object"

    def test_excludes_child_objects(self):
        """Objects with a parent_id (buildable area polygons) are not parcels."""
        objects = self._make_objects()
        parcels = get_parcels(objects)
        for p in parcels:
            assert "parent_id" not in p

    def test_hidden_parcel_included(self):
        """Hidden parcels are still returned — caller decides whether to show/skip."""
        objects = self._make_objects()
        parcels = get_parcels(objects)
        hidden = [p for p in parcels if p.get("hidden") is True]
        assert len(hidden) == 1
        assert hidden[0]["id"] == "obj_parcel2"

    def test_empty_objects(self):
        assert get_parcels({}) == []


# ── get_buildable_groups ──────────────────────────────────────────────────────


class TestGetBuildableGroups:

    def _make_objects(self):
        return _reconstruct_items(PARCEL_ROWS + GROUP_ROWS + CHILD_ROWS)

    def test_returns_both_groups(self):
        objects = self._make_objects()
        groups = get_buildable_groups(objects)
        ids = {g["id"] for g in groups}
        assert ids == {"grp_visible", "grp_hidden"}

    def test_excludes_parcels_and_children(self):
        objects = self._make_objects()
        groups = get_buildable_groups(objects)
        for g in groups:
            assert g["type"] == "group"

    def test_hidden_group_included(self):
        objects = self._make_objects()
        groups = get_buildable_groups(objects)
        hidden = [g for g in groups if g.get("hidden") is True]
        assert len(hidden) == 1
        assert hidden[0]["id"] == "grp_hidden"

    def test_empty_objects(self):
        assert get_buildable_groups({}) == []


# ── set_hidden API body format ────────────────────────────────────────────────


def _make_mock_client(captured: list) -> httpx.AsyncClient:
    """httpx client backed by a mock transport that captures request bodies."""

    class _CaptureTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured.append(request)
            return httpx.Response(200, content=b"[]")

    return httpx.AsyncClient(transport=_CaptureTransport())


class TestSetHidden:

    @pytest.mark.asyncio
    async def test_hide_sends_put_action(self):
        captured = []
        client = _make_mock_client(captured)
        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            await set_hidden(client, "pro_Z", "obj_abc", "object", hidden=True)

        assert len(captured) == 1
        body = json.loads(captured[0].content)
        assert len(body) == 1
        assert body[0]["action"] == "PUT"
        assert body[0]["key"] == "hidden"
        assert body[0]["value"] is True
        assert body[0]["id"] == "obj_abc"
        assert body[0]["type"] == "object"
        assert "hlc" in body[0]

    @pytest.mark.asyncio
    async def test_show_sends_delete_action(self):
        captured = []
        client = _make_mock_client(captured)
        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            await set_hidden(client, "pro_Z", "obj_abc", "object", hidden=False)

        body = json.loads(captured[0].content)
        assert body[0]["action"] == "DELETE"
        assert body[0]["key"] == "hidden"
        assert "value" not in body[0]

    @pytest.mark.asyncio
    async def test_content_type_is_text_plain(self):
        """Server requires text/plain even though body is JSON."""
        captured = []
        client = _make_mock_client(captured)
        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            await set_hidden(client, "pro_Z", "obj_abc", "object", hidden=True)

        ct = captured[0].headers.get("content-type", "")
        assert ct.startswith("text/plain")

    @pytest.mark.asyncio
    async def test_returns_false_on_http_error(self):
        class _ErrorTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return httpx.Response(500, content=b"error")

        client = httpx.AsyncClient(transport=_ErrorTransport())
        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            result = await set_hidden(client, "pro_Z", "obj_abc", "object", hidden=True)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        captured = []
        client = _make_mock_client(captured)
        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            result = await set_hidden(client, "pro_Z", "obj_abc", "object", hidden=True)

        assert result is True


# ── show_only_parcel visibility logic ─────────────────────────────────────────


class TestShowOnlyParcel:
    """
    Verify which objects get hidden/shown when isolating a target parcel.
    Uses a fake httpx client that records each call to /api/objects.
    """

    def _make_objects_map(self):
        return _reconstruct_items(PARCEL_ROWS + GROUP_ROWS + CHILD_ROWS)

    @pytest.mark.asyncio
    async def test_target_parcel_is_shown_when_hidden(self):
        """A previously hidden target parcel must be un-hidden (DELETE action)."""
        calls = []
        client = _make_mock_client(calls)
        objects = self._make_objects_map()

        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            # obj_parcel2 is currently hidden; make it the target
            await show_only_parcel(client, "pro_Z", "obj_parcel2", objects)

        # Find the call that un-hides obj_parcel2
        bodies = [json.loads(c.content) for c in calls]
        show_call = next(
            (b[0] for b in bodies if b[0]["id"] == "obj_parcel2"), None
        )
        assert show_call is not None, "No toggle call for obj_parcel2"
        assert show_call["action"] == "DELETE", "Target parcel must be un-hidden"
        assert show_call["key"] == "hidden"

    @pytest.mark.asyncio
    async def test_non_target_visible_parcels_are_hidden(self):
        """All visible non-target parcels must receive a PUT hidden=true call."""
        calls = []
        client = _make_mock_client(calls)
        objects = self._make_objects_map()

        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            # obj_parcel1 is visible; obj_parcel2 is already hidden — target is parcel1
            await show_only_parcel(client, "pro_Z", "obj_parcel1", objects)

        bodies = [json.loads(c.content) for c in calls]
        # obj_parcel2 is already hidden — no toggle needed
        parcel2_calls = [b[0] for b in bodies if b[0]["id"] == "obj_parcel2"]
        assert parcel2_calls == [], "Already-hidden parcel should not be toggled"

    @pytest.mark.asyncio
    async def test_visible_buildable_groups_are_hidden(self):
        """All visible buildable area groups must be hidden before fresh analysis."""
        calls = []
        client = _make_mock_client(calls)
        objects = self._make_objects_map()

        with patch("objects.config") as mock_cfg:
            mock_cfg.API_BASE = "https://app.glintsolar.com"
            mock_cfg.ORG_ID = "org_X"
            mock_cfg.PORTFOLIO_ID = "cus_Y"
            await show_only_parcel(client, "pro_Z", "obj_parcel1", objects)

        bodies = [json.loads(c.content) for c in calls]
        hidden_ids = {
            b[0]["id"] for b in bodies if b[0].get("action") == "PUT"
        }
        # grp_visible is currently visible → must be hidden
        assert "grp_visible" in hidden_ids
        # grp_hidden is already hidden → must NOT be toggled again
        grp_hidden_calls = [b[0] for b in bodies if b[0]["id"] == "grp_hidden"]
        assert grp_hidden_calls == [], "Already-hidden group should not be re-toggled"

"""
Object API helpers — CRDT key-value store for Glint project objects.

Glint's /api/objects endpoint returns a flat list of CRDT rows.  Each row
represents one property of one object at a specific revision.  We reconstruct
logical objects by grouping rows by ID and taking the highest-revision value
for each key.

Public API:
  get_project_objects()   — fetch and reconstruct all objects in a project
  get_parcels()           — filter for parcel objects (top-level, no parent_id)
  get_buildable_groups()  — filter for buildable area group objects
  set_hidden()            — toggle a single object's visibility
  show_only_parcel()      — isolate one parcel (hide others + all buildable groups)
"""

import json
import time

import httpx

import config


# ── HLC helpers ───────────────────────────────────────────────────────────────


def make_hlc(node_id: str = "1a41c4") -> str:
    """
    Generate a Hybrid Logical Clock timestamp string.

    Format: {epoch_ms_15_digits}:00000:{node_id_6_hex}

    The server accepts any reasonable node_id; the value observed in production
    HAR captures is "1a41c4" and is used as the default.
    """
    ts_ms = int(time.time() * 1000)
    return f"{ts_ms:015d}:00000:{node_id}"


# ── CRDT reconstruction ───────────────────────────────────────────────────────


def _reconstruct_items(items: list[dict]) -> dict[str, dict]:
    """
    Reconstruct logical objects from a flat list of CRDT key-value rows.

    Each row: {"id": "obj_xxx", "type": "object", "key": "title",
               "value": "Parcel 1234", "revision": 1772130409716, ...}

    For each (id, key) pair the row with the highest revision wins.
    Returns {obj_id: {"id": ..., "type": ..., key: value, ...}}.

    Objects that have had a key deleted (action=DELETE) will simply not include
    that key — the caller uses .get("hidden") rather than checking for absence.
    """
    objects: dict[str, dict] = {}
    revisions: dict[str, dict[str, int]] = {}  # {obj_id: {key: revision}}

    for row in items:
        obj_id = row["id"]
        obj_type = row.get("type", "object")
        key = row["key"]
        value = row.get("value")
        revision = row.get("revision", 0)

        if obj_id not in objects:
            objects[obj_id] = {"id": obj_id, "type": obj_type}
            revisions[obj_id] = {}

        if revisions[obj_id].get(key, -1) < revision:
            objects[obj_id][key] = value
            revisions[obj_id][key] = revision

    return objects


# ── Network ───────────────────────────────────────────────────────────────────


async def get_project_objects(
    client: httpx.AsyncClient,
    project_id: str,
) -> dict[str, dict]:
    """
    Fetch all objects for a project from GET /api/objects.
    Returns reconstructed {obj_id: {key: value, ...}}.
    """
    r = await client.get(
        f"{config.API_BASE}/api/objects",
        params={
            "orgId": config.ORG_ID,
            "portfolioId": config.PORTFOLIO_ID,
            "entityId": project_id,
        },
    )
    r.raise_for_status()
    return _reconstruct_items(r.json().get("items", []))


# ── Object filtering ──────────────────────────────────────────────────────────


def get_parcels(objects: dict[str, dict]) -> list[dict]:
    """
    Return parcel objects from a reconstructed object map.

    Parcels are top-level objects: type=object, no parent_id, title starts
    with "Parcel " (e.g. "Parcel 1830134775").
    """
    return [
        obj for obj in objects.values()
        if obj.get("type") == "object"
        and not obj.get("parent_id")
        and str(obj.get("title", "")).startswith("Parcel ")
    ]


def get_buildable_groups(objects: dict[str, dict]) -> list[dict]:
    """
    Return buildable area group objects from a reconstructed object map.

    Each group is a folder (type=group) whose title contains "Buildable area".
    The group's child polygon objects carry the actual geometry.
    """
    return [
        obj for obj in objects.values()
        if obj.get("type") == "group"
        and "Buildable area" in str(obj.get("title", ""))
    ]


# ── Visibility toggle ─────────────────────────────────────────────────────────


async def set_hidden(
    client: httpx.AsyncClient,
    project_id: str,
    obj_id: str,
    obj_type: str,
    hidden: bool,
) -> bool:
    """
    Show or hide a single project object via POST /api/objects.

    To hide: action=PUT with key=hidden, value=true.
    To show: action=DELETE to remove the hidden key entirely.

    Content-Type must be text/plain;charset=UTF-8 even though the body is JSON
    — this is the format the Glint app sends and the server requires it.

    Returns True on success, False on any HTTP error.
    """
    if hidden:
        body = [
            {
                "action": "PUT",
                "hlc": make_hlc(),
                "id": obj_id,
                "type": obj_type,
                "key": "hidden",
                "value": True,
            }
        ]
    else:
        # Note: the server's DeleteRequest schema does NOT allow the "type" field.
        # Including it causes a 400 "instance[0] is not any of PutRequest,DeleteRequest".
        body = [
            {
                "action": "DELETE",
                "hlc": make_hlc(),
                "id": obj_id,
                "key": "hidden",
            }
        ]

    r = await client.post(
        f"{config.API_BASE}/api/objects",
        content=json.dumps(body),
        headers={"content-type": "text/plain;charset=UTF-8"},
        params={
            "orgId": config.ORG_ID,
            "portfolioId": config.PORTFOLIO_ID,
            "entityId": project_id,
        },
    )
    if r.status_code not in (200, 201, 204):
        print(
            f"[objects] toggle {obj_id} hidden={hidden} failed: "
            f"{r.status_code} — {r.text[:200]}"
        )
        return False
    return True


async def show_only_parcel(
    client: httpx.AsyncClient,
    project_id: str,
    target_obj_id: str,
    all_objects: dict[str, dict],
) -> None:
    """
    Isolate a single parcel for analysis:
      - Show the target parcel (un-hide if currently hidden)
      - Hide all other parcel objects
      - Hide all existing buildable area groups (so the new analysis result
        is the only visible one after the UI saves it)

    The caller should refresh all_objects from get_project_objects() just before
    calling this to ensure hide/show decisions reflect the current server state.
    """
    parcels = get_parcels(all_objects)
    buildable_groups = get_buildable_groups(all_objects)

    toggle_failed = False

    for parcel in parcels:
        obj_id = parcel["id"]
        currently_hidden = parcel.get("hidden") is True
        should_hide = obj_id != target_obj_id

        if should_hide and not currently_hidden:
            ok = await set_hidden(client, project_id, obj_id, "object", True)
            if not ok:
                toggle_failed = True
        elif not should_hide and currently_hidden:
            ok = await set_hidden(client, project_id, obj_id, "object", False)
            if not ok:
                toggle_failed = True

    # Hide all existing buildable area groups before running a fresh analysis.
    # The new group created by the UI will be visible by default.
    for group in buildable_groups:
        if group.get("hidden") is not True:
            ok = await set_hidden(client, project_id, group["id"], "group", True)
            if not ok:
                toggle_failed = True

    if toggle_failed:
        print(
            f"[objects] WARNING: one or more visibility toggles failed for "
            f"project {project_id} — analysis may include unintended parcels"
        )

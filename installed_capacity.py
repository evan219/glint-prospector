"""
Phase 3: Installed Capacity (kW) — browser-use vision flow

Glint Solar computes installed capacity client-side (pvSegments bundle);
the value is never returned in an API response. We must drive the browser.

Two entry points:

get_installed_capacity(context, parcel)
    Single-parcel flow (original MVP).  Navigates to the project page,
    clicks "New Analysis", reads kW.  Assumes buildable area already exists
    in the project.  Uses Playwright DOM selectors from config.

get_all_installed_capacities(storage_state, client, parcels)
    Multi-parcel flow using browser-use vision agent.  For each parcel:
      1. Isolate the parcel via the objects API (hide others + old groups)
      2. Launch a browser-use agent that:
           a. Navigates to the project page
           b. Clicks the parcel row in the sidebar
           c. Clicks "Run Buildable Area" and waits for completion
           d. Clicks "New Analysis" and waits for kW
           e. Returns structured output: {installed_capacity_kw, buildable_area_acres}
      Concurrently, runs buildable-area-async via the API using the parcel's
      stored geometry to compute buildable_area_acres from the S3 result
      (used as fallback / cross-check against the vision-extracted value).

Required config for single-parcel:
    config.PROJECT_URL      — URL of the Glint project page
    config.SEL_NEW_ANALYSIS — "New Analysis" button selector
    config.SEL_CAPACITY_KW  — DOM element containing the kW number

Additional config for multi-parcel:
    config.PROJECT_ID       — project ID (auto-derived from PROJECT_URL)
    BROWSER_USE_API_KEY     — set in .env; used by ChatBrowserUse()
"""
import asyncio
import json
import re
import tempfile
from pathlib import Path

import httpx
from playwright.async_api import BrowserContext
from pydantic import BaseModel

import config
from buildable_area import post_buildable_area, poll_s3_result, calculate_buildable_acres


# ── Shared sidebar/map selectors (hardcoded — not user-configurable) ──────────

_SEL_SIDEBAR_COLLAPSE = (
    "#root > div > div > div._container_5gf63_1 > nav > "
    "div._expandButton_5gf63_35 > button"
)
_SEL_MAP_CONTAINER = "#root > div > div > div.MapContainer__Container-dXAjZF.hVPsZZ"


# ── Single-parcel entry point (original MVP) ──────────────────────────────────


async def get_installed_capacity(
    context: BrowserContext,
    parcel: dict,
) -> float | None:
    """
    Phase 3 flow for a single parcel.

    Uses parcel["project_url"] if present, otherwise config.PROJECT_URL.
    Navigates to the project page, clicks "New Analysis", waits for the
    capacity number to be fully populated, screenshots the result, then
    returns the kW value.

    Returns the installed capacity in kW, or None on any error.
    """
    parcel_id = parcel["parcel_id"]
    project_url = parcel.get("project_url") or config.PROJECT_URL

    screenshot_dir = Path(config.SCREENSHOT_DIR)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    unresolved = [
        name
        for name, val in [
            ("PROJECT_URL", project_url),
            ("SEL_NEW_ANALYSIS", config.SEL_NEW_ANALYSIS),
            ("SEL_CAPACITY_KW", config.SEL_CAPACITY_KW),
        ]
        if not val or val == "TODO"
    ]
    if unresolved:
        print(
            f"[capacity] Skipping {parcel_id} — unresolved config: "
            + ", ".join(unresolved)
        )
        return None

    page = await context.new_page()
    try:
        print(f"[capacity] {parcel_id} → {project_url}")
        await page.goto(project_url)
        await page.wait_for_load_state("networkidle")
        await page.screenshot(
            path=str(screenshot_dir / f"{parcel_id}_01_project.png")
        )

        print(f"[capacity] {parcel_id}: clicking New Analysis…")
        await page.wait_for_selector(config.SEL_NEW_ANALYSIS, timeout=30_000)
        await page.click(config.SEL_NEW_ANALYSIS)
        await page.screenshot(
            path=str(screenshot_dir / f"{parcel_id}_02_modal.png")
        )

        print(f"[capacity] {parcel_id}: waiting for capacity result…")
        await page.wait_for_selector(config.SEL_CAPACITY_KW, timeout=120_000)
        try:
            await page.wait_for_function(
                "(sel) => { const el = document.querySelector(sel); "
                "const t = el?.textContent?.trim(); "
                "if (!t) return false; "
                "const n = parseFloat(t.replace(/,/g, '')); "
                "return !isNaN(n) && n > 0; }",
                arg=config.SEL_CAPACITY_KW,
                timeout=30_000,
            )
        except Exception:
            print(
                f"[capacity] {parcel_id}: no non-zero value after 30s — "
                "reading whatever is there"
            )

        try:
            await page.click(_SEL_SIDEBAR_COLLAPSE, timeout=3_000)
            await page.wait_for_timeout(400)
        except Exception:
            pass
        try:
            await page.locator(_SEL_MAP_CONTAINER).screenshot(
                path=str(screenshot_dir / f"{parcel_id}_03_result.png")
            )
        except Exception:
            await page.screenshot(
                path=str(screenshot_dir / f"{parcel_id}_03_result.png")
            )

        kw_text = await page.text_content(config.SEL_CAPACITY_KW)
        if not kw_text:
            raise ValueError("SEL_CAPACITY_KW matched an element with no text content")
        kw = float(kw_text.replace(",", "").replace("kW", "").strip())
        print(f"[capacity] {parcel_id}: {kw} kW")
        return kw

    except Exception as exc:
        print(f"[capacity] ERROR for {parcel_id}: {exc}")
        await page.screenshot(
            path=str(screenshot_dir / f"{parcel_id}_error.png")
        )
        return None

    finally:
        await page.close()


# ── kW helper ─────────────────────────────────────────────────────────────────


async def _read_kw(page, parcel_id: str, screenshot_dir: Path) -> float | None:
    """
    Open the New Analysis modal, click Analyse to trigger the computation,
    wait for the kW result, and return it.

    The "Analyse" button in the modal runs buildable area + kW from scratch for
    whatever parcel is currently visible — no pre-saved buildable area needed.
    """
    try:
        await page.wait_for_selector(config.SEL_NEW_ANALYSIS, timeout=30_000)
        await page.click(config.SEL_NEW_ANALYSIS)
        await page.screenshot(
            path=str(screenshot_dir / f"{parcel_id}_02_modal.png")
        )

        # Click "Analyse" to trigger the analysis.  The modal shows this button
        # whether or not a prior result exists; clicking it always runs fresh.
        await page.get_by_role("button", name="Analyse").click(timeout=15_000)
        print(f"[capacity] {parcel_id}: analysis triggered")

        # kW takes up to ~2 min (includes buildable area computation).
        await page.wait_for_selector(config.SEL_CAPACITY_KW, timeout=120_000)
        try:
            await page.wait_for_function(
                "(sel) => { const el = document.querySelector(sel); "
                "const t = el?.textContent?.trim(); "
                "if (!t) return false; "
                "const n = parseFloat(t.replace(/,/g, '')); "
                "return !isNaN(n) && n > 0; }",
                arg=config.SEL_CAPACITY_KW,
                timeout=120_000,
            )
        except Exception:
            print(
                f"[capacity] {parcel_id}: no non-zero value after 120s — "
                "reading whatever is there"
            )

        try:
            await page.click(_SEL_SIDEBAR_COLLAPSE, timeout=3_000)
            await page.wait_for_timeout(400)
        except Exception:
            pass
        try:
            await page.locator(_SEL_MAP_CONTAINER).screenshot(
                path=str(screenshot_dir / f"{parcel_id}_03_result.png")
            )
        except Exception:
            await page.screenshot(
                path=str(screenshot_dir / f"{parcel_id}_03_result.png")
            )

        kw_text = await page.text_content(config.SEL_CAPACITY_KW)
        if not kw_text:
            raise ValueError("SEL_CAPACITY_KW element has no text content")
        kw = float(kw_text.replace(",", "").replace("kW", "").strip())
        print(f"[capacity] {parcel_id}: {kw} kW")
        return kw

    except Exception as exc:
        print(f"[capacity] {parcel_id}: analysis failed — {exc}")
        await page.screenshot(
            path=str(screenshot_dir / f"{parcel_id}_error.png")
        )
        return None


# ── Multi-parcel entry point (browser-use vision) ────────────────────────────


class _ParcelResult(BaseModel):
    """Structured output returned by the browser-use agent for one parcel."""
    installed_capacity_kw: float | None = None
    buildable_area_acres: float | None = None


async def _run_agent_for_parcel(
    storage_state: dict,
    parcel_id: str,
    screenshot_dir: Path,
) -> _ParcelResult:
    """
    Launch a browser-use vision agent to:
      1. Navigate to the Glint project page
      2. Click the parcel row in the left sidebar
      3. Click "Run Buildable Area" and wait for completion
      4. Click "New Analysis" and wait for the kW value
      5. Return structured output

    Uses ChatBrowserUse() which reads BROWSER_USE_API_KEY from the environment.
    """
    from browser_use import Agent, Browser
    from browser_use import ChatBrowserUse

    # browser-use requires storage_state as a file path (not dict).
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        json.dump(storage_state, tmp)
        state_path = tmp.name

    browser = Browser(
        storage_state=state_path,
        headless=True,
        keep_alive=False,
    )

    task = f"""
You are automating a solar prospecting workflow in the Glint Solar web app.
The project page already has only one parcel visible: "Parcel {parcel_id}".

Complete these steps in order:

1. Navigate to: {config.PROJECT_URL}
   Wait for the page to fully load (the Objects tab in the left sidebar is visible).

2. In the left sidebar Objects list, find the row labelled "Parcel {parcel_id}".
   RIGHT-CLICK on that row (not a regular click — use right-click to open the
   context menu). A context menu should appear with options like "Run Buildable
   Area", "Edit", "Delete", etc.

3. In the context menu, click "Run Buildable Area".
   Wait for the buildable area computation to finish — a progress indicator will
   appear then disappear. This can take up to 2 minutes.
   Do not click anything else while it is running.

4. Once buildable area is complete, note the buildable area value in acres if
   it is displayed anywhere on screen (it may appear as "X.X ac" or similar).

5. Find the "New Analysis" button (in the top area of the sidebar or project
   header) and click it. A modal or panel will open.

6. In the modal, wait for the installed capacity number in kilowatts (kW) to
   finish loading (it starts at 0 and increases to the final value).
   Read the final kW value.

Return:
- installed_capacity_kw: the final kW number (float, no units)
- buildable_area_acres: the buildable area in acres (float), or null if not shown
"""

    agent = Agent(
        task=task,
        llm=ChatBrowserUse(),
        browser=browser,
        output_model_schema=_ParcelResult,
    )

    try:
        history = await agent.run(max_steps=60)
        Path(state_path).unlink(missing_ok=True)
        result = history.get_structured_output(_ParcelResult)
        if result is None:
            # Fall back to parsing the final text result
            final_text = history.final_result() or ""
            result = _ParcelResult()
            kw_match = re.search(r"(\d[\d,]*\.?\d*)\s*kW", final_text, re.IGNORECASE)
            if kw_match:
                result.installed_capacity_kw = float(kw_match.group(1).replace(",", ""))
        if isinstance(result, _ParcelResult):
            print(
                f"[capacity] {parcel_id}: agent → "
                f"{result.installed_capacity_kw} kW, "
                f"{result.buildable_area_acres} acres"
            )
            return result
        print(f"[capacity] {parcel_id}: agent returned unexpected type: {type(result)}")
        return _ParcelResult()
    except Exception as exc:
        Path(state_path).unlink(missing_ok=True)
        print(f"[capacity] {parcel_id}: agent error — {exc}")
        return _ParcelResult()


async def get_all_installed_capacities(
    storage_state: dict,
    client: httpx.AsyncClient,
    parcels: list[dict],
) -> None:
    """
    Multi-parcel Phase 3 (browser-use vision).  For each parcel:
      - Toggle visibility (show only this parcel, hide others + old groups)
      - Launch a browser-use agent to run buildable area + New Analysis; read kW
      - Concurrently, run buildable-area-async via the API for a precise acres
        value from the S3 result (used if the agent doesn't extract it).

    Mutates each parcel dict in-place (buildable_area_acres, buildable_pct,
    installed_capacity_kw).  Parcels not found in the project object list are
    skipped with a log message.

    Requires config: PROJECT_ID, PROJECT_URL.
    BROWSER_USE_API_KEY must be set in the environment.
    """
    from objects import get_project_objects, get_parcels, show_only_parcel

    unresolved = [
        name
        for name, val in [
            ("PROJECT_ID", config.PROJECT_ID),
            ("PROJECT_URL", config.PROJECT_URL),
        ]
        if not val or val == "TODO"
    ]
    if unresolved:
        print(
            "[capacity] Skipping all parcels — unresolved config: "
            + ", ".join(unresolved)
        )
        return

    screenshot_dir = Path(config.SCREENSHOT_DIR)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # Build parcel_id → object mapping from the project's CRDT store.
    all_objects = await get_project_objects(client, config.PROJECT_ID)
    project_parcels = get_parcels(all_objects)
    obj_by_parcel_id = {
        obj["title"][len("Parcel "):]: obj
        for obj in project_parcels
        if obj.get("title", "").startswith("Parcel ")
    }

    # ── Phase A: Fire all buildable-area-async API calls in parallel ─────────
    # These are independent of each other and of the browser flow — each just
    # POSTs geometry and polls S3.  Start them all now so S3 results are ready
    # (or nearly so) by the time the sequential browser loop reaches each parcel.

    async def _api_acres_for(parcel_id: str) -> float | None:
        obj = obj_by_parcel_id.get(parcel_id)
        if not obj:
            return None
        geom = obj.get("geom")
        if not geom:
            print(f"[capacity] {parcel_id}: no geometry in objects store — skipping acres")
            return None
        request_id = await post_buildable_area(client, geom, parcel_id)
        if not request_id:
            return None
        s3_result = await poll_s3_result(request_id)
        if not s3_result:
            return None
        return calculate_buildable_acres(s3_result)

    api_tasks = {
        str(p["parcel_id"]): asyncio.create_task(_api_acres_for(str(p["parcel_id"])))
        for p in parcels
    }
    print(f"[capacity] Fired {len(api_tasks)} parallel buildable-area API jobs")

    # ── Phase B: Sequential browser loop (visibility isolation required) ─────
    # Each iteration: isolate parcel → browser-use agent → collect results.
    # The API tasks run in the background; we await each one's result only after
    # its browser agent completes (it's almost certainly done by then).

    for i, parcel in enumerate(parcels, 1):
        parcel_id = str(parcel["parcel_id"])
        print(f"[capacity] [{i}/{len(parcels)}] {parcel_id}")

        obj = obj_by_parcel_id.get(parcel_id)
        if not obj:
            print(
                f"[capacity] {parcel_id}: not found in project objects — "
                "add it to the project in the Glint UI and re-run"
            )
            continue

        # Refresh object state so hide/show decisions are current.
        all_objects = await get_project_objects(client, config.PROJECT_ID)
        await show_only_parcel(client, config.PROJECT_ID, obj["id"], all_objects)

        agent_result = await _run_agent_for_parcel(storage_state, parcel_id, screenshot_dir)

        # Collect the pre-fired API result (prefer over agent value — precise UTM).
        api_acres = await api_tasks[parcel_id]
        buildable_acres = api_acres if api_acres is not None else agent_result.buildable_area_acres
        total_acres = parcel.get("total_area_acres") or 0

        parcel["buildable_area_acres"] = buildable_acres
        parcel["buildable_pct"] = (
            round(buildable_acres / total_acres * 100, 1)
            if buildable_acres is not None and total_acres
            else None
        )
        parcel["installed_capacity_kw"] = agent_result.installed_capacity_kw

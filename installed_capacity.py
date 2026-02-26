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
from playwright_flow import _parse_mwp_or_kw, _parse_bare_float


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
        kw = _parse_mwp_or_kw(kw_text) or _parse_bare_float(kw_text)
        if kw is None:
            raise ValueError(f"Could not parse kW from: {kw_text!r}")
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
        kw = _parse_mwp_or_kw(kw_text) or _parse_bare_float(kw_text)
        if kw is None:
            raise ValueError(f"Could not parse kW from: {kw_text!r}")
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


async def _run_playwright_for_parcel(
    storage_state: dict,
    parcel_id: str,
    project_url: str,
    screenshot_dir: Path,
) -> _ParcelResult:
    """
    Pure Playwright implementation replacing the browser-use vision agent.

    Steps:
      1. Launch Playwright browser using storage_state
      2. Navigate to project_url
      3. open_buildable_area_panel → right-click parcel → Buildable Area panel
      4. run_buildable_area_and_copy → Run → extract acres → Copy to project
      5. click_new_analysis_and_read_kw → New Analysis → read kW
      6. Screenshot and return _ParcelResult
    """
    from playwright.async_api import async_playwright
    from playwright_flow import (
        open_buildable_area_panel,
        run_buildable_area_and_copy,
        click_new_analysis_and_read_kw,
    )

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(storage_state=storage_state)
            page = await ctx.new_page()
            try:
                await page.goto(project_url)
                await page.wait_for_load_state("networkidle")

                await open_buildable_area_panel(page, parcel_id)
                acres = await run_buildable_area_and_copy(page)
                kw = await click_new_analysis_and_read_kw(page)

                await page.screenshot(
                    path=str(screenshot_dir / f"{parcel_id}_result.png")
                )
                print(
                    f"[capacity] {parcel_id}: playwright → {kw} kW, {acres} acres"
                )
                return _ParcelResult(installed_capacity_kw=kw, buildable_area_acres=acres)
            finally:
                await page.close()
                await browser.close()
    except Exception as exc:
        print(f"[capacity] {parcel_id}: playwright error — {exc}")
        return _ParcelResult()


async def _run_agent_for_parcel_legacy(
    storage_state: dict,
    parcel_id: str,
    project_url: str,
    screenshot_dir: Path,
) -> _ParcelResult:
    """
    Legacy browser-use vision agent (kept for fallback testing).
    Use _run_playwright_for_parcel for the main flow.

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

    playwright_log = str(Path(config.SCREENSHOT_DIR) / f"{parcel_id}_playwright_log.md")
    task = f"""
You are automating a solar prospecting workflow in the Glint Solar web app.
This project has exactly ONE parcel: "Parcel {parcel_id}". No visibility toggling needed.

Complete ALL steps in order:

1. Navigate to: {project_url}
   Wait for the Objects tab in the left sidebar to be visible and loaded.

2. In the left sidebar Objects list, find the row labelled "Parcel {parcel_id}".
   RIGHT-CLICK that row to open the context menu.

3. In the context menu, click "Buildable Area".
   A settings panel opens — click the "Run Buildable Area" button inside it.
   Wait for the "Calculating..." progress bar to finish (up to 2 minutes).

4. REQUIRED: After computation finishes, a floating panel shows "N objects selected,
   X.XX ac" and a "Copy to project" button. Note the acres value, then click
   "Copy to project". Wait for the panel to close.

5. Find the "New Analysis" button (top of sidebar) and click it.
   A panel opens on the right showing "Installed capacity: X.XX MWp".
   Wait until it shows a non-zero value.
   Convert to kW: multiply MWp × 1000.

IMPORTANT — PLAYWRIGHT DOCUMENTATION:
As you work, write a file called "{playwright_log}" that documents every UI
element you interact with so this workflow can be replicated in Playwright
without a vision AI. For each action, record:
  - The step number and description
  - How you located the element (CSS selector, role+name, text content, XPath)
  - The exact selector string you used (most stable form you can determine)
  - Whether it was a click, right-click, wait, or read
  - Any timing notes (e.g. "waited 10s for progress bar to clear")

Format each entry as:
### Step N: <description>
- **Located by**: <method>
- **Selector**: `<selector>`
- **Action**: <click|right_click|wait|read_text>
- **Notes**: <timing, fallbacks, observations>

Return:
- installed_capacity_kw: the final value in kW as a float (MWp × 1000)
- buildable_area_acres: the acres value from step 4 (float)
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
    Multi-parcel Phase 3 (pure Playwright).

    Each parcel must have 'project_id' and 'project_url' set (populated by
    main.py Phase 1 from PROJECT_URL_1 .. PROJECT_URL_N).  Each project
    contains exactly one parcel — no visibility toggling needed.

    For each parcel:
      - Fetches parcel geometry via the objects API (for the API buildable area job)
      - Fires a buildable-area-async API call in parallel (precise S3 acres)
      - Runs a pure Playwright flow: right-click → Buildable Area → Run →
        Copy to project → New Analysis → read kW

    Mutates each parcel dict in-place.
    """
    from objects import get_project_objects, get_parcels

    if not parcels:
        print("[capacity] No parcels to process.")
        return

    screenshot_dir = Path(config.SCREENSHOT_DIR)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase A: Fetch geometry + fire all buildable-area-async API calls ─────
    # Each parcel is in its own project; look up objects to find geometry.
    # All API jobs fire in parallel so S3 results are ready (or nearly so)
    # by the time the sequential browser loop reaches each parcel.

    async def _api_acres_for(parcel: dict) -> float | None:
        parcel_id = str(parcel["parcel_id"])
        project_id = parcel.get("project_id")
        if not project_id or project_id == "TODO":
            print(f"[capacity] {parcel_id}: no project_id — skipping API acres")
            return None
        try:
            all_objects = await get_project_objects(client, project_id)
        except Exception as exc:
            print(f"[capacity] {parcel_id}: failed to fetch objects — {exc}")
            return None
        project_parcels = get_parcels(all_objects)
        obj = next(
            (o for o in project_parcels
             if o.get("title", "").strip() == f"Parcel {parcel_id}"),
            None,
        )
        if not obj:
            print(f"[capacity] {parcel_id}: not found in project objects")
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
        str(p["parcel_id"]): asyncio.create_task(_api_acres_for(p))
        for p in parcels
    }
    print(f"[capacity] Fired {len(api_tasks)} parallel buildable-area API jobs")

    # ── Phase B: Sequential browser loop ─────────────────────────────────────
    # One parcel per project — no visibility toggling needed.
    # Browser agents run sequentially to avoid resource contention.

    for i, parcel in enumerate(parcels, 1):
        parcel_id = str(parcel["parcel_id"])
        project_url = parcel.get("project_url") or config.PROJECT_URL
        print(f"[capacity] [{i}/{len(parcels)}] {parcel_id}  ({project_url.split('/')[-1].split('?')[0]})")

        result = await _run_playwright_for_parcel(
            storage_state, parcel_id, project_url, screenshot_dir
        )

        kw = result.installed_capacity_kw

        # Collect the pre-fired API result (prefer over Playwright value — precise UTM).
        api_acres = await api_tasks[parcel_id]
        buildable_acres = api_acres if api_acres is not None else result.buildable_area_acres
        total_acres = parcel.get("total_area_acres") or 0

        parcel["buildable_area_acres"] = buildable_acres
        parcel["buildable_pct"] = (
            round(buildable_acres / total_acres * 100, 1)
            if buildable_acres is not None and total_acres
            else None
        )
        parcel["installed_capacity_kw"] = kw
        parcel["kw_agent_reported"] = kw      # kept for CSV compatibility
        parcel["kw_verified"] = kw            # single Playwright source — no dual-read
        parcel["kw_match"] = kw is not None   # True when kW was successfully read

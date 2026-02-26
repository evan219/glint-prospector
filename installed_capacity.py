"""
Phase 3: Installed Capacity (kW) — Playwright DOM flow

HAR FINDING (Feb 2026): Installed capacity is computed entirely client-side.
After "New Analysis" is clicked, the JS bundles pvSegments-yd5TuR0N.js and
createSolarPanels-CU3YJTdo.js tile solar panels onto the buildable polygon and
derive DC/AC capacity locally. No installed_capacity field ever appears in any
API response — this value only exists in the rendered DOM.

Required Playwright flow:
  1. Navigate to the project (projectId stored on the parcel dict)
  2. Open the "New Analysis" modal
  3. Select the configuration profile (panel model, mount type, row spacing)
  4. Submit → wait for panel layout to fully render
  5. Read the installed capacity kW value from the DOM
  6. Capture screenshot for audit trail

TODO before this runs end-to-end:
  - Confirm INSTALLED_CAPACITY_SELECTOR in config.py matches the actual DOM
    (right-click the kW value in DevTools → Copy → Copy selector)
  - Confirm the "New Analysis" button selector below
  - Verify what project navigation URL pattern looks like
"""
import os
import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext
import config


# ── Selectors (update if the app changes) ────────────────────────────────────
NEW_ANALYSIS_BUTTON = "button:has-text('New analysis'), button:has-text('New Analysis')"
CONFIG_PROFILE_DROPDOWN = "[data-testid='config-profile-select'], select[name='configuration']"
SUBMIT_ANALYSIS_BUTTON = "button:has-text('Run'), button[type='submit']:has-text('Analy')"
CAPACITY_SELECTOR = config.INSTALLED_CAPACITY_SELECTOR   # set in config / .env
LAYOUT_READY_INDICATOR = ".solar-panel, [data-testid='panel-layout'], canvas.panel-canvas"


async def _take_screenshot(page: Page, label: str) -> str:
    """Save a screenshot to output/screenshots/ and return the file path."""
    Path(config.SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"{config.SCREENSHOT_DIR}/{label}.png"
    await page.screenshot(path=filename, full_page=False)
    print(f"[capacity] Screenshot saved: {filename}")
    return filename


async def get_installed_capacity(
    context: BrowserContext,
    parcel: dict,
) -> float | None:
    """
    Full Phase 3 Playwright flow for a single parcel.

    Args:
        context: An authenticated Playwright BrowserContext (cookies already set).
        parcel:  Parcel dict — must contain 'parcel_id' and (after Phase 2) a
                 'project_id' key set by copy_to_project().

    Returns:
        Installed capacity in kW as a float, or None if the flow fails.
    """
    project_id = parcel.get("project_id")
    parcel_id = parcel["parcel_id"]

    if not project_id:
        print(f"[capacity] No project_id for {parcel_id} — run copy_to_project() first")
        return None

    page = await context.new_page()
    try:
        # Step 1: Navigate to project
        project_url = f"{config.API_BASE}/projects/{project_id}"
        print(f"[capacity] Navigating to project {project_id}...")
        await page.goto(project_url, wait_until="networkidle")
        await _take_screenshot(page, f"{parcel_id}_01_project_loaded")

        # Step 2: Open New Analysis modal
        print(f"[capacity] Opening New Analysis modal...")
        await page.click(NEW_ANALYSIS_BUTTON)
        await page.wait_for_selector(CONFIG_PROFILE_DROPDOWN, timeout=10_000)
        await _take_screenshot(page, f"{parcel_id}_02_new_analysis_modal")

        # Step 3: Select configuration profile
        config_name = config.DEFAULT_ANALYSIS_CONFIG_NAME
        print(f"[capacity] Selecting config profile: {config_name}")
        try:
            await page.select_option(CONFIG_PROFILE_DROPDOWN, label=config_name)
        except Exception:
            # Fallback: look for a listbox / radio option with matching text
            await page.click(f"text={config_name}")

        # Step 4: Submit
        print(f"[capacity] Submitting analysis...")
        await page.click(SUBMIT_ANALYSIS_BUTTON)

        # Step 5: Wait for panel layout to render (JS bundle runs client-side)
        # Increase timeout generously — layout computation can take 30–60 s
        print(f"[capacity] Waiting for panel layout to render...")
        await page.wait_for_selector(LAYOUT_READY_INDICATOR, timeout=90_000)
        # Extra buffer for capacity number to populate
        await asyncio.sleep(3)
        await _take_screenshot(page, f"{parcel_id}_03_layout_rendered")

        # Step 6: Extract kW value
        capacity_el = await page.query_selector(CAPACITY_SELECTOR)
        if not capacity_el:
            print(f"[capacity] Selector '{CAPACITY_SELECTOR}' not found for {parcel_id}")
            await _take_screenshot(page, f"{parcel_id}_04_selector_miss")
            return None

        raw_text = await capacity_el.inner_text()
        kw = _parse_kw(raw_text)
        print(f"[capacity] {parcel_id} → {kw} kW (raw: '{raw_text.strip()}')")
        await _take_screenshot(page, f"{parcel_id}_05_capacity_found")
        return kw

    except Exception as exc:
        print(f"[capacity] Error for {parcel_id}: {exc}")
        try:
            await _take_screenshot(page, f"{parcel_id}_ERROR")
        except Exception:
            pass
        return None

    finally:
        await page.close()


def _parse_kw(text: str) -> float | None:
    """
    Parse a kW value out of a DOM text string.
    Handles formats like: "1,234.5 kW", "1234.5kW", "1.2 MW" → converted to kW.
    """
    text = text.replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*(kW|MW|KW|mw)?", text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "kW").upper()
    if unit == "MW":
        value *= 1000
    return round(value, 2)


# ── Project creation helpers (called between Phase 2 and Phase 3) ─────────────

async def copy_to_project(
    context: BrowserContext,
    parcel: dict,
    buildable_area_geom: dict,
) -> str | None:
    """
    Copies a buildable area polygon into a new Glint project.
    Returns the new projectId (e.g. "pro_XXXX") or None on failure.

    This replicates the UI flow:
      "Copy to project" → "Create new project" → enter name → Save

    NOTE: The exact selectors below need verification against the live UI.
    Run with headed=True and watch the flow once to confirm button labels.
    """
    page = await context.new_page()
    try:
        await page.goto(config.API_BASE, wait_until="networkidle")

        project_name = f"Glint-Prospector-{parcel['parcel_id']}"

        # Click "Copy to project" from the buildable area result panel
        await page.click("button:has-text('Copy to project'), button:has-text('Copy buildable')")
        await page.wait_for_selector("text=Create new project", timeout=10_000)
        await page.click("text=Create new project")

        # Fill project name
        await page.fill("input[placeholder*='project name'], input[name='name']", project_name)
        await page.click("button:has-text('Save'), button:has-text('Create')")

        # Wait for navigation to the new project
        await page.wait_for_url(f"{config.API_BASE}/projects/**", timeout=15_000)
        project_url = page.url
        project_id = project_url.rstrip("/").split("/")[-1]
        print(f"[capacity] Created project {project_id} for parcel {parcel['parcel_id']}")
        return project_id

    except Exception as exc:
        print(f"[capacity] copy_to_project failed for {parcel['parcel_id']}: {exc}")
        return None
    finally:
        await page.close()

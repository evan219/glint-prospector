"""
Phase 3: Installed Capacity (kW)
STATUS: STUB — requires Phase 3 HAR capture to determine approach.

Two possible paths (see brief §3.1):
  A) REST API: POST to a geo-insights endpoint, poll S3 for JSON with installed_capacity_kw
  B) DOM only: Playwright navigates to project, clicks New Analysis, reads kW from DOM

Action required before implementing:
  1. Capture HAR during: Copy to project → New Analysis → wait for render → read kW
  2. Check for any POST/GET to geo-insights, analysis, or design endpoints
  3. If API: map the endpoint and add a poll_s3_result-style function here
  4. If DOM: implement the Playwright flow below
"""
import asyncio
import httpx
from playwright.async_api import Page
import config


# --- Path A: API-based (fill in after HAR capture) ---

async def get_installed_capacity_api(
    client: httpx.AsyncClient,
    parcel: dict,
) -> float | None:
    """
    TODO: Map this endpoint from the Phase 3 HAR.
    Expected: POST to geo-insights analysis endpoint → poll S3 for result JSON.
    """
    raise NotImplementedError(
        "Phase 3 API endpoint not yet mapped. Capture Phase 3 HAR first."
    )


# --- Path B: DOM/Playwright-based (fill in DOM selector after HAR capture) ---

# Placeholder selector — update after inspecting the DOM:
#   Right-click the kW value in DevTools → Copy → Copy selector
INSTALLED_CAPACITY_SELECTOR = "[data-testid='installed-capacity-kw']"


async def get_installed_capacity_playwright(
    page: Page,
    project_name: str,
) -> float | None:
    """
    TODO: Implement after confirming installed capacity is DOM-only.
    Rough flow:
      1. Navigate to the parcel's project page
      2. Click "New Analysis"
      3. Wait for solar layout to render
      4. Extract kW value from DOM element
    """
    raise NotImplementedError(
        "Phase 3 Playwright flow not yet implemented. Capture Phase 3 HAR first."
    )


# --- Dispatcher (update once path is confirmed) ---

async def get_installed_capacity(
    client: httpx.AsyncClient,
    parcel: dict,
    page=None,
) -> float | None:
    """
    Entry point for Phase 3. Switch to the confirmed path once HAR is captured.
    """
    # Uncomment the correct path after HAR analysis:
    # return await get_installed_capacity_api(client, parcel)
    # return await get_installed_capacity_playwright(page, parcel["parcel_id"])

    print(f"[capacity] Phase 3 not yet implemented for {parcel['parcel_id']} — skipping")
    return None

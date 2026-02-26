"""
Playwright-based flow functions for the Glint Solar UI.

These replace browser-use vision agents with deterministic selectors confirmed
from browser-use agent logs (output/screenshots/*_playwright_log.md).
"""
import asyncio
import re

import config


# ── kW parsing helpers ────────────────────────────────────────────────────────


def _parse_mwp_or_kw(text: str) -> float | None:
    """Parse a kW value from text like '35.00 MWp', '19,430 kWp', '35 kW'."""
    text = text.strip().replace(",", "")
    m = re.search(r"([\d.]+)\s*(MWp|kWp|MW|kW)", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    if m.group(2).upper().startswith("M"):
        val *= 1000
    return round(val, 1)


def _parse_bare_float(text: str) -> float | None:
    """Fallback: parse a bare number (no unit) as kW."""
    try:
        return float(text.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None


async def _read_kw_from_page(page) -> float | None:
    """
    Extract the installed capacity kW value from the current page state.

    Tries the configured CSS selector first, then falls back to a JS text scan
    for any leaf element whose text matches an MWp/kWp number pattern.
    """
    if config.SEL_CAPACITY_KW and config.SEL_CAPACITY_KW != "TODO":
        try:
            text = await page.text_content(config.SEL_CAPACITY_KW, timeout=5_000)
            if text:
                kw = _parse_mwp_or_kw(text)
                if kw is not None:
                    return kw
        except Exception:
            pass

    result = await page.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            if (el.children.length === 0) {
                const t = el.textContent.trim();
                if (/^[\\d,]+\\.\\d+\\s*[Mm][Ww][Pp]?$/.test(t) ||
                    /^[\\d,]+\\.\\d+\\s*[Kk][Ww][Pp]?$/.test(t)) {
                    return t;
                }
            }
        }
        return null;
    }""")
    if result:
        return _parse_mwp_or_kw(result)
    return None


# ── UI flow functions ─────────────────────────────────────────────────────────


async def open_buildable_area_panel(page, parcel_id: str) -> None:
    print(f"[playwright] {parcel_id}: waiting for sidebar…")
    await page.wait_for_selector("text=Objects", timeout=30_000)

    locator = page.locator(f'p:has-text("Parcel {parcel_id}")')
    await locator.wait_for(state="visible", timeout=10_000)
    print(f"[playwright] {parcel_id}: right-clicking parcel row…")
    await locator.dispatch_event("contextmenu", {"bubbles": True, "cancelable": True})

    btn = page.get_by_role("button", name="Buildable Area")
    await btn.wait_for(state="visible", timeout=5_000)
    print(f"[playwright] {parcel_id}: clicking Buildable Area…")
    await btn.click()

    run_btn = page.get_by_role("button", name="Run Buildable Area")
    await run_btn.wait_for(state="visible", timeout=10_000)
    print(f"[playwright] {parcel_id}: settings panel open")


async def run_buildable_area_and_copy(page) -> float | None:
    print("[playwright] clicking Run Buildable Area…")
    await page.get_by_role("button", name="Run Buildable Area").click()

    copy_locator = page.locator('button:has-text("Copy to project")')
    elapsed = 0
    poll_interval = 2
    max_wait = 120
    while elapsed < max_wait:
        if await copy_locator.is_visible():
            break
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    else:
        print("[playwright] timed out waiting for Copy to project button")
        return None

    acres_text = await page.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            if (el.children.length === 0) {
                const m = el.textContent.trim().match(/^(\\d+\\.\\d+)\\s*ac$/);
                if (m) return m[1];
            }
        }
        return null;
    }""")
    acres = float(acres_text) if acres_text else None
    print(f"[playwright] buildable area: {acres} ac")

    await page.get_by_role("button", name="Copy to project").click()

    for _ in range(5):
        if not await copy_locator.is_visible():
            break
        await asyncio.sleep(1)

    return acres


async def click_new_analysis_and_read_kw(page) -> float | None:
    print("[playwright] clicking New analysis…")
    await page.get_by_role("button", name="New analysis", exact=False).click()

    try:
        await page.wait_for_function(
            """() => {
                for (const el of document.querySelectorAll('*')) {
                    if (el.children.length === 0) {
                        const t = el.textContent.trim();
                        if (/[1-9][\\d,.]*\\s*[MmKk][Ww][Pp]?/.test(t)) return true;
                    }
                }
                return false;
            }""",
            timeout=120_000,
        )
    except Exception:
        print("[playwright] wait_for_function timed out — reading current state")

    return await _read_kw_from_page(page)

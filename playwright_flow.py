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

    Strategy 1: read the number element (SEL_CAPACITY_KW) and its parent together.
      The number element (div._number_17kug_157) holds only the numeric part, e.g.
      "15.04".  The parent (div._value_17kug_144) contains both the number and unit,
      e.g. "15.04MWp" — which _parse_mwp_or_kw can convert to kW.
    Strategy 2: JS scan for the "Installed capacity" label and walk up to its container
      to find a number+unit pair.
    """
    if config.SEL_CAPACITY_KW and config.SEL_CAPACITY_KW != "TODO":
        # Try the leaf element itself (works when element contains unit, e.g. "1,234 kW")
        try:
            text = await page.text_content(config.SEL_CAPACITY_KW, timeout=5_000)
            if text:
                kw = _parse_mwp_or_kw(text)
                if kw is not None:
                    return kw
        except Exception:
            pass

        # Try the parent element — typically has number + unit together ("15.04MWp")
        parent_sel = config.SEL_CAPACITY_KW.rsplit(" > ", 1)[0]
        try:
            text = await page.text_content(parent_sel, timeout=5_000)
            if text:
                kw = _parse_mwp_or_kw(text.strip())
                if kw is not None:
                    return kw
        except Exception:
            pass

    # JS scan: find "Installed capacity" label then walk up to find number+unit
    result = await page.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            if (el.children.length === 0 &&
                el.textContent.trim().toLowerCase() === 'installed capacity') {
                let container = el.parentElement;
                for (let i = 0; i < 8 && container; i++) {
                    const full = container.textContent.trim();
                    const m = full.match(/(\\d[\\d,.]*)\\s*(MWp|kWp|MW|kW)/i);
                    if (m) return m[0];
                    container = container.parentElement;
                }
            }
        }
        // Fallback: leaf scan for combined number+unit
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

    # Wait for the kW number element to be non-zero.
    # SEL_CAPACITY_KW points to the number-only leaf (e.g. div._number_17kug_157);
    # wait until it contains a parseable positive number.
    if config.SEL_CAPACITY_KW and config.SEL_CAPACITY_KW != "TODO":
        try:
            await page.wait_for_selector(config.SEL_CAPACITY_KW, timeout=30_000)
            await page.wait_for_function(
                "(sel) => { const el = document.querySelector(sel); "
                "const n = parseFloat((el?.textContent || '').replace(/,/g, '')); "
                "return !isNaN(n) && n > 0; }",
                arg=config.SEL_CAPACITY_KW,
                timeout=120_000,
            )
        except Exception:
            print("[playwright] SEL_CAPACITY_KW wait timed out — reading current state")
    else:
        # Fallback when selector not configured: scan leaf elements for MWp/kWp text
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

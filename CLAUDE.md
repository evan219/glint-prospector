# CLAUDE.md — Glint Solar Prospecting Agent

Developer guide for Claude Code agents working on this repo.

---

## Multi-Agent Development Workflow

All significant changes follow this three-phase pattern:

```
Drafter → Reviewer → Testing
```

1. **Drafter** — implements the change (write/edit files)
2. **Reviewer** — spawned via `Task` tool to read all changed files and return a structured `BUGS / RISKS / IMPROVEMENTS / VERDICT` report
3. **Testing** — runs `python -m pytest tests/ -v` and confirms 29 passed, 1 xfailed

If the reviewer returns `REQUEST_CHANGES`, all must-fix items are resolved before proceeding.
Never skip the testing phase — the test suite catches real bugs (e.g. the CRS reprojection
fix discovered during review).

---

## Setting Up `.env` for Testing

```bash
cp .env.example .env
```

Edit `.env` with real credentials:

```
GLINT_EMAIL=your@email.com
GLINT_PASSWORD=yourpassword
```

The `.env` file is gitignored and will never be committed.

**For Claude Code to use credentials when running `python main.py` or integration tests:**
- The file just needs to exist at the project root
- `python-dotenv` loads it automatically at import time via `load_dotenv()` in `config.py`

**Unit tests** (`python -m pytest tests/`) do NOT require real credentials —
`tests/conftest.py` injects placeholder values so config.py can be imported.

**Integration tests / end-to-end runs** require a populated `.env`.

---

## Phase 3 Selector Capture Protocol

Phase 3 (`installed_capacity.py`) is ready to run but has 5 DOM selectors and 1 URL
template that must be filled in first. All are guarded — the code safely skips parcels
and prints which config keys are missing.

### Steps to capture

1. Open a terminal and run:
   ```bash
   HEADLESS=0 python -c "
   import asyncio
   from playwright.async_api import async_playwright
   import config
   async def run():
       async with async_playwright() as p:
           browser = await p.chromium.launch(headless=False)
           ctx = await browser.new_context()
           page = await ctx.new_page()
           await page.goto(config.API_BASE)
           input('Press Enter to close...')
   asyncio.run(run())
   "
   ```
2. Log in manually.
3. Navigate to a parcel with buildable area.
4. For each element below: right-click → **Inspect** → right-click the highlighted node
   in DevTools → **Copy** → **Copy selector**.
5. Set the corresponding env var in `.env` (or edit `config.py` directly).

| Config key | Element to inspect |
|---|---|
| `PARCEL_RESULT_URL_TEMPLATE` | Copy the URL from the browser address bar after navigating to a parcel page. Template form: `{api_base}/parcel/{parcel_id}` |
| `SEL_COPY_TO_PROJECT` | The "Copy to project" button on the parcel result page |
| `SEL_NEW_ANALYSIS` | The "New Analysis" button on the project page |
| `SEL_ANALYSIS_CONFIG` | The config `<select>` dropdown inside the New Analysis modal |
| `SEL_ANALYSIS_SUBMIT` | The submit/run button inside the modal |
| `SEL_CAPACITY_KW` | The element showing the installed capacity kW number |

### Verification gate

After filling in selectors, smoke-test with one parcel before running the full pipeline:

```python
import asyncio
from playwright.async_api import async_playwright
from auth import playwright_login
from installed_capacity import get_installed_capacity
import config

async def smoke():
    _, storage_state = await playwright_login(config.EMAIL, config.PASSWORD)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(storage_state=storage_state)
        result = await get_installed_capacity(ctx, {"parcel_id": "YOUR_PARCEL_ID"})
        print(f"Result: {result} kW")
        await browser.close()

asyncio.run(smoke())
```

Screenshots are saved to `output/screenshots/` at every step. Review them if the result
is `None`.

---

## API Reference (from HAR analysis, Feb 2026)

| Endpoint | Method | Description |
|---|---|---|
| `auth.glintsolar.com/login` | GET | Login page |
| `auth.glintsolar.com/sessions/whoami` | GET | Session validation |
| `app.glintsolar.com/api/pkg/parcels_{version}/{z}/{x}/{y}.pbf` | GET | PBF tile |
| `app.glintsolar.com/api/parcels/parcel-properties` | GET | Parcel metadata |
| `app.glintsolar.com/api/parcels/parcel-geometry` | GET | Parcel GeoJSON |
| `app.glintsolar.com/api/geo-insights-v2/buildable-area-async` | POST | Start buildable-area job |
| `glint-eu-west-1-geo-insights.s3.amazonaws.com/{portfolioId}/buildable-area/{requestId}.json` | GET | Poll buildable-area result |
| Installed capacity | DOM only | Computed client-side by pvSegments bundle; no API endpoint |

---

## Known Unknowns

| Priority | Item | Owner |
|---|---|---|
| 🔴 CRITICAL | `PARCEL_RESULT_URL_TEMPLATE` — URL pattern to navigate to a parcel in the app | Needs headed session |
| 🔴 CRITICAL | `SEL_COPY_TO_PROJECT` — button selector | Needs headed session |
| 🔴 CRITICAL | `SEL_NEW_ANALYSIS` — button selector | Needs headed session |
| 🔴 CRITICAL | `SEL_ANALYSIS_CONFIG` — dropdown selector in modal | Needs headed session |
| 🔴 CRITICAL | `SEL_ANALYSIS_SUBMIT` — submit button selector | Needs headed session |
| 🔴 CRITICAL | `SEL_CAPACITY_KW` — kW result DOM selector | Needs headed session |
| 🟡 HIGH | Confirm `parcel-properties` response field names (`ownership_info`, `tot_val`, etc.) match live API | Run Phase 1b and inspect first result |
| 🟡 HIGH | Confirm buildable-area result GeoJSON CRS (assumed WGS84) | Inspect actual S3 result |
| 🟢 KNOWN GAP | Null geometry features in buildable-area result not handled (`test_null_geometry_skipped` is xfailed) | Low priority — add guard to `calculate_buildable_acres` |

---

## Playwright Migration Task Board

Migrate Phase 3 from browser-use vision AI to deterministic Playwright selectors.
This eliminates LLM inference per step (3-4 min/parcel → ~30 sec/parcel) and removes
the `BROWSER_USE_API_KEY` dependency.

Playwright selectors confirmed by browser-use agent logs in `output/screenshots/*_playwright_log.md`:

| Action | Selector | Notes |
|---|---|---|
| Navigate | `project_url` | Direct URL load |
| Wait for sidebar | `page.wait_for_selector('text=Objects')` | After networkidle |
| Right-click parcel | `page.locator(f'p:has-text("Parcel {parcel_id}")').dispatch_event('contextmenu')` | Must dispatch on parent row |
| Click "Buildable Area" | `page.get_by_role("button", name="Buildable Area")` | Context menu item |
| Click "Run Buildable Area" | `page.get_by_role("button", name="Run Buildable Area")` | Inside settings panel |
| Wait for completion | Poll for `button:has-text("Copy to project")` to appear | Up to 2 min |
| Read acres | Parse text matching `(\d+\.\d+) ac` from floating panel | e.g. "23 objects selected, 62.44 ac" |
| Click "Copy to project" | `page.get_by_role("button", name="Copy to project")` | |
| Click "New analysis" | `page.get_by_role("button", name="New analysis")` | |
| Wait for kW | Poll for element containing `\d+\.\d+\s*MWp` with non-zero value | Up to 60s |
| Read kW | JS scan: `document.querySelectorAll('*')` → leaf with MWp pattern | `_read_kw_from_page` already implements this |

### Tasks (Drafter → Reviewer → Tester)

Dependencies are listed explicitly. A task must not start until all its `DEPENDS_ON` tasks
are marked `✅ DONE`. The orchestration script (`scripts/run_playwright_migration.py`)
enforces these constraints automatically.

---

#### TASK-P1: Playwright right-click + context menu  `[READY]`
**File**: `playwright_flow.py` (new module)
**Description**: Implement `open_buildable_area_panel(page, parcel_id)` — locates the
parcel row in the Objects sidebar, dispatches a contextmenu event, waits for the context
menu to appear, and clicks "Buildable Area". Returns when the buildable area settings
panel is visible.
**Depends on**: *(none)*
**Done when**: `tests/test_playwright_flow.py::test_open_buildable_area_panel` passes (mock page)

---

#### TASK-P2: Buildable area run + acres extraction  `[READY]`
**File**: `playwright_flow.py`
**Description**: Implement `run_buildable_area_and_copy(page)` — clicks "Run Buildable
Area", polls for "Copy to project" button (max 120s, 2s interval), parses the acres value
from the floating panel text, clicks "Copy to project", returns `(float_acres)`.
**Depends on**: *(none — can be developed independently from TASK-P1)*
**Done when**: `tests/test_playwright_flow.py::test_run_buildable_area_and_copy` passes

---

#### TASK-P3: New Analysis kW read  `[READY]`
**File**: `playwright_flow.py`
**Description**: Implement `click_new_analysis_and_read_kw(page)` — clicks "New analysis"
button, polls for a non-zero MWp/kWp value (max 60s), returns float kW. Uses
`_read_kw_from_page` from `installed_capacity.py` as the value extractor.
**Depends on**: *(none)*
**Done when**: `tests/test_playwright_flow.py::test_click_new_analysis_and_read_kw` passes

---

#### TASK-P4: Fix `_verify_and_screenshot`  `[READY — BLOCKED BY P3 knowledge]`
**File**: `installed_capacity.py`
**Description**: `_verify_and_screenshot` currently fails on every parcel because it relies
on `config.SEL_NEW_ANALYSIS` (a brittle CSS hash selector). Replace with
`click_new_analysis_and_read_kw(page)` from `playwright_flow.py` (TASK-P3). This makes
verification use the same stable text selectors the agent confirmed.
**Depends on**: TASK-P3
**Done when**: unit test for `_verify_and_screenshot` passes with a mock `click_new_analysis_and_read_kw`

---

#### TASK-P5: Replace browser-use with full Playwright in `_run_agent_for_parcel`  `[BLOCKED]`
**File**: `installed_capacity.py`
**Description**: Replace `_run_agent_for_parcel` with a pure Playwright implementation
that calls `open_buildable_area_panel` → `run_buildable_area_and_copy` →
`click_new_analysis_and_read_kw` in sequence. Removes `browser-use`, `ChatBrowserUse`,
and the temp-file storage_state hack. Uses `storage_state` dict directly via
`browser.new_context(storage_state=storage_state)`.
**Depends on**: TASK-P1, TASK-P2, TASK-P3, TASK-P4
**Done when**: `python -m pytest tests/ -v` → 58+ passed, 1 xfailed AND `python main.py`
runs 3 parcels with `kw_verified` populated (not None) for all

---

## Running the Pipeline

```bash
# Unit tests (no credentials needed)
python -m pytest tests/ -v

# Full end-to-end (requires .env with real credentials)
python main.py
```

Output: `output/parcels.csv`

Phase 3 screenshots: `output/screenshots/{parcel_id}_0{1-4}_*.png`

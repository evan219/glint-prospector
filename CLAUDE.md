# CLAUDE.md — Glint Solar Prospecting Agent

Best practices and agent workflow instructions for AI-assisted development on this project.
Inspired by testing patterns from [cleak/tea-leaves](https://github.com/cleak/tea-leaves).

---

## Project Overview

This agent automates solar parcel prospecting on `app.glintsolar.com`:
- **Phase 0** — Playwright login → cookie extraction
- **Phase 1** — PBF tile decode → parcel enumeration + property fetch
- **Phase 2** — `buildable-area-async` POST → S3 poll → shapely area calc
- **Phase 3** — Playwright DOM: Copy to project → New Analysis → read installed kW
- **Phase 4** — Export `output/parcels.csv`

Key fact: **Installed capacity is computed client-side** by Glint's JS bundles. It never
appears in any API response. Phase 3 always requires Playwright to read the DOM.

---

## Before Writing Any Code

1. **Read `config.py` first** — all known IDs, API constants, and constraint values live there.
2. **Check the HAR findings in this file** (§ API Reference) before adding new endpoints.
3. **Never hardcode org/portfolio IDs** inline — always reference `config.*`.
4. **Never commit `.env`** — use `.env.example` for documentation.

---

## Testing Protocol

### Verification Gate
Run this before marking any task complete:

```bash
# 1. Static checks
python -m py_compile auth.py tiles.py parcels.py buildable_area.py installed_capacity.py main.py
python -m mypy . --ignore-missing-imports

# 2. Unit tests
pytest tests/ -v

# 3. Auth smoke test (fastest real integration check)
python -c "
import asyncio
from auth import playwright_login, validate_session
import httpx, config

async def test():
    cookies = await playwright_login(config.EMAIL, config.PASSWORD)
    async with httpx.AsyncClient(cookies=cookies) as c:
        ok = await validate_session(c)
        assert ok, 'Session validation failed'
    print('Auth OK')

asyncio.run(test())
"
```

### Screenshot Review Protocol
Every Playwright interaction **must** produce screenshots at key steps.
Screenshots are saved to `output/screenshots/{parcel_id}_{step}_{label}.png`.

After any Phase 3 run, review screenshots in order:
| Step | Filename pattern | What to check |
|------|-----------------|---------------|
| 01 | `_01_project_loaded` | Correct project is open, map visible |
| 02 | `_02_new_analysis_modal` | Modal opened, config profile dropdown visible |
| 03 | `_03_layout_rendered` | Solar panels visible on map |
| 04 | `_04_selector_miss` | Should NOT exist — means capacity selector needs updating |
| 05 | `_05_capacity_found` | kW value visible and highlighted |
| ERR | `_ERROR` | Inspect to diagnose what went wrong |

If `_04_selector_miss` screenshots appear:
1. Open DevTools on the rendered page
2. Right-click the kW value → Copy → Copy selector
3. Update `GLINT_CAPACITY_SELECTOR` in `.env`

### Async Operation Testing
For any new polling loop (S3, API), validate both paths:
```python
# Test success path
result = await poll_s3_result("known-good-request-id")
assert result is not None
assert "features" in result

# Test timeout path (use a fake ID)
result = await poll_s3_result("00000000-0000-0000-0000-000000000000")
assert result is None  # should timeout gracefully, not raise
```

### Result Validation Pattern
After each phase, validate shape and content before proceeding:
```python
# Phase 1b validation
assert all("parcel_id" in p for p in parcels), "Missing parcel_id"
assert all(p["total_area_acres"] > 0 for p in parcels), "Zero-area parcel"

# Phase 2 validation
buildable = [p for p in parcels if p.get("buildable_area_acres") is not None]
print(f"Phase 2: {len(buildable)}/{len(parcels)} parcels have buildable area")

# Phase 3 validation
with_capacity = [p for p in parcels if p.get("installed_capacity_kw")]
print(f"Phase 3: {len(with_capacity)}/{len(buildable)} parcels have kW value")
```

---

## Code Quality

### Style
- Python 3.11+, async/await throughout
- Type hints on all function signatures
- `httpx.AsyncClient` for all API calls — never `requests`
- `asyncio.Semaphore` for concurrency control (see `parcels.py`)

### Error Handling
- Never let a single parcel failure crash the whole run
- All per-parcel operations return `None` on failure (not raise)
- Log `[module] message` prefix on every print for traceability
- On Playwright errors: always take a screenshot before returning `None`

### Logging Convention
```
[auth]      — authentication and session
[tiles]     — PBF tile decode and enumeration
[parcels]   — parcel-properties and parcel-geometry API
[buildable] — buildable-area-async and S3 polling
[capacity]  — Phase 3 Playwright flow
[main]      — orchestration and pipeline control
```

### Concurrency Rules
- Parcel property fetches: `asyncio.Semaphore(MAX_CONCURRENT_PARCEL_CALLS)` — batched
- Buildable area: **serial** per parcel — each POST is expensive and stateful
- Phase 3: **serial** per parcel — Playwright context is shared, one page at a time
- Tile downloads: batched in groups of 10 (see `tiles.py`)

---

## API Reference (from HAR Analysis, Feb 2026)

### Known Endpoints

| Phase | Method | Endpoint | Notes |
|-------|--------|----------|-------|
| Auth | GET | `https://auth.glintsolar.com/sessions/whoami` | Validate session |
| 1a | GET | `/api/pkg/parcels_{version}/{z}/{x}/{y}.pbf?packageId=USA` | PBF tiles |
| 1b | GET | `/api/parcels/parcel-properties?packageId=USNY&id={id}&version={v}` | Lightweight metadata |
| 1b | GET | `/api/parcels/parcel-geometry?id={id}&packageId=USNY&version={v}` | GeoJSON polygon |
| 2 | POST | `/api/geo-insights-v2/buildable-area-async?orgId=...&portfolioId=...` | Kick off job |
| 2 | GET | `https://glint-eu-west-1-geo-insights.s3.amazonaws.com/{portfolioId}/buildable-area/{requestId}.json` | Poll result |
| 3 | GET | `/api/configurations?orgId=...&portfolioId=...` | Design config profiles |
| 3 | GET | `/api/analyses?orgId=...&portfolioId=...&projectId=...` | List analyses |

### Known IDs

| Key | Value |
|-----|-------|
| `orgId` | `org_OoParhEkGMoVGWXY` |
| `portfolioId` | `cus_EnumCTAzNbIUxQKl` |
| Parcel version | `20250617` |
| NYSEG BESS version | `20260109` |
| Wetlands version | `20251001` |

### Constraint Profile Note
The UI's "Constraints Profile" dropdown (e.g. "BESS Capacity") auto-fills constraint
values in the browser — there is no profile ID accepted by the API. All constraints are
sent inline in the `buildable-area-async` POST body. The exact constraint values for the
"BESS Capacity" profile are in `config.BUILDABLE_CONSTRAINTS`.

### Phase 3 Key Finding
Installed capacity is **never returned by any API**. It is computed client-side by:
- `pvSegments-yd5TuR0N.js` (387 KB) — tiles panels onto buildable polygon
- `createSolarPanels-CU3YJTdo.js` (10 KB) — creates panel objects, computes DC/AC

Always use Playwright to read the kW value from the DOM after the layout renders.

---

## Known Unknowns / Next Steps

| Priority | Item |
|----------|------|
| CRITICAL | Confirm `INSTALLED_CAPACITY_SELECTOR` — run Phase 3 headed, inspect DOM |
| CRITICAL | Confirm "Copy to project" → "New Analysis" button selectors in `installed_capacity.py` |
| HIGH | Capture POST `/api/analyses` from a complete Phase 3 HAR (recording stopped at modal open) |
| HIGH | Confirm `project_url` pattern: is it `/projects/{id}` or `/portfolio/{portfolioId}/project/{id}`? |
| MEDIUM | Add retry logic for S3 poll (transient 403s observed on cold starts) |
| MEDIUM | Tile enumeration: validate PBF field name for parcel ID (may be `id` not `parcel_id`) |
| LOW | Consider caching parcel-geometry responses to avoid redundant fetches in Phase 3 |

---

## Output Artifacts

After a successful run:
```
output/
├── parcels.csv              # Full results table
└── screenshots/
    ├── {parcel_id}_01_project_loaded.png
    ├── {parcel_id}_02_new_analysis_modal.png
    ├── {parcel_id}_03_layout_rendered.png
    └── {parcel_id}_05_capacity_found.png
```

The CSV schema:
`parcel_id, owner_name, parcel_address, mail_address, total_area_acres, land_use,
assessed_value, buildable_area_acres, buildable_pct, installed_capacity_kw, lat, lon`

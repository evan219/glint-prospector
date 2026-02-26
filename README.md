# Glint Solar Prospecting Agent

Automates solar parcel prospecting on `app.glintsolar.com` — extracting landowner data, running buildable area analysis, and capturing installed capacity estimates for unconstrained parcels in a target geography.

## Architecture

| Phase | Approach | Status |
|---|---|---|
| **0** Auth | Playwright login → extract cookies for httpx | Ready |
| **1a** Tile Enum | Decode PBF tiles → enumerate parcel IDs | Ready |
| **1b** Properties | `parcel-properties` API loop | Ready |
| **2** Buildable Area | `buildable-area-async` POST → S3 poll → shapely | Ready |
| **3** Installed Capacity | TBD: API or Playwright (see `installed_capacity.py`) | **Stub** |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Edit .env with your credentials and target bounding box
```

## Run

```bash
python main.py
```

Output is written to `output/parcels.csv`.

## Phase 3 — Next Steps

Before Phase 3 can be implemented, capture a HAR file during the full flow:

1. Run buildable area on a parcel
2. Click **Copy to project** → **Create new project**
3. Click **New analysis**, accept defaults
4. Wait for solar panel layout to render, note the **Installed Capacity (kW)** value
5. Check HAR for any `POST`/`GET` to `geo-insights`, `analysis`, or `design` endpoints
6. If API-based: map the endpoint in `installed_capacity.py`
7. If DOM-only: add the CSS selector for the kW value and implement the Playwright flow

## Target Geography

Set `BBOX_*` in `.env` to define your prospecting area. At zoom 13, each tile covers ~10–20 sq km. A 50 km × 50 km area ≈ 25 tiles ≈ 1,250–5,000 parcel API calls (~8 min with async httpx).

## Known IDs (from HAR analysis)

| Parameter | Value |
|---|---|
| `orgId` | `org_OoParhEkGMoVGWXY` |
| `portfolioId` | `cus_EnumCTAzNbIUxQKl` |
| `packageId` (state) | `USNY` |
| `packageId` (national) | `USA` |
| Parcel version | `20250617` |

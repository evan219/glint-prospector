"""
Central configuration — loaded once at startup.
All known IDs and API constants are sourced from HAR analysis (Feb 2026).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Credentials ---
EMAIL = os.environ["GLINT_EMAIL"]
PASSWORD = os.environ["GLINT_PASSWORD"]

# --- Known IDs from HAR ---
ORG_ID = "org_OoParhEkGMoVGWXY"
PORTFOLIO_ID = "cus_EnumCTAzNbIUxQKl"
PACKAGE_ID_STATE = "USNY"
PACKAGE_ID_NATIONAL = "USA"
PARCEL_VERSION = "20250617"

# --- API base URLs ---
AUTH_BASE = "https://auth.glintsolar.com"
API_BASE = "https://app.glintsolar.com"
S3_BASE = "https://glint-eu-west-1-geo-insights.s3.amazonaws.com"

# --- Tile enumeration ---
TILE_ZOOM = int(os.getenv("TILE_ZOOM", 13))
BBOX = {
    "lat_min": float(os.getenv("BBOX_LAT_MIN", 42.00)),
    "lat_max": float(os.getenv("BBOX_LAT_MAX", 42.30)),
    "lon_min": float(os.getenv("BBOX_LON_MIN", -78.10)),
    "lon_max": float(os.getenv("BBOX_LON_MAX", -77.70)),
}

# --- Buildable area constraints (confirmed from HAR, Feb 2026) ---
# These match the live request captured when the user pressed "Run Buildable Area".
# The nyseg_reg_bess_analysis constraint was absent from the live request and is
# profile/parcel-specific — do not add it here.
BUILDABLE_CONSTRAINTS = [
    {
        "layerId": "steepness",
        "flag": "steepness",
        "inclusion": False,
        # All four directions use the same slope-percentage threshold (uniform).
        "limits": {
            "west": 5.710593137499643,
            "east": 5.710593137499643,
            "south": 5.710593137499643,
            "north": 5.710593137499643,
        },
        "country": PACKAGE_ID_STATE,
    },
    {
        "layerId": "wetlands",
        "flag": "wetlands",
        "inclusion": False,
        "buffer": 30.48,
        "version": 20251001,
        "sources": [
            "EstuarineandMarineDeepwater",
            "EstuarineandMarineWetland",
            "FreshwaterEmergentWetland",
            "FreshwaterForestedShrubWetland",
            "FreshwaterPond",
            "Lake",
            "Riverine",
        ],
        "country": PACKAGE_ID_STATE,
        "sourcesMap": {
            "Estuarine and Marine Deepwater": ["EstuarineandMarineDeepwater"],
            "Estuarine and Marine Wetland": ["EstuarineandMarineWetland"],
            "Freshwater Emergent Wetland": ["FreshwaterEmergentWetland"],
            "Freshwater Forested/Shrub Wetland": ["FreshwaterForestedShrubWetland"],
            "Freshwater Pond": ["FreshwaterPond"],
            "Lake": ["Lake"],
            "Riverine": ["Riverine"],
        },
    },
    {
        "flag": "parcels",
        "version": int(PARCEL_VERSION),
        "minArea": 101171.41056000002,
        "maxArea": 809371.2844800001,
        "sources": ["main"],
        "country": PACKAGE_ID_STATE,
    },
]

# --- Phase 3: Installed Capacity (Playwright DOM flow) ---
# PROJECT_URL: URL of a Glint project containing the parcel(s) to analyse.
# Set via .env after manually creating a project and adding parcels.
# Clicking "New Analysis" on the project page opens a modal that immediately
# shows the installed capacity — no submit button or config dropdown needed.

SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "output/screenshots")

PROJECT_URL = os.getenv("PROJECT_URL", "TODO")

# PROJECT_ID: extracted from PROJECT_URL (.../projects/{id}?...) or set explicitly.
_raw_project_url = PROJECT_URL
PROJECT_ID = os.getenv("PROJECT_ID") or (
    _raw_project_url.split("/projects/")[-1].split("?")[0]
    if "/projects/" in _raw_project_url
    else "TODO"
)

# DOM selectors (right-click element in DevTools → Copy → Copy selector)
SEL_NEW_ANALYSIS = os.getenv("SEL_NEW_ANALYSIS", "TODO")       # "New Analysis" btn
SEL_CAPACITY_KW = os.getenv("SEL_CAPACITY_KW", "TODO")         # kW number element
# "Run Buildable Area" button in the parcel analysis panel (right sidebar).
# Appears after clicking a parcel row in the object list.
SEL_BUILDABLE_AREA_BTN = os.getenv(
    "SEL_BUILDABLE_AREA_BTN",
    "#root > div > div > div._container_i8sf3_1 > div > div "
    "> div._footer_ks47x_198 > button._button_10u1k_1._outline_10u1k_59._small_10u1k_113",
)

# --- Concurrency ---
MAX_CONCURRENT_PARCEL_CALLS = 20
S3_POLL_INTERVAL_SECONDS = 5
S3_POLL_MAX_ATTEMPTS = 60  # 5 min timeout

# --- Output ---
OUTPUT_DIR = "output"
OUTPUT_CSV = f"{OUTPUT_DIR}/parcels.csv"

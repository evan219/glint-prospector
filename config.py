"""
Central configuration — loaded once at startup.
All known IDs, API constants, and constraint values sourced from HAR analysis (Feb 2026).

Constraint note: The UI presents a "Constraints Profile" dropdown (e.g. "BESS Capacity")
that auto-fills constraint values in the browser before sending the buildable-area POST.
There is no separate profile-fetch API — the constraints are always sent inline.
The values below are the exact payload extracted from the "BESS Capacity" profile HAR.
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

# --- Buildable area constraints — "BESS Capacity" profile (exact values from HAR) ---
# These are sent inline in every buildable-area-async POST. The UI profile dropdown
# ("BESS Capacity") simply auto-fills these same values — there is no profile ID param.
BUILDABLE_CONSTRAINTS = [
    {
        "flag": "steepness",
        "layerId": "steepness",
        "inclusion": False,
        "limits": {
            "west": 5.710593137499643,
            "east": 5.710593137499643,
            "south": 5.710593137499643,
            "north": 5.710593137499643,
        },
        "country": PACKAGE_ID_STATE,
    },
    {
        "flag": "wetlands",
        "layerId": "wetlands",
        "inclusion": False,
        "buffer": 30.48,          # 100 ft setback
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
    },
    {
        "flag": "nyseg_reg_bess_analysis",
        "layerId": "nyseg_reg_bess_analysis",
        "inclusion": True,        # inclusion = within 1000 ft of qualifying feeders
        "buffer": 304.8,          # 1000 ft
        "version": 20260109,
        "sources": [
            "hostingcapacity_1_00_1_49",
            "hostingcapacity_1_50_1_99",
            "hostingcapacity_2_00_2_99",
            "hostingcapacity_3_00_4_99",
            "hostingcapacity_5_00_10_00",
        ],
        "country": PACKAGE_ID_STATE,
    },
    {
        "flag": "parcels",
        "version": 20250617,
        "minArea": 101171.41056000002,   # ~25 acres in sq meters
        "maxArea": 809371.2844800001,    # ~200 acres in sq meters
        "sources": ["main"],
        "country": PACKAGE_ID_STATE,
    },
]

# --- Phase 3: New Analysis configuration ---
# Installed capacity is computed client-side by JS bundles after "New Analysis" renders.
# DEFAULT_ANALYSIS_CONFIG_NAME must match a name returned by GET /api/configurations.
# Options from HAR: "Max Spec. Yield - Fixed 2P", "Max Spec. Yield - Tracker 2P",
#                   "Max DC - Tracker 2P", "East-west 1P", "Vertical AgriVoltaics - Landscape"
DEFAULT_ANALYSIS_CONFIG_NAME = os.getenv(
    "GLINT_ANALYSIS_CONFIG", "Max Spec. Yield - Fixed 2P"
)
# Selector for the rendered installed capacity kW value in the DOM.
# Update after inspecting the "New Analysis" result panel in DevTools.
INSTALLED_CAPACITY_SELECTOR = os.getenv(
    "GLINT_CAPACITY_SELECTOR", "[data-testid='installed-capacity']"
)

# --- Concurrency ---
MAX_CONCURRENT_PARCEL_CALLS = 20
S3_POLL_INTERVAL_SECONDS = 5
S3_POLL_MAX_ATTEMPTS = 60  # 5 min timeout

# --- Output ---
OUTPUT_DIR = "output"
OUTPUT_CSV = f"{OUTPUT_DIR}/parcels.csv"
SCREENSHOT_DIR = f"{OUTPUT_DIR}/screenshots"

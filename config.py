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

# --- Buildable area constraints (from HAR) ---
# Copy the full constraints array from your HAR for your profile.
BUILDABLE_CONSTRAINTS = [
    {
        "flag": "steepness",
        "layerId": "steepness",
        "inclusion": False,
        "limits": {"north": 2, "south": 9, "east": 5, "west": 5},
        "country": PACKAGE_ID_STATE,
    },
    {
        "flag": "wetlands",
        "layerId": "wetlands",
        "inclusion": False,
        "buffer": 30.48,
        "sources": [],  # populate from your HAR
        "country": PACKAGE_ID_STATE,
    },
    {
        "flag": "nyseg_reg_bess_analysis",
        "layerId": "nyseg_reg_bess_analysis",
        "inclusion": True,
        "buffer": 304.8,
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
        "version": int(PARCEL_VERSION),
        "minArea": 101171.41,
        "maxArea": 809371.28,
        "sources": ["main"],
        "country": PACKAGE_ID_STATE,
    },
]

# --- Concurrency ---
MAX_CONCURRENT_PARCEL_CALLS = 20
S3_POLL_INTERVAL_SECONDS = 5
S3_POLL_MAX_ATTEMPTS = 60  # 5 min timeout

# --- Output ---
OUTPUT_DIR = "output"
OUTPUT_CSV = f"{OUTPUT_DIR}/parcels.csv"

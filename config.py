"""
Central configuration for the flight tracking pipeline.
All tunable constants live here so nothing is hardcoded/scattered across files.
"""

import os

from dotenv import load_dotenv
load_dotenv()

# --- OpenSky bounding box: South Asia + surrounding airspace ---
# Covers Sri Lanka, India, Bangladesh, and major Europe<->Asia overflight corridors.
BBOX = {
    "lamin": 5.0,
    "lomin": 68.0,
    "lamax": 30.0,
    "lomax": 92.0,
}

# --- OpenSky API ---
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)

# Optional authenticated access (recommended: higher rate limit, more reliable).
# Leave unset to fall back to anonymous access (still enough for 15-min polling).
OPENSKY_CLIENT_ID = os.environ.get("OPENSKY_CLIENT_ID")
OPENSKY_CLIENT_SECRET = os.environ.get("OPENSKY_CLIENT_SECRET")

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# --- Retention policy ---
RETENTION_DAYS = 7

# --- Database ---
# Full connection string, e.g.:
# postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/flightdb?sslmode=require
DATABASE_URL = os.environ.get("DATABASE_URL")

# --- Logging ---
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")

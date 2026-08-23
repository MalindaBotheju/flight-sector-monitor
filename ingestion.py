"""
Extract step of the ETL pipeline.

Responsibility: talk to the OpenSky API and return raw state vectors
for the configured bounding box. Does NOT clean or store anything —
that's cleaning.py and database.py's job. Keeping this boundary strict
is what makes each piece independently testable.
"""

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

# OpenSky's /states/all response is a flat array per aircraft, in this fixed order.
# Naming them here means the rest of the pipeline works with dicts, not magic indices.
STATE_VECTOR_FIELDS = [
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",          # not stored — internal OpenSky field
    "geo_altitude",
    "squawk",
    "spi",               # not stored
    "position_source",   # not stored
]


class OpenSkyAuthError(Exception):
    pass


class OpenSkyRequestError(Exception):
    pass


def _get_access_token() -> str:
    """Exchange client credentials for a bearer token (OAuth2 client_credentials flow)."""
    resp = requests.post(
        config.OPENSKY_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": config.OPENSKY_CLIENT_ID,
            "client_secret": config.OPENSKY_CLIENT_SECRET,
        },
        timeout=config.REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise OpenSkyAuthError(f"Token request failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def fetch_state_vectors() -> list[dict]:
    """
    Fetch current aircraft state vectors within the configured bounding box.

    Returns a list of dicts, each representing one aircraft's raw state.
    Raises OpenSkyRequestError on failure so main.py can decide how to handle it
    (log and skip this run, rather than silently returning nothing).
    """
    params = {
        "lamin": config.BBOX["lamin"],
        "lomin": config.BBOX["lomin"],
        "lamax": config.BBOX["lamax"],
        "lomax": config.BBOX["lomax"],
    }

    headers = {}
    if config.OPENSKY_CLIENT_ID and config.OPENSKY_CLIENT_SECRET:
        try:
            token = _get_access_token()
            headers["Authorization"] = f"Bearer {token}"
        except OpenSkyAuthError as e:
            # Don't hard-fail the whole run just because auth failed —
            # fall back to anonymous access, which still works within our rate needs.
            logger.warning("Auth failed, falling back to anonymous access: %s", e)

    start = time.monotonic()
    try:
        resp = requests.get(
            config.OPENSKY_STATES_URL,
            params=params,
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise OpenSkyRequestError(f"Request to OpenSky failed: {e}") from e

    elapsed = time.monotonic() - start

    if resp.status_code != 200:
        raise OpenSkyRequestError(f"OpenSky returned {resp.status_code}: {resp.text[:300]}")

    payload = resp.json()
    raw_states = payload.get("states") or []

    logger.info(
        "Fetched %d raw state vectors in %.2fs (response time=%s)",
        len(raw_states), elapsed, payload.get("time"),
    )

    records = []
    for state in raw_states:
        # Some historical/edge responses can be shorter than the full field list —
        # pad defensively rather than crashing on a malformed row.
        padded = state + [None] * (len(STATE_VECTOR_FIELDS) - len(state))
        record = dict(zip(STATE_VECTOR_FIELDS, padded))
        records.append(record)

    return records

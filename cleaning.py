"""
Transform step of the ETL pipeline.

Responsibility: take raw records from ingestion.py and turn them into
rows that are safe to insert — valid types, sane ranges, no duplicates,
normalized text fields. This is where "bad coordinates, missing
callsigns, etc." gets handled, as a distinct step from extraction.
"""

import logging

logger = logging.getLogger(__name__)

# Sanity bounds — reject anything outside physically plausible ranges
# rather than trusting the API blindly.
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LON, MAX_LON = -180.0, 180.0
MAX_ALTITUDE_M = 20000.0   # ~65,000 ft, well above any commercial ceiling
MIN_ALTITUDE_M = -500.0    # allow slightly below sea level (e.g. Dead Sea region)


def _is_valid_coord(lat, lon) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON


def _clean_altitude(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value < MIN_ALTITUDE_M or value > MAX_ALTITUDE_M:
        return None
    return value


def _clean_callsign(value):
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def clean_records(raw_records: list[dict]) -> list[dict]:
    """
    Validate and normalize a batch of raw state vectors.

    Rules applied:
      - icao24 must be present (it's our primary identifier) -> drop row if missing
      - last_contact must be present (needed for time-series ordering) -> drop if missing
      - lat/lon must be valid coordinates or both set to None (never a partial pair
        that looks valid but isn't)
      - altitude values clamped to a plausible range, else nulled
      - callsign whitespace-stripped; empty string normalized to None
      - exact duplicate (icao24, last_contact) pairs within this batch are dropped,
        since OpenSky occasionally returns the same aircraft twice in one response
    """
    seen_keys = set()
    cleaned = []
    dropped_missing_id = 0
    dropped_duplicate = 0
    coords_nulled = 0

    for rec in raw_records:
        icao24 = rec.get("icao24")
        last_contact = rec.get("last_contact")

        if not icao24 or last_contact is None:
            dropped_missing_id += 1
            continue

        icao24 = icao24.strip().lower()
        dedup_key = (icao24, last_contact)
        if dedup_key in seen_keys:
            dropped_duplicate += 1
            continue
        seen_keys.add(dedup_key)

        lat, lon = rec.get("latitude"), rec.get("longitude")
        if not _is_valid_coord(lat, lon):
            if lat is not None or lon is not None:
                coords_nulled += 1
            lat, lon = None, None

        cleaned.append({
            "icao24": icao24,
            "callsign": _clean_callsign(rec.get("callsign")),
            "origin_country": (rec.get("origin_country") or "").strip() or None,
            "time_position": rec.get("time_position"),
            "last_contact": last_contact,
            "longitude": lon,
            "latitude": lat,
            "baro_altitude": _clean_altitude(rec.get("baro_altitude")),
            "on_ground": bool(rec.get("on_ground")) if rec.get("on_ground") is not None else None,
            "velocity": rec.get("velocity"),
            "true_track": rec.get("true_track"),
            "vertical_rate": rec.get("vertical_rate"),
            "geo_altitude": _clean_altitude(rec.get("geo_altitude")),
            "squawk": rec.get("squawk"),
        })

    logger.info(
        "Cleaned %d -> %d records (dropped_missing_id=%d, dropped_duplicate=%d, coords_nulled=%d)",
        len(raw_records), len(cleaned), dropped_missing_id, dropped_duplicate, coords_nulled,
    )

    return cleaned

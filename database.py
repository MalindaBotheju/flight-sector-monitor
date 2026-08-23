"""
Load step of the ETL pipeline.

Responsibility: own all direct database interaction — connecting,
bulk-inserting cleaned rows, and enforcing the retention policy.
Nothing else in the codebase should talk to psycopg2 directly;
that isolation is what makes it easy to swap databases later
(e.g. Neon -> RDS) by touching only this file.
"""

import logging

import psycopg2
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

INSERT_COLUMNS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact",
    "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
    "true_track", "vertical_rate", "geo_altitude", "squawk",
]


def get_connection():
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Export it or put it in a .env file "
            "before running the pipeline."
        )
    return psycopg2.connect(config.DATABASE_URL)


def insert_records(records: list[dict]) -> int:
    """Bulk-insert cleaned records. Returns the number of rows inserted."""
    if not records:
        logger.info("No records to insert this run.")
        return 0

    rows = [tuple(rec[col] for col in INSERT_COLUMNS) for rec in records]

    query = f"""
        INSERT INTO flight_positions ({", ".join(INSERT_COLUMNS)})
        VALUES %s
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, query, rows, page_size=500)
        logger.info("Inserted %d rows into flight_positions.", len(rows))
        return len(rows)
    finally:
        conn.close()


def enforce_retention(retention_days: int = None) -> int:
    """
    Delete rows older than the retention window. Returns number of rows deleted.
    Uses last_contact (unix timestamp) since that's the semantic "when was this true"
    field, not ingested_at (which is "when did our pipeline happen to run").
    """
    retention_days = retention_days or config.RETENTION_DAYS

    query = """
        DELETE FROM flight_positions
        WHERE last_contact < EXTRACT(EPOCH FROM NOW() - (%s || ' days')::interval)
    """

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, (retention_days,))
                deleted = cur.rowcount
        logger.info("Retention cleanup: deleted %d rows older than %d days.", deleted, retention_days)
        return deleted
    finally:
        conn.close()


def get_current_row_count() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM flight_positions")
            return cur.fetchone()[0]
    finally:
        conn.close()

-- ============================================================
-- Flight Tracking Pipeline — Schema
-- Run this once against your Neon database to set everything up.
-- ============================================================

-- Raw / clean landing table for aircraft state snapshots.
-- Append-only: every pipeline run INSERTs new rows here.
-- Never UPDATE existing rows — the history IS the point.
CREATE TABLE IF NOT EXISTS flight_positions (
    id              BIGSERIAL PRIMARY KEY,
    icao24          VARCHAR(6)  NOT NULL,        -- stable aircraft identifier (NOT callsign)
    callsign        VARCHAR(8),                  -- flight number, often null/blank
    origin_country  VARCHAR(100),
    time_position   BIGINT,                      -- unix timestamp of last position update
    last_contact    BIGINT NOT NULL,              -- unix timestamp of last contact
    longitude       DOUBLE PRECISION,
    latitude        DOUBLE PRECISION,
    baro_altitude   DOUBLE PRECISION,             -- meters
    on_ground       BOOLEAN,
    velocity        DOUBLE PRECISION,             -- m/s
    true_track      DOUBLE PRECISION,             -- degrees
    vertical_rate   DOUBLE PRECISION,             -- m/s, positive = climbing
    geo_altitude    DOUBLE PRECISION,             -- meters
    squawk          VARCHAR(4),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()  -- when OUR pipeline wrote this row
);

-- Indexes that matter for the query patterns we'll actually run:
-- time-range scans (retention delete, dashboard time filters) and per-aircraft lookups.
CREATE INDEX IF NOT EXISTS idx_flight_positions_last_contact
    ON flight_positions (last_contact);

CREATE INDEX IF NOT EXISTS idx_flight_positions_icao24
    ON flight_positions (icao24);

CREATE INDEX IF NOT EXISTS idx_flight_positions_ingested_at
    ON flight_positions (ingested_at);

-- ============================================================
-- Analytics views — SQL layer sits on top of the raw table.
-- Dashboard queries these, never the raw table directly.
-- ============================================================

-- Aircraft activity per hour (for a time-series chart)
CREATE OR REPLACE VIEW v_hourly_activity AS
SELECT
    date_trunc('hour', to_timestamp(last_contact)) AS hour_bucket,
    COUNT(DISTINCT icao24) AS unique_aircraft,
    COUNT(*) AS total_observations
FROM flight_positions
GROUP BY 1
ORDER BY 1;

-- Aircraft count by country of registration
CREATE OR REPLACE VIEW v_country_breakdown AS
SELECT
    COALESCE(NULLIF(TRIM(origin_country), ''), 'Unknown') AS origin_country,
    COUNT(DISTINCT icao24) AS unique_aircraft,
    COUNT(*) AS total_observations
FROM flight_positions
GROUP BY 1
ORDER BY 2 DESC;

-- Snapshot-level summary stats (for KPI cards)
CREATE OR REPLACE VIEW v_summary_stats AS
SELECT
    COUNT(DISTINCT icao24) AS unique_aircraft_7d,
    COUNT(*) AS total_observations_7d,
    COUNT(DISTINCT origin_country) FILTER (WHERE origin_country IS NOT NULL) AS countries_seen,
    ROUND(AVG(baro_altitude)::numeric, 0) AS avg_altitude_m,
    ROUND(AVG(velocity)::numeric, 1) AS avg_velocity_ms,
    MAX(ingested_at) AS last_ingested_at
FROM flight_positions;

-- Most frequently observed aircraft (repeat visitors to the bounding box)
CREATE OR REPLACE VIEW v_most_seen_aircraft AS
SELECT
    icao24,
    -- most recent non-null callsign for that aircraft, trimmed
    (ARRAY_AGG(NULLIF(TRIM(callsign), '') ORDER BY last_contact DESC) FILTER (WHERE callsign IS NOT NULL))[1] AS callsign,
    origin_country,
    COUNT(*) AS observations
FROM flight_positions
GROUP BY icao24, origin_country
ORDER BY observations DESC
LIMIT 20;

-- Latest known position of every aircraft currently in the 7-day window
-- (useful for "current snapshot" map view rather than plotting all history at once)
CREATE OR REPLACE VIEW v_latest_positions AS
SELECT DISTINCT ON (icao24)
    icao24, callsign, origin_country, latitude, longitude,
    baro_altitude, velocity, true_track, on_ground, last_contact
FROM flight_positions
WHERE latitude IS NOT NULL AND longitude IS NOT NULL
ORDER BY icao24, last_contact DESC;

-- Climbing / cruising / descending / on-ground breakdown
CREATE OR REPLACE VIEW v_flight_phase_breakdown AS
SELECT
    CASE
        WHEN on_ground THEN 'on_ground'
        WHEN vertical_rate > 1 THEN 'climbing'
        WHEN vertical_rate < -1 THEN 'descending'
        ELSE 'cruising'
    END AS flight_phase,
    COUNT(*) AS observations
FROM flight_positions
GROUP BY 1;

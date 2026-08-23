# Flight Sector Monitor — Real-Time Data Ingestion & Historical Analytics Pipeline

A scheduled ETL pipeline that polls live aircraft state vectors from the OpenSky
Network for a South Asia bounding box, cleans and loads them into PostgreSQL
(Neon), and serves the accumulated history through a Streamlit dashboard.

```
OpenSky API → cron (every 15 min) → Python ETL → PostgreSQL (Neon)
            → SQL analytics views → Streamlit dashboard
```

The core engineering idea: OpenSky only gives you the *current* state of the
sky. This pipeline is what turns that into *history* — repeated snapshots,
accumulated over time, queryable as a time series.

## Project layout

```
flight-pipeline/
├── notebooks/
│   └── 01_explore_opensky.ipynb   # exploration only — not part of the pipeline
├── config.py                       # bounding box, retention window, env vars
├── ingestion.py                    # Extract: pulls state vectors from OpenSky
├── cleaning.py                     # Transform: validation, dedup, normalization
├── database.py                     # Load: bulk insert + retention enforcement
├── main.py                         # Orchestrator — this is what cron runs
├── dashboard.py                    # Streamlit presentation layer (read-only)
├── schema.sql                      # Table + analytics views — run once on Neon
├── requirements.txt
├── .env.example
└── .streamlit/config.toml          # dashboard theme
```

## 1. Set up the database

1. Create a new Neon project (region: AWS Asia Pacific 1 / Singapore).
2. Copy the connection string from the Neon dashboard.
3. Run the schema against it:

```bash
psql "$DATABASE_URL" -f schema.sql
```

This creates the `flight_positions` table and all analytics views
(`v_summary_stats`, `v_hourly_activity`, `v_country_breakdown`,
`v_latest_positions`, `v_most_seen_aircraft`, `v_flight_phase_breakdown`).

## 2. Configure environment

```bash
cp .env.example .env
# edit .env and set DATABASE_URL (required)
# OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET are optional but recommended —
# free signup at https://opensky-network.org gives you 4,000 requests/day
# instead of 400 anonymous
```

## 3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Run one manual cycle to confirm everything works

```bash
export $(grep -v '^#' .env | xargs)   # load .env into the shell
python main.py
```

Check `logs/pipeline.log` — you should see how many rows were inserted.

## 5. Schedule it with cron (every 15 minutes)

```bash
crontab -e
```

Add (adjust paths to your actual project location):

```
*/15 * * * * cd /path/to/flight-pipeline && /path/to/flight-pipeline/venv/bin/python main.py >> logs/cron.log 2>&1
```

Since `main.py` reads `config.py`, which reads `os.environ`, cron needs the
env vars available too — either export them in the crontab itself, or have
`main.py`/`config.py` load `.env` directly (recommended: add `python-dotenv`
loading at the top of `config.py` if you want cron to "just work" without
exporting manually).

## 6. Run the dashboard

```bash
streamlit run dashboard.py
```

The dashboard reads only from the SQL views — it never writes anything and
never touches the raw table directly.

## Design notes

- **Identity:** `icao24` is used as the aircraft identifier throughout, not
  `callsign` — callsigns are frequently blank or inconsistent; `icao24` is
  the stable 24-bit transponder address.
- **Append-only:** the pipeline only ever `INSERT`s and `DELETE`s-by-age. It
  never `UPDATE`s a row, which is what makes it safe to run unattended.
- **Retention:** every run deletes rows older than 7 days
  (`RETENTION_DAYS` in `config.py`), keyed off `last_contact` (when the
  data was true), not `ingested_at` (when we happened to fetch it).
- **Bounding box:** South Asia + surrounding overflight corridors
  (`lamin=5, lomin=68, lamax=30, lomax=92`) — chosen to keep storage well
  within Neon's free-tier 0.5GB limit at a 15-minute polling interval.

## Roadmap (not built yet, on purpose)

- V2: move scheduling to GitHub Actions + confirm hosted DB reachability
- V3: stream via a message queue instead of polling
- V4: anomaly detection on top of the historical table

V1 is deliberately just: a reliable, unattended pipeline that has been
running long enough to have real history to show.

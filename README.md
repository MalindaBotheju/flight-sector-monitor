# Flight Sector Monitor — Real-Time Flight Data Ingestion & Historical Analytics Pipeline

A fully deployed, unattended ETL pipeline that polls live aircraft state vectors
from the OpenSky Network for a South Asia bounding box, cleans and loads them
into PostgreSQL (Neon), and serves the accumulated history through a public
Streamlit dashboard — running entirely in the cloud, independent of any local
machine.

**Live dashboard:** https://flight-sector-monitor-7v77x3ibxstrybvtcygixr.streamlit.app

```
OpenSky API → GitHub Actions (every 15 min) → Python ETL → PostgreSQL (Neon)
            → SQL analytics views → Streamlit Community Cloud dashboard
```

The core engineering idea: OpenSky only exposes the *current* state of the
sky. This pipeline is what turns that into *history* — repeated snapshots,
accumulated over time, queryable as a time series, with old data automatically
aged out so storage stays bounded forever.

## Architecture

| Stage | Tool | Responsibility |
|---|---|---|
| Extract | `ingestion.py` | Pull current aircraft state vectors from OpenSky for the bounding box |
| Transform | `cleaning.py` | Validate, deduplicate, and normalize raw records |
| Load | `database.py` | Bulk insert into Postgres + enforce 7-day retention |
| Orchestration | `main.py` | Run one full extract → transform → load cycle, log the result |
| Scheduling | GitHub Actions (`.github/workflows/pipeline.yml`) | Run `main.py` every 15 minutes, in the cloud |
| Storage | Neon (managed PostgreSQL) | Append-only historical table + analytics views |
| Presentation | `dashboard.py` (Streamlit) | Read-only dashboard, deployed on Streamlit Community Cloud |

## Project layout

```
flight-sector-monitor/
├── .github/workflows/
│   └── pipeline.yml            # scheduled + manually-triggerable pipeline run
├── notebooks/
│   └── 01_explore_opensky.ipynb # exploration only — not part of the pipeline
├── .streamlit/
│   └── config.toml             # dashboard theme
├── config.py                    # bounding box, retention window, env vars
├── ingestion.py                  # Extract: pulls state vectors from OpenSky
├── cleaning.py                   # Transform: validation, dedup, normalization
├── database.py                   # Load: bulk insert + retention enforcement
├── main.py                       # Orchestrator — what the scheduler runs
├── dashboard.py                  # Streamlit presentation layer (read-only)
├── schema.sql                    # Table + analytics views — run once on Neon
├── requirements.txt
├── .env.example
└── .gitignore
```

## How it works end to end

1. **Every 15 minutes**, a GitHub Actions runner spins up, checks out this
   repo, installs dependencies, and runs `main.py`.
2. `main.py` calls `ingestion.py`, which requests current aircraft state
   vectors from OpenSky, scoped to a South Asia bounding box
   (`lamin=5, lomin=68, lamax=30, lomax=92`) — chosen to capture meaningful
   traffic (domestic India/Sri Lanka/Bangladesh flights plus major
   Europe↔Asia overflight corridors) while keeping storage well within
   Neon's free-tier limit.
3. `cleaning.py` validates and normalizes the batch: drops records missing
   `icao24` (the stable aircraft identifier — not `callsign`, which is
   frequently blank), nulls out physically implausible coordinates or
   altitudes rather than trusting the API blindly, and drops exact
   duplicate `(icao24, last_contact)` pairs.
4. `database.py` bulk-inserts the cleaned batch into `flight_positions`,
   then deletes any rows older than 7 days in the same run — a genuine,
   self-managing retention policy, not a manual chore.
5. `dashboard.py`, deployed separately on Streamlit Community Cloud, reads
   only from SQL views (`v_summary_stats`, `v_hourly_activity`,
   `v_country_breakdown`, `v_latest_positions`, `v_most_seen_aircraft`,
   `v_flight_phase_breakdown`) — never the raw table directly, and never
   writes anything.

The pipeline and the dashboard are two separate deployments that only share
the database — either can be redeployed or restarted independently without
affecting the other.

## Setting this up yourself

### 1. Database (Neon)

Create a Neon project, then run the schema once against it:

```bash
psql "$DATABASE_URL" -f schema.sql
```

This creates `flight_positions` and all six analytics views.

### 2. Local development (optional, for testing changes)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL
python main.py         # run one manual cycle to confirm it works
streamlit run dashboard.py
```

`config.py` loads `.env` automatically via `python-dotenv`, so both `main.py`
and `dashboard.py` pick up `DATABASE_URL` without manually exporting it.

### 3. Scheduler (GitHub Actions)

1. Push this repo to GitHub.
2. In **Settings → Secrets and variables → Actions**, add a repository
   secret named `DATABASE_URL` with your Neon connection string.
   (`OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` are optional — the
   pipeline works fine on OpenSky's anonymous tier at a 15-minute interval.)
3. The workflow at `.github/workflows/pipeline.yml` runs automatically
   every 15 minutes, and can also be triggered manually from the **Actions**
   tab (`workflow_dispatch`) for testing.

### 4. Dashboard (Streamlit Community Cloud)

1. Go to [share.streamlit.io](https://share.streamlit.io) → **Create app**
   → **Deploy a public app from GitHub**.
2. Point it at this repo, branch `main`, main file `dashboard.py`.
3. Under **Advanced settings → Secrets**, add:
   ```toml
   DATABASE_URL = "postgresql://user:password@host/db?sslmode=require"
   ```
4. Deploy. The resulting public URL updates automatically as the pipeline
   writes new data — no redeploy needed for new rows, only for code changes.

## Design notes

- **Identity:** `icao24` is used as the aircraft identifier throughout, not
  `callsign` — callsigns are frequently blank or inconsistent; `icao24` is
  the stable 24-bit transponder address.
- **Append-only:** the pipeline only ever `INSERT`s and `DELETE`s-by-age. It
  never `UPDATE`s a row, which is what makes it safe to run unattended and
  safe to re-run after a failure without corrupting prior data.
- **Retention:** every run deletes rows older than 7 days
  (`RETENTION_DAYS` in `config.py`), keyed off `last_contact` (when the
  data was true), not `ingested_at` (when the pipeline happened to fetch it).
- **Analytics live in SQL, not Python:** the dashboard never aggregates
  data itself — it queries pre-built views, so the same aggregation logic
  isn't duplicated between the app layer and the database layer.
- **Map rendering:** the dashboard's map uses Plotly `Scattergeo`, which
  draws coastlines/borders from data bundled in the browser, rather than a
  tile-server-dependent basemap — avoids a class of failures where the map
  silently renders blank if an external tile request is blocked.
- **Failure handling:** a failed OpenSky request or database error is
  logged and the run exits cleanly rather than crashing — the next
  scheduled run 15 minutes later simply tries again.

## What was deliberately left out of V1

- No AI/LLM anywhere in the pipeline — this is a data engineering project,
  not an AI-wrapper project.
- No richer OpenSky endpoints (departure/arrival airports) — state vectors
  alone give enough for meaningful analytics without the added complexity
  and tighter rate limits of the flights endpoint.
- No message queue / streaming architecture — polling on a fixed interval
  is the right amount of complexity for this data volume and use case.

## Roadmap (not built, on purpose — ideas for a V2+)

- Migrate from Neon free tier to a larger managed instance if the bounding
  box or retention window grows.
- Add automated tests for `cleaning.py`'s validation rules.
- Add a rollup job that compresses old raw snapshots into hourly aggregates
  before they age out, to preserve longer-term trends beyond 7 days without
  keeping full-resolution history forever.
- Anomaly detection on top of the historical table (e.g. unusual
  altitude/velocity combinations).

V1's goal was deliberately narrow: a reliable, unattended, cloud-deployed
pipeline with a real historical dataset behind it — not a maximal feature
list.

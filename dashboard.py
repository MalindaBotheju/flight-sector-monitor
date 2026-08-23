"""
Dashboard — the presentation layer only.

This file does NOT do any ETL, cleaning, or writing. It only reads from
the SQL views defined in schema.sql. All aggregation logic lives in SQL,
not here — this keeps the dashboard fast and the analytics logic in one
place (the database), not duplicated between SQL and Python.

Run with: streamlit run dashboard.py
"""

import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st

import config

# ---------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Flight Sector Monitor",
    page_icon="✈",
    layout="wide",
)

AMBER = "#FF8C42"
SKY_BLUE = "#4FA8D8"
TEXT_MUTED = "#6B7488"
PANEL = "#141B2E"
BG = "#0A0E1A"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', sans-serif;
}}

.eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.15em;
    color: {AMBER};
    text-transform: uppercase;
    margin-bottom: 0.2rem;
}}

.page-title {{
    font-size: 1.9rem;
    font-weight: 600;
    color: #E8ECF4;
    margin-bottom: 0;
}}

.page-subtitle {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    color: {TEXT_MUTED};
    margin-top: 0.3rem;
    margin-bottom: 1.6rem;
}}

.kpi-card {{
    background-color: {PANEL};
    border: 1px solid #212B42;
    border-radius: 6px;
    padding: 1rem 1.2rem;
}}

.kpi-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {TEXT_MUTED};
    margin-bottom: 0.4rem;
}}

.kpi-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.7rem;
    font-weight: 700;
    color: {AMBER};
}}

.section-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {TEXT_MUTED};
    border-bottom: 1px solid #212B42;
    padding-bottom: 0.4rem;
    margin: 1.6rem 0 0.8rem 0;
}}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------
# Data access — cached so the dashboard doesn't hammer the DB
# ---------------------------------------------------------------
@st.cache_data(ttl=120)
def load_view(view_name: str) -> pd.DataFrame:
    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        return pd.read_sql(f"SELECT * FROM {view_name}", conn)
    finally:
        conn.close()


def try_load(view_name: str) -> pd.DataFrame:
    try:
        return load_view(view_name)
    except Exception as e:
        st.error(f"Could not load `{view_name}`: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------
# Header
# ---------------------------------------------------------------
st.markdown('<div class="eyebrow">Live Sector Feed · South Asia</div>', unsafe_allow_html=True)
st.markdown('<div class="page-title">Flight Sector Monitor</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-subtitle">lat 5°N–30°N · lon 68°E–92°E &nbsp;|&nbsp; '
    '7-day rolling window &nbsp;|&nbsp; refreshed every 15 min</div>',
    unsafe_allow_html=True,
)

summary = try_load("v_summary_stats")

if summary.empty or summary.iloc[0]["unique_aircraft_7d"] is None:
    st.warning(
        "No data yet. Run `python main.py` at least once (or wait for the "
        "scheduled job to fire) before loading the dashboard."
    )
    st.stop()

row = summary.iloc[0]

# ---------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------
kpi_cols = st.columns(5)
kpis = [
    ("Unique Aircraft (7d)", f"{int(row['unique_aircraft_7d']):,}"),
    ("Observations (7d)", f"{int(row['total_observations_7d']):,}"),
    ("Countries Seen", f"{int(row['countries_seen'])}"),
    ("Avg Altitude", f"{int(row['avg_altitude_m']):,} m" if row["avg_altitude_m"] else "—"),
    ("Avg Velocity", f"{row['avg_velocity_ms']:.0f} m/s" if row["avg_velocity_ms"] else "—"),
]
for col, (label, value) in zip(kpi_cols, kpis):
    col.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
    </div>
    """, unsafe_allow_html=True)

last_ingested_local = pd.to_datetime(row["last_ingested_at"]).tz_convert("Asia/Colombo")
st.markdown(
    f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
    f'color:{TEXT_MUTED};margin-top:0.6rem;">'
    f'last ingested · {last_ingested_local.strftime("%Y-%m-%d %H:%M:%S")} (Colombo time)</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------
# Map — latest known position of every aircraft in the window
# ---------------------------------------------------------------
st.markdown(
    f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;'
    f'color:{TEXT_MUTED};margin-bottom:0.6rem;">'
    f'Each dot is one aircraft\'s most recent known position in the 7-day window. '
    f'Color = altitude (dark → light amber = low → high).</div>',
    unsafe_allow_html=True,
)

positions = try_load("v_latest_positions")
if not positions.empty:
    positions = positions.dropna(subset=["latitude", "longitude"])
    positions["callsign_display"] = positions["callsign"].fillna("Unknown callsign")
    positions["country_display"] = positions["origin_country"].fillna("Unknown country")
    positions["altitude_display"] = positions["baro_altitude"].fillna(0)

    fig = go.Figure(go.Scattergeo(
        lat=positions["latitude"],
        lon=positions["longitude"],
        mode="markers",
        marker=dict(
            size=8,
            color=positions["altitude_display"],
            colorscale=[[0, "#5A3A22"], [0.5, AMBER], [1, "#FFD9A8"]],
            showscale=True,
            colorbar=dict(
                title=dict(text="altitude (m)", font=dict(color="#E8ECF4", size=10)),
                tickfont=dict(color="#E8ECF4", size=9),
                len=0.7,
            ),
            line=dict(width=0),
        ),
        customdata=positions[["callsign_display", "country_display", "altitude_display"]],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "%{customdata[1]}<br>"
            "altitude: %{customdata[2]:,.0f} m"
            "<extra></extra>"
        ),
    ))
    fig.update_geos(
        showcountries=True, countrycolor="#3A4560",
        showcoastlines=True, coastlinecolor="#3A4560",
        showland=True, landcolor="#141B2E",
        showocean=True, oceancolor=BG,
        showlakes=False,
        lataxis_range=[3, 32],
        lonaxis_range=[65, 95],
        projection_type="mercator",
        bgcolor=BG,
    )
    fig.update_layout(
        paper_bgcolor=BG,
        margin=dict(l=0, r=0, t=0, b=0),
        height=460,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No position data available yet.")

# ---------------------------------------------------------------
# Charts row
# ---------------------------------------------------------------
st.markdown('<div class="section-label">Activity &amp; Composition</div>', unsafe_allow_html=True)
st.markdown(
    f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.75rem;'
    f'color:{TEXT_MUTED};margin-bottom:0.6rem;">'
    f'How much traffic the sector sees over time, and where the aircraft are registered. '
    f'Needs a few hours of history to look meaningful.</div>',
    unsafe_allow_html=True,
)
chart_col1, chart_col2 = st.columns(2)

PLOTLY_LAYOUT = dict(
    paper_bgcolor=PANEL,
    plot_bgcolor=PANEL,
    font=dict(family="Inter", color="#E8ECF4", size=12),
    margin=dict(l=10, r=10, t=30, b=10),
)

with chart_col1:
    hourly = try_load("v_hourly_activity")
    if not hourly.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hourly["hour_bucket"], y=hourly["unique_aircraft"],
            mode="lines", line=dict(color=AMBER, width=2),
            fill="tozeroy", fillcolor="rgba(255,140,66,0.12)",
            name="Unique aircraft",
        ))
        fig.update_layout(
            title="Unique Aircraft by Hour",
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor="#212B42"),
            **PLOTLY_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No hourly activity data yet.")

with chart_col2:
    countries = try_load("v_country_breakdown").head(10)
    if not countries.empty:
        fig = go.Figure(go.Bar(
            x=countries["unique_aircraft"],
            y=countries["origin_country"],
            orientation="h",
            marker_color=SKY_BLUE,
        ))
        fig.update_layout(
            title="Top Countries by Aircraft Registered",
            xaxis=dict(showgrid=True, gridcolor="#212B42"),
            yaxis=dict(autorange="reversed"),
            **PLOTLY_LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No country data yet.")

# ---------------------------------------------------------------
# Flight phase + most-seen table
# ---------------------------------------------------------------
phase_col, table_col = st.columns([1, 2])

with phase_col:
    st.markdown(
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
        f'color:{TEXT_MUTED};margin-bottom:0.4rem;">'
        f'What aircraft in the sector are doing right now: cruising level, '
        f'climbing after takeoff, descending toward landing, or parked on the ground.</div>',
        unsafe_allow_html=True,
    )
    phases = try_load("v_flight_phase_breakdown")
    if not phases.empty:
        colors = {"cruising": AMBER, "climbing": SKY_BLUE, "descending": "#8B7CD8", "on_ground": TEXT_MUTED}
        fig = go.Figure(go.Pie(
            labels=phases["flight_phase"],
            values=phases["observations"],
            hole=0.55,
            marker=dict(colors=[colors.get(p, TEXT_MUTED) for p in phases["flight_phase"]]),
        ))
        fig.update_layout(title="Flight Phase Mix", **PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

with table_col:
    st.markdown('<div class="section-label">Most Frequently Observed Aircraft</div>', unsafe_allow_html=True)
    most_seen = try_load("v_most_seen_aircraft")
    if not most_seen.empty:
        st.dataframe(
            most_seen.rename(columns={
                "icao24": "ICAO24", "callsign": "Callsign",
                "origin_country": "Country", "observations": "Observations",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No aircraft observations yet.")

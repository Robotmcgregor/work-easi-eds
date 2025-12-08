#!/usr/bin/env python
"""
NEW EDS Dashboard (preferred tiles + detections) with QC form added
- Keeps the working map, tiles and charts from new_dashboard.py
- Adds a QC panel (detection dropdown, polygon preview, decision + confidence slider, comments)
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output, State, callback
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta
    import logging
    from shapely.geometry import shape
    import threading

    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile, ProcessingJob
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.database.qc_models import QCValidation, QCAuditLog
    from src.config.settings import get_config
    from src.processing.pipeline import EDSPipelineManager, ProcessingConfig
    from sqlalchemy import func

    # Initialize Dash app with external stylesheets
    app = dash.Dash(
        __name__,
        title="EDS - Validate Detections Dashboard",
        external_stylesheets=["https://codepen.io/chriddyp/pen/bWLwgP.css"],
    )

    # Build/version tag to verify freshness in UI
    BUILD_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Define the layout
    app.layout = html.Div(
        [
            # Header
            html.Div(
                [
                    html.H1(
                        "🛰️ EDS - Validate Detections Dashboard",
                        style={
                            "textAlign": "center",
                            "color": "#2c3e50",
                            "marginBottom": 10,
                        },
                    ),
                    html.P(
                        "Working tiles + detections + QC form",
                        style={
                            "textAlign": "center",
                            "color": "#7f8c8d",
                            "marginBottom": 20,
                        },
                    ),
                    html.Div(
                        [
                            html.Span(
                                f"Build: {BUILD_TS}", style={"marginRight": "15px"}
                            ),
                            html.Span("Port: 8055"),
                        ],
                        style={
                            "textAlign": "center",
                            "color": "#95a5a6",
                            "fontSize": "12px",
                        },
                    ),
                ]
            ),
            # Hidden version markers for auto-reload
            html.Div(id="build-version", children=BUILD_TS, style={"display": "none"}),
            dcc.Store(id="version-store"),
            # Metrics row (same as new_dashboard)
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="total-tiles-display",
                                        children="...",
                                        style={"margin": 0, "color": "#2c3e50"},
                                    ),
                                    html.P(
                                        "Total Tiles",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                className="metric-box",
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="processed-tiles-display",
                                        children="...",
                                        style={"margin": 0, "color": "#2c3e50"},
                                    ),
                                    html.P(
                                        id="processed-tiles-label",
                                        children="Latest Run",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                className="metric-box",
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="total-detections-display",
                                        children="...",
                                        style={"margin": 0, "color": "#2c3e50"},
                                    ),
                                    html.P(
                                        "Total Detections",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                className="metric-box",
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="cleared-areas-display",
                                        children="...",
                                        style={"margin": 0, "color": "#2c3e50"},
                                    ),
                                    html.P(
                                        "Confirmed Clearing",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                className="metric-box",
                            ),
                        ],
                        className="three columns",
                    ),
                ],
                className="row",
                style={"marginBottom": 30},
            ),
            # Charts row (same as new_dashboard)
            html.Div(
                [
                    html.Div(
                        [dcc.Graph(id="nvms-runs-chart")], className="six columns"
                    ),
                    html.Div([dcc.Graph(id="timeline-chart")], className="six columns"),
                ],
                className="row",
                style={"marginBottom": 20},
            ),
            # Map + QC row
            html.Div(
                [
                    # Left: map controls + map
                    html.Div(
                        [
                            html.Label(
                                "Map Style:",
                                style={"marginRight": 10, "fontWeight": "bold"},
                            ),
                            dcc.RadioItems(
                                id="map-style-selector",
                                options=[
                                    {
                                        "label": " 🗺️ Street Map",
                                        "value": "open-street-map",
                                    },
                                    {"label": " 🛰️ Satellite", "value": "satellite"},
                                    {"label": " 🌍 Terrain", "value": "stamen-terrain"},
                                ],
                                value="open-street-map",
                                inline=True,
                                style={"marginLeft": 10},
                            ),
                            html.Label(
                                "Show Detections:",
                                style={
                                    "marginLeft": 30,
                                    "marginRight": 10,
                                    "fontWeight": "bold",
                                },
                            ),
                            dcc.Checklist(
                                id="show-detections",
                                options=[{"label": " Detections", "value": "show"}],
                                value=["show"],
                                inline=True,
                            ),
                            html.Label(
                                "All Tiles:",
                                style={
                                    "marginLeft": 30,
                                    "marginRight": 10,
                                    "fontWeight": "bold",
                                },
                            ),
                            dcc.Checklist(
                                id="show-all-tiles",
                                options=[{"label": " Show base grid", "value": "show"}],
                                value=["show"],
                                inline=True,
                            ),
                            html.Div(
                                [
                                    dcc.Graph(
                                        id="main-map-display", style={"height": "600px"}
                                    )
                                ],
                                style={"marginTop": 10},
                            ),
                        ],
                        className="seven columns",
                    ),
                    # Right: QC panel
                    html.Div(
                        [
                            html.H3(
                                "🎯 Quality Control Review", style={"color": "#2c3e50"}
                            ),
                            html.Label(
                                "Select Detection:", style={"fontWeight": "bold"}
                            ),
                            dcc.Dropdown(
                                id="qc-detection-dropdown",
                                placeholder="Choose a detection...",
                            ),
                            html.Div(id="qc-detection-info", style={"marginTop": 10}),
                            html.Hr(),
                            html.Label("Reviewer:", style={"fontWeight": "bold"}),
                            dcc.Input(
                                id="qc-reviewer",
                                type="text",
                                placeholder="Your name...",
                                style={"width": "100%", "marginBottom": "10px"},
                            ),
                            html.Label("Decision:", style={"fontWeight": "bold"}),
                            dcc.RadioItems(
                                id="qc-decision",
                                options=[
                                    {"label": " ✅ Confirm", "value": "confirmed"},
                                    {"label": " ❌ Reject", "value": "rejected"},
                                    {"label": " ⚠️ Review", "value": "requires_review"},
                                ],
                                style={"marginBottom": "10px"},
                            ),
                            html.Label(
                                "Confidence (1-5):", style={"fontWeight": "bold"}
                            ),
                            dcc.Slider(
                                id="qc-confidence",
                                min=1,
                                max=5,
                                step=1,
                                value=3,
                                marks={i: f"{i}" for i in range(1, 6)},
                                tooltip={"placement": "bottom", "always_visible": True},
                            ),
                            html.Label(
                                "Comments:",
                                style={"fontWeight": "bold", "marginTop": "10px"},
                            ),
                            dcc.Textarea(
                                id="qc-comments",
                                style={
                                    "width": "100%",
                                    "height": 80,
                                    "marginBottom": "10px",
                                },
                            ),
                            html.Button(
                                "💾 Submit Review",
                                id="qc-submit",
                                n_clicks=0,
                                style={
                                    "backgroundColor": "#27ae60",
                                    "color": "white",
                                    "border": "none",
                                    "padding": "10px 20px",
                                    "borderRadius": "4px",
                                },
                            ),
                            html.Div(id="qc-submit-status", style={"marginTop": 8}),
                        ],
                        className="five columns",
                        style={
                            "backgroundColor": "white",
                            "padding": 15,
                            "borderRadius": 8,
                            "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                        },
                    ),
                ],
                className="row",
            ),
            # Run EDS row
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("⚙️ Run EDS", style={"color": "#2c3e50"}),
                            html.Label(
                                "Tile ID (PathRow):", style={"fontWeight": "bold"}
                            ),
                            dcc.Input(
                                id="eds-tile-id",
                                type="text",
                                placeholder="e.g., 090084",
                                style={"width": "200px", "marginRight": "10px"},
                            ),
                            html.Br(),
                            html.Br(),
                            html.Label("Date Range:", style={"fontWeight": "bold"}),
                            dcc.DatePickerRange(
                                id="eds-date-range", display_format="YYYY-MM-DD"
                            ),
                            html.Br(),
                            html.Br(),
                            html.Label(
                                "Confidence threshold:", style={"fontWeight": "bold"}
                            ),
                            dcc.Slider(
                                id="eds-confidence",
                                min=0.5,
                                max=0.95,
                                step=0.05,
                                value=0.7,
                                marks={
                                    v: f"{v:.2f}"
                                    for v in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
                                },
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": False,
                                },
                            ),
                            html.Br(),
                            html.Button(
                                "▶️ Run EDS",
                                id="eds-run-btn",
                                n_clicks=0,
                                style={
                                    "backgroundColor": "#2980b9",
                                    "color": "white",
                                    "border": "none",
                                    "padding": "10px 16px",
                                    "borderRadius": "4px",
                                },
                            ),
                            html.Div(id="eds-run-status", style={"marginTop": 8}),
                        ],
                        className="six columns",
                        style={
                            "backgroundColor": "white",
                            "padding": 15,
                            "borderRadius": 8,
                            "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                        },
                    ),
                    html.Div(
                        [
                            html.H3(
                                "🧾 Recent Processing Jobs", style={"color": "#2c3e50"}
                            ),
                            html.Div(id="eds-recent-jobs"),
                        ],
                        className="six columns",
                    ),
                ],
                className="row",
                style={"marginTop": 20},
            ),
            # Update interval
            dcc.Interval(id="refresh-interval", interval=30000, n_intervals=0),
        ],
        className="container-fluid",
        style={
            "fontFamily": "Arial, sans-serif",
            "backgroundColor": "#f8f9fa",
            "padding": "20px",
        },
    )

    # Custom CSS
    app.index_string = """
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
                .metric-box { background: white; border-radius: 8px; padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 10px; border-left: 4px solid #3498db; }
            </style>
        </head>
        <body>
            {%app_entry%}
            <footer>
                {%config%}
                {%scripts%}
                {%renderer%}
            </footer>
        </body>
    </html>
    """

    # Auto-reload the page if the server build version changes
    app.clientside_callback(
        """
        function(serverVersion, previousVersion){
            if (previousVersion && serverVersion !== previousVersion) {
                // Force a hard reload to refresh Dash callback map
                setTimeout(function(){ location.reload(true); }, 100);
            }
            return serverVersion;
        }
        """,
        Output("version-store", "data"),
        Input("build-version", "children"),
        State("version-store", "data"),
    )

    # --- Callbacks (metrics/charts) copied from new_dashboard ---
    @app.callback(
        Output("total-tiles-display", "children"),
        Output("processed-tiles-display", "children"),
        Output("total-detections-display", "children"),
        Output("cleared-areas-display", "children"),
        Input("refresh-interval", "n_intervals"),
        Input("qc-submit", "n_clicks"),
    )
    def update_metrics(_n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                from sqlalchemy import func

                total_tiles = session.query(LandsatTile).count()
                # Latest run by run_number (fallback to created_at)
                latest_run = (
                    session.query(NVMSRun)
                    .order_by(NVMSRun.run_number.desc(), NVMSRun.created_at.desc())
                    .first()
                )
                processed_tiles = 0
                if latest_run:
                    # Count distinct tiles processed in the latest run
                    processed_tiles = (
                        session.query(func.count(func.distinct(NVMSResult.tile_id)))
                        .filter(NVMSResult.run_id == latest_run.run_id)
                        .scalar()
                        or 0
                    )
                # Only count detections where IsClearing='y'
                total_detections = (
                    session.query(NVMSDetection)
                    .filter(NVMSDetection.properties["IsClearing"].astext == "y")
                    .count()
                )
                # Count unique detections confirmed via QC
                confirmed_detections = (
                    session.query(
                        func.count(func.distinct(QCValidation.nvms_detection_id))
                    )
                    .filter(QCValidation.qc_status == "confirmed")
                    .scalar()
                    or 0
                )
                cleared_areas = confirmed_detections
                return (
                    f"{total_tiles:,}",
                    f"{processed_tiles:,}",
                    f"{total_detections:,}",
                    f"{cleared_areas:,}",
                )
        except Exception as e:
            logger.error(f"metrics error: {e}")
            return "-", "-", "-", "-"

    @app.callback(
        Output("processed-tiles-label", "children"),
        Input("refresh-interval", "n_intervals"),
        Input("qc-submit", "n_clicks"),
    )
    def update_latest_run_label(_n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                latest_run = (
                    session.query(NVMSRun)
                    .order_by(NVMSRun.run_number.desc(), NVMSRun.created_at.desc())
                    .first()
                )
                if latest_run:
                    if getattr(latest_run, "run_number", None) is not None:
                        return f"Latest Run (Run {latest_run.run_number})"
                    return f"Latest Run ({latest_run.run_id})"
                return "Latest Run"
        except Exception as e:
            logger.error(f"latest run label error: {e}")
            return "Latest Run"

    @app.callback(
        Output("nvms-runs-chart", "figure"),
        Output("timeline-chart", "figure"),
        Input("refresh-interval", "n_intervals"),
        Input("qc-submit", "n_clicks"),
    )
    def update_charts(_n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                # Recent runs by created_at
                runs = (
                    session.query(NVMSRun)
                    .order_by(NVMSRun.created_at.desc())
                    .limit(10)
                    .all()
                )
                # Count tiles processed per run using NVMSResult
                run_rows = []
                if runs:
                    for r in runs:
                        cnt = (
                            session.query(NVMSResult)
                            .filter(NVMSResult.run_id == r.run_id)
                            .count()
                        )
                        run_rows.append(
                            {"run_id": r.run_id, "date": r.created_at, "tiles": cnt}
                        )
                runs_df = (
                    pd.DataFrame(run_rows)
                    if run_rows
                    else pd.DataFrame(columns=["run_id", "date", "tiles"])
                )
                runs_fig = (
                    px.bar(
                        runs_df, x="run_id", y="tiles", title="Tiles Processed per Run"
                    )
                    if not runs_df.empty
                    else go.Figure()
                )

                # Detections over time (last 90 days)
                from datetime import timezone

                end_date = datetime.now(timezone.utc).date()
                start_date = end_date - timedelta(days=90)
                tl = go.Figure()
                try:
                    from sqlalchemy import func

                    day_col = func.date_trunc("day", NVMSDetection.imported_at)
                    rows = (
                        session.query(day_col.label("day"), func.count().label("cnt"))
                        .filter(NVMSDetection.imported_at >= start_date)
                        .group_by("day")
                        .order_by("day")
                        .all()
                    )
                    if rows:
                        df = pd.DataFrame(rows, columns=["day", "cnt"])
                        df["day"] = pd.to_datetime(df["day"]).dt.date
                        # Ensure continuous date axis with zeros for missing days
                        full_range = pd.date_range(
                            start=start_date, end=end_date, freq="D"
                        )
                        df_full = pd.DataFrame({"day": full_range.date})
                        df = df_full.merge(df, on="day", how="left").fillna({"cnt": 0})
                        tl = px.bar(
                            df,
                            x="day",
                            y="cnt",
                            title="Detections over Time (last 90 days)",
                        )
                except Exception:
                    # Fallback: count in Python
                    times = [
                        t[0]
                        for t in session.query(NVMSDetection.imported_at)
                        .filter(
                            NVMSDetection.imported_at >= start_date,
                            NVMSDetection.properties["IsClearing"].astext == "y",
                        )
                        .all()
                        if t[0]
                    ]
                    if times:
                        dts = pd.to_datetime(times)
                        df = pd.DataFrame({"day": dts.date})
                        s = df.groupby("day").size()
                        full_range = pd.date_range(
                            start=start_date, end=end_date, freq="D"
                        ).date
                        s = s.reindex(full_range, fill_value=0)
                        tl = px.bar(
                            x=list(s.index),
                            y=list(s.values),
                            title="Detections over Time (last 90 days)",
                        )
                return runs_fig, tl
        except Exception as e:
            logger.error(f"charts error: {e}")
            return go.Figure(), go.Figure()

    @app.callback(
        Output("main-map-display", "figure"),
        Input("map-style-selector", "value"),
        Input("show-detections", "value"),
        Input("show-all-tiles", "value"),
        Input("refresh-interval", "n_intervals"),
        Input("qc-submit", "n_clicks"),
    )
    def make_map(map_style, show_detections, show_all_tiles, _n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                fig = go.Figure()

                # Base layer: all Landsat tiles (light gray) to visualize never-run tiles (toggle)
                if "show" in (show_all_tiles or []):
                    try:
                        all_tiles = session.query(LandsatTile).limit(1000).all()
                        added = False
                        for tile in all_tiles:
                            if not tile.bounds_geojson:
                                continue
                            try:
                                bounds = json.loads(tile.bounds_geojson)
                                coords = bounds["coordinates"][0]
                                lons = [c[0] for c in coords]
                                lats = [c[1] for c in coords]
                                # Show PathRow on hover for all tiles
                                pr = None
                                try:
                                    pr = f"{int(tile.path):03d}{int(tile.row):03d}"
                                except Exception:
                                    pr = str(getattr(tile, "tile_id", ""))
                                fig.add_trace(
                                    go.Scattermapbox(
                                        mode="lines",
                                        lon=lons,
                                        lat=lats,
                                        line=dict(
                                            width=1, color="rgba(120,120,120,0.4)"
                                        ),
                                        name="All Tiles" if not added else None,
                                        showlegend=not added,
                                        customdata=[pr] * len(lons),
                                        hovertemplate="PathRow: %{customdata}<extra></extra>",
                                    )
                                )
                                added = True
                            except Exception:
                                continue
                    except Exception:
                        pass

                # Color-coded tiles per NVMS run using NVMSResult.tile_id
                run_ids = [
                    r.run_id
                    for r in session.query(NVMSRun)
                    .order_by(NVMSRun.run_number.asc())
                    .all()
                ]
                palette = [
                    "#e74c3c",
                    "#e67e22",
                    "#f1c40f",
                    "#2ecc71",
                    "#3498db",
                    "#9b59b6",
                ]
                color_for = {
                    rid: palette[i % len(palette)] for i, rid in enumerate(run_ids)
                }
                for rid in run_ids:
                    # Get distinct tile_ids for this run
                    tile_ids = [
                        t[0]
                        for t in session.query(NVMSResult.tile_id)
                        .filter(NVMSResult.run_id == rid)
                        .distinct()
                        .all()
                    ]
                    if not tile_ids:
                        continue
                    # Limit to reasonable number for performance
                    tile_ids = tile_ids[:120]
                    tiles = (
                        session.query(LandsatTile)
                        .filter(LandsatTile.tile_id.in_(tile_ids))
                        .all()
                    )
                    added_legend = False
                    for tile in tiles:
                        try:
                            if tile.bounds_geojson:
                                bounds = json.loads(tile.bounds_geojson)
                                coords = bounds["coordinates"][0]
                                lons = [c[0] for c in coords]
                                lats = [c[1] for c in coords]
                                pr = f"{int(tile.path):03d}{int(tile.row):03d}"
                                fig.add_trace(
                                    go.Scattermapbox(
                                        mode="lines",
                                        lon=lons,
                                        lat=lats,
                                        line=dict(width=2, color=color_for[rid]),
                                        name=rid if not added_legend else None,
                                        showlegend=not added_legend,
                                        customdata=[pr] * len(lons),
                                        hovertemplate=f"Run: {rid}<br>PathRow: %{{customdata}}<extra></extra>",
                                    )
                                )
                                added_legend = True
                            else:
                                # fallback to center point marker
                                pr = f"{int(tile.path):03d}{int(tile.row):03d}"
                                fig.add_trace(
                                    go.Scattermapbox(
                                        lat=[tile.center_lat],
                                        lon=[tile.center_lon],
                                        mode="markers",
                                        marker=dict(
                                            size=6, color=color_for[rid], opacity=0.7
                                        ),
                                        name=rid if not added_legend else None,
                                        showlegend=not added_legend,
                                        customdata=[pr],
                                        hovertemplate=f"Run: {rid}<br>PathRow: %{{customdata}}<extra></extra>",
                                    )
                                )
                                added_legend = True
                        except Exception:
                            continue

                # Detections colored by QC status (only IsClearing='y')
                if "show" in (show_detections or []):
                    detections = (
                        session.query(NVMSDetection)
                        .filter(NVMSDetection.properties["IsClearing"].astext == "y")
                        .order_by(NVMSDetection.id.desc())
                        .limit(2000)
                        .all()
                    )
                    if detections:
                        # Build map of latest QC status by detection
                        det_ids = [d.id for d in detections]
                        qcs = (
                            session.query(QCValidation)
                            .filter(QCValidation.nvms_detection_id.in_(det_ids))
                            .all()
                        )
                        latest = {}
                        for q in qcs:
                            key = q.nvms_detection_id
                            ts = q.reviewed_at or q.created_at
                            if key not in latest or (
                                ts and (latest[key][1] is None or ts > latest[key][1])
                            ):
                                latest[key] = (q.qc_status or "pending", ts)

                        buckets = {
                            "confirmed": {"lat": [], "lon": [], "tile": []},
                            "rejected": {"lat": [], "lon": [], "tile": []},
                            "requires_review": {"lat": [], "lon": [], "tile": []},
                            "other": {"lat": [], "lon": [], "tile": []},
                        }

                        for det in detections:
                            if not det.geom_geojson:
                                continue
                            try:
                                geom = (
                                    shape(det.geom_geojson)
                                    if isinstance(det.geom_geojson, dict)
                                    else shape(json.loads(det.geom_geojson))
                                )
                                c = geom.centroid
                                status = latest.get(det.id, ("pending", None))[0]
                                status = (status or "pending").lower()
                                if status in (
                                    "confirmed",
                                    "rejected",
                                    "requires_review",
                                ):
                                    bucket = status
                                else:
                                    bucket = "other"
                                buckets[bucket]["lat"].append(c.y)
                                buckets[bucket]["lon"].append(c.x)
                                buckets[bucket]["tile"].append(det.tile_id)
                            except Exception:
                                continue

                        # Add traces per bucket
                        colors = {
                            "confirmed": "#2ecc71",
                            "rejected": "#e74c3c",
                            "requires_review": "#f1c40f",
                            "other": "blue",
                        }
                        names = {
                            "confirmed": "Detections (Confirmed)",
                            "rejected": "Detections (Rejected)",
                            "requires_review": "Detections (Review)",
                            "other": "Detections",
                        }
                        for key in [
                            "confirmed",
                            "rejected",
                            "requires_review",
                            "other",
                        ]:
                            data = buckets[key]
                            if data["lat"]:
                                fig.add_trace(
                                    go.Scattermapbox(
                                        lat=data["lat"],
                                        lon=data["lon"],
                                        mode="markers",
                                        marker=dict(
                                            size=5, color=colors[key], opacity=0.7
                                        ),
                                        name=names[key],
                                        text=data["tile"],
                                        hovertemplate="<b>Detection</b><br>Tile: %{text}<extra></extra>",
                                    )
                                )

                fig.update_layout(
                    mapbox_style=map_style,
                    mapbox=dict(center=dict(lat=-25, lon=135), zoom=4),
                    height=600,
                    margin=dict(r=0, t=40, l=0, b=0),
                    legend=dict(x=0.02, y=0.98),
                )
                return fig
        except Exception as e:
            logger.error(f"map error: {e}")
            return go.Figure().add_annotation(
                text=f"Map Error: {str(e)}", x=0.5, y=0.5, xref="paper", yref="paper"
            )

    # --- QC callbacks ---
    @app.callback(
        Output("qc-detection-dropdown", "options"),
        Input("refresh-interval", "n_intervals"),
        Input("qc-submit", "n_clicks"),
    )
    def load_qc_options(_n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                # Exclude detections that have already been confirmed or rejected
                from sqlalchemy import select

                subq = select(QCValidation.nvms_detection_id).where(
                    QCValidation.qc_status.in_(["confirmed", "rejected"])
                )
                detections = (
                    session.query(NVMSDetection)
                    .filter(
                        ~NVMSDetection.id.in_(subq),
                        NVMSDetection.properties["IsClearing"].astext == "y",
                    )
                    .order_by(NVMSDetection.id.desc())
                    .limit(50)
                    .all()
                )
                opts = []
                for det in detections:
                    date_str = (
                        det.imported_at.strftime("%Y-%m-%d")
                        if det.imported_at
                        else "Unknown"
                    )
                    opts.append(
                        {
                            "label": f"NVMS #{det.id} - Tile {det.tile_id} ({date_str})",
                            "value": det.id,
                        }
                    )
                return opts
        except Exception as e:
            logger.error(f"qc options error: {e}")
            return [{"label": f"Error: {e}", "value": "error"}]

    @app.callback(
        Output("qc-detection-info", "children"), Input("qc-detection-dropdown", "value")
    )
    def show_qc_detection(det_id):
        if not det_id or det_id == "error":
            return "Select a detection to see details."
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                det = session.query(NVMSDetection).get(det_id)
                if not det:
                    return "Detection not found."
                fig = go.Figure()
                # Render polygon if possible
                try:
                    raw = det.geom_geojson
                    if raw:
                        geom = raw if isinstance(raw, dict) else json.loads(raw)
                        gtype = (geom.get("type") or "").lower()
                        coords = None
                        if gtype == "polygon":
                            coords = geom["coordinates"][0]
                        elif gtype == "multipolygon":
                            coords = geom["coordinates"][0][0]
                        if coords:
                            lons = [p[0] for p in coords] + [coords[0][0]]
                            lats = [p[1] for p in coords] + [coords[0][1]]
                            fig.add_trace(
                                go.Scattermapbox(
                                    lon=lons,
                                    lat=lats,
                                    mode="lines",
                                    fill="toself",
                                    fillcolor="rgba(255,0,0,0.3)",
                                    line=dict(color="red", width=2),
                                )
                            )
                            cx = sum([p[0] for p in coords]) / len(coords)
                            cy = sum([p[1] for p in coords]) / len(coords)
                            fig.update_layout(
                                mapbox=dict(
                                    style="open-street-map",
                                    center=dict(lat=cy, lon=cx),
                                    zoom=15,
                                ),
                                height=280,
                                margin=dict(l=0, r=0, t=20, b=0),
                            )
                        else:
                            # centroid fallback
                            geom_s = shape(geom)
                            c = geom_s.centroid
                            fig.add_trace(
                                go.Scattermapbox(
                                    lon=[c.x],
                                    lat=[c.y],
                                    mode="markers",
                                    marker=dict(size=12, color="red"),
                                )
                            )
                            fig.update_layout(
                                mapbox=dict(
                                    style="open-street-map",
                                    center=dict(lat=c.y, lon=c.x),
                                    zoom=15,
                                ),
                                height=240,
                                margin=dict(l=0, r=0, t=20, b=0),
                            )
                    else:
                        fig.add_annotation(
                            text="No geometry",
                            x=0.5,
                            y=0.5,
                            xref="paper",
                            yref="paper",
                            showarrow=False,
                        )
                except Exception as ge:
                    fig.add_annotation(
                        text=f"Geometry error: {ge}",
                        x=0.5,
                        y=0.5,
                        xref="paper",
                        yref="paper",
                        showarrow=False,
                    )
                info = html.Div(
                    [
                        html.Div(
                            [
                                html.Strong(f"Detection #{det.id}"),
                                html.Br(),
                                f"Tile: {det.tile_id}",
                                html.Br(),
                                f"Imported: {det.imported_at.strftime('%Y-%m-%d') if det.imported_at else 'Unknown'}",
                            ],
                            style={
                                "backgroundColor": "#f8f9fa",
                                "padding": 8,
                                "borderRadius": 6,
                                "marginBottom": 6,
                            },
                        ),
                        html.Div(
                            [
                                html.Strong("🗺️ Polygon Shape Preview:"),
                                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                            ],
                            style={
                                "border": "2px solid #3498db",
                                "borderRadius": "8px",
                                "padding": "8px",
                                "backgroundColor": "#f8f9ff",
                            },
                        ),
                    ]
                )
                return info
        except Exception as e:
            logger.error(f"qc info error: {e}")
            return f"Error: {e}"

    # --- Run EDS callbacks ---
    def _run_eds_background(tile_id: str, start_date, end_date, confidence: float):
        try:
            # Build processing config
            if start_date and end_date:
                cfg = ProcessingConfig(
                    start_date=datetime.fromisoformat(str(start_date)),
                    end_date=datetime.fromisoformat(str(end_date)),
                    confidence_threshold=confidence,
                )
            else:
                cfg = EDSPipelineManager.create_processing_config(
                    days_back=7, confidence_threshold=confidence
                )
            EDSPipelineManager.run_tile_processing(tile_id, cfg)
        except Exception as e:
            logger.error(f"EDS run error for {tile_id}: {e}")

    @app.callback(
        Output("eds-run-status", "children"),
        Input("eds-run-btn", "n_clicks"),
        State("eds-tile-id", "value"),
        State("eds-date-range", "start_date"),
        State("eds-date-range", "end_date"),
        State("eds-confidence", "value"),
    )
    def run_eds(n, tile_id, start_date, end_date, confidence):
        if not n:
            return ""
        if not tile_id:
            return html.Div(
                "Please enter a Tile ID (PathRow).", style={"color": "#e74c3c"}
            )
        try:
            threading.Thread(
                target=_run_eds_background,
                args=(tile_id, start_date, end_date, float(confidence or 0.7)),
                daemon=True,
            ).start()
            return html.Div(
                f"🚀 Started EDS processing for tile {tile_id}.",
                style={"color": "#27ae60"},
            )
        except Exception as e:
            logger.error(f"run_eds callback error: {e}")
            return html.Div(f"Error starting EDS: {e}", style={"color": "#e74c3c"})

    @app.callback(
        Output("eds-date-range", "start_date"),
        Output("eds-date-range", "end_date"),
        Input("eds-tile-id", "value"),
    )
    def autofill_dates(tile_id):
        try:
            from sqlalchemy import func
            from datetime import timezone

            today = datetime.now(timezone.utc).date().isoformat()
            if not tile_id:
                return dash.no_update, today
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                last_dates = []
                # 1) LandsatTile.last_processed
                lt = (
                    session.query(LandsatTile)
                    .filter(LandsatTile.tile_id == tile_id)
                    .first()
                )
                if lt and lt.last_processed:
                    last_dates.append(lt.last_processed)
                # 2) Latest ProcessingJob.completed_at for tile
                try:
                    pj = (
                        session.query(ProcessingJob)
                        .filter(ProcessingJob.tile_id == tile_id)
                        .order_by(
                            ProcessingJob.completed_at.desc().nullslast(),
                            ProcessingJob.created_at.desc(),
                        )
                        .first()
                    )
                    if pj and (pj.completed_at or pj.created_at):
                        last_dates.append(pj.completed_at or pj.created_at)
                except Exception:
                    pass
                # 3) Latest NVMSResult.end_date_dt for tile
                try:
                    nr = (
                        session.query(NVMSResult)
                        .filter(NVMSResult.tile_id == tile_id)
                        .order_by(
                            NVMSResult.end_date_dt.desc().nullslast(),
                            NVMSResult.created_at.desc(),
                        )
                        .first()
                    )
                    if nr and (nr.end_date_dt or nr.created_at):
                        last_dates.append(nr.end_date_dt or nr.created_at)
                except Exception:
                    pass
                if last_dates:
                    start = max(last_dates).date().isoformat()
                    return start, today
                return dash.no_update, today
        except Exception as e:
            logger.error(f"autofill dates error: {e}")
            return dash.no_update, dash.no_update

    def _jobs_table(rows):
        if not rows:
            return html.Div("No recent jobs.")
        header = html.Tr(
            [
                html.Th(h)
                for h in [
                    "Job ID",
                    "Tile",
                    "Status",
                    "Progress %",
                    "Created",
                    "Started",
                    "Completed",
                ]
            ]
        )
        body = []
        for r in rows:
            body.append(
                html.Tr(
                    [
                        html.Td(r.job_id),
                        html.Td(r.tile_id),
                        html.Td(r.status),
                        html.Td(r.progress_percent or 0),
                        html.Td(
                            r.created_at.strftime("%Y-%m-%d %H:%M")
                            if r.created_at
                            else ""
                        ),
                        html.Td(
                            r.started_at.strftime("%Y-%m-%d %H:%M")
                            if r.started_at
                            else ""
                        ),
                        html.Td(
                            r.completed_at.strftime("%Y-%m-%d %H:%M")
                            if r.completed_at
                            else ""
                        ),
                    ]
                )
            )
        return html.Table(
            [header] + body, style={"width": "100%", "borderCollapse": "collapse"}
        )

    @app.callback(
        Output("eds-recent-jobs", "children"),
        Input("refresh-interval", "n_intervals"),
        Input("eds-run-btn", "n_clicks"),
    )
    def update_recent_jobs(_n, _n_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                recents = (
                    session.query(ProcessingJob)
                    .order_by(ProcessingJob.created_at.desc())
                    .limit(10)
                    .all()
                )
                return _jobs_table(recents)
        except Exception as e:
            logger.error(f"recent jobs error: {e}")
            return html.Div(f"Error loading jobs: {e}")

    @app.callback(
        Output("qc-submit-status", "children"),
        Output("qc-reviewer", "value"),
        Output("qc-decision", "value"),
        Output("qc-confidence", "value"),
        Output("qc-comments", "value"),
        Output("qc-detection-dropdown", "value"),
        Input("qc-submit", "n_clicks"),
        State("qc-detection-dropdown", "value"),
        State("qc-reviewer", "value"),
        State("qc-decision", "value"),
        State("qc-confidence", "value"),
        State("qc-comments", "value"),
    )
    def submit_qc(n, det_id, reviewer, decision, confidence, comments):
        if not n:
            return "", reviewer, decision, confidence, comments, dash.no_update
        if not det_id or not reviewer or not decision:
            return (
                html.Div("Please fill in required fields.", style={"color": "#e74c3c"}),
                reviewer,
                decision,
                confidence,
                comments,
                dash.no_update,
            )
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)
            with db.get_session() as session:
                # ensure tile_id is populated from detection
                det = session.query(NVMSDetection).get(det_id)
                det_tile_id = det.tile_id if det and det.tile_id else "unknown"
                qc = QCValidation(
                    nvms_detection_id=det_id,
                    tile_id=det_tile_id,
                    qc_status=decision,
                    reviewed_by=reviewer,
                    reviewed_at=datetime.now(),
                    reviewer_comments=comments or "",
                    confidence_score=confidence,
                    is_confirmed_clearing=(decision == "confirmed"),
                )
                session.add(qc)
                session.commit()
                msg = html.Div(
                    f"✅ Review submitted for detection {det_id}.",
                    style={"color": "#27ae60"},
                )
                return msg, "", None, 3, "", None
        except Exception as e:
            logger.error(f"qc submit error: {e}")
            return (
                html.Div(f"Error: {e}", style={"color": "#e74c3c"}),
                reviewer,
                decision,
                confidence,
                comments,
                dash.no_update,
            )

    # Run the app
    print("🚀 Starting EDS Preferred + QC Dashboard...")
    print("🌐 Navigate to: http://localhost:8055")
    print("📍 Network: http://10.0.0.14:8055")
    print("Press Ctrl+C to stop")

    app.run_server(debug=False, host="0.0.0.0", port=8055)

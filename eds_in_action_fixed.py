#!/usr/bin/env python
"""
EDS IN ACTION Dashboard - Fixed version with working callbacks
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output, State, callback_context
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta
    import logging
    from sqlalchemy import func, text
    import uuid

    # Configure logging
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.database.qc_models import QCValidation, QCAuditLog, QCStatus
    from src.config.settings import get_config

    # Build/instance stamp for cache-busting visibility
    BUILD_STAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    INSTANCE_ID = str(uuid.uuid4())[:8]
    # Allow overriding port via env var for convenience
    import os

    PORT = int(os.environ.get("EDS_PORT", "8058"))

    # Initialize Dash app
    app = dash.Dash(
        __name__,
        title="EDS in Action - Fixed",
        external_stylesheets=["https://codepen.io/chriddyp/pen/bWLwgP.css"],
    )

    # Layout
    app.layout = html.Div(
        [
            # Header
            html.Div(
                [
                    html.H1(
                        "🛰️ EDS IN ACTION - WORKING VERSION",
                        style={
                            "textAlign": "center",
                            "color": "#2c3e50",
                            "marginBottom": 10,
                        },
                    ),
                    html.P(
                        "Early Detection System with Quality Control",
                        style={
                            "textAlign": "center",
                            "color": "#7f8c8d",
                            "marginBottom": 30,
                        },
                    ),
                    html.Div(
                        [
                            html.Small(
                                f"Build: {BUILD_STAMP} | Instance: {INSTANCE_ID} | Port: {PORT} | Add ?v={INSTANCE_ID} to URL to bypass cache",
                                style={"color": "#7f8c8d"},
                            )
                        ],
                        style={"textAlign": "center", "marginBottom": 10},
                    ),
                ]
            ),
            # Basic Metrics row (simplified)
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="basic-tiles-count",
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
                                style={
                                    "background": "white",
                                    "borderRadius": "8px",
                                    "padding": "20px",
                                    "textAlign": "center",
                                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                                    "margin": "10px",
                                    "borderLeft": "4px solid #3498db",
                                },
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="basic-detections-count",
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
                                style={
                                    "background": "white",
                                    "borderRadius": "8px",
                                    "padding": "20px",
                                    "textAlign": "center",
                                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                                    "margin": "10px",
                                    "borderLeft": "4px solid #f39c12",
                                },
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="qc-pending-count",
                                        children="...",
                                        style={"margin": 0, "color": "#e74c3c"},
                                    ),
                                    html.P(
                                        "Pending QC",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                style={
                                    "background": "white",
                                    "borderRadius": "8px",
                                    "padding": "20px",
                                    "textAlign": "center",
                                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                                    "margin": "10px",
                                    "borderLeft": "4px solid #e74c3c",
                                },
                            ),
                        ],
                        className="three columns",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2(
                                        id="qc-confirmed-count",
                                        children="...",
                                        style={"margin": 0, "color": "#27ae60"},
                                    ),
                                    html.P(
                                        "Confirmed",
                                        style={
                                            "margin": "5px 0 0 0",
                                            "color": "#7f8c8d",
                                        },
                                    ),
                                ],
                                style={
                                    "background": "white",
                                    "borderRadius": "8px",
                                    "padding": "20px",
                                    "textAlign": "center",
                                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                                    "margin": "10px",
                                    "borderLeft": "4px solid #27ae60",
                                },
                            ),
                        ],
                        className="three columns",
                    ),
                ],
                className="row",
                style={"marginBottom": 30},
            ),
            # Map controls
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "🗺️ Map Style:",
                                style={"marginRight": 10, "fontWeight": "bold"},
                            ),
                            dcc.RadioItems(
                                id="map-style-radio",
                                options=[
                                    {
                                        "label": " Street Map",
                                        "value": "open-street-map",
                                    },
                                    {"label": " Light Map", "value": "carto-positron"},
                                    {"label": " Dark Map", "value": "carto-darkmatter"},
                                    {"label": " Terrain", "value": "stamen-terrain"},
                                ],
                                value="open-street-map",
                                inline=True,
                                style={"marginLeft": 10},
                            ),
                        ],
                        style={"marginBottom": "15px"},
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Layers:",
                                style={"marginRight": 10, "fontWeight": "bold"},
                            ),
                            dcc.Checklist(
                                id="layer-toggles",
                                options=[
                                    {"label": " Tiles", "value": "tiles"},
                                    {"label": " NVMS", "value": "nvms"},
                                    {"label": " Alerts", "value": "alerts"},
                                ],
                                value=["tiles", "nvms", "alerts"],
                                inline=True,
                                style={"marginLeft": 10},
                            ),
                        ],
                        style={"marginBottom": "10px"},
                    ),
                    html.Div(
                        [
                            html.Button(
                                "🔍 Queensland",
                                id="zoom-qld",
                                n_clicks=0,
                                style={
                                    "marginRight": "10px",
                                    "backgroundColor": "#3498db",
                                    "color": "white",
                                    "border": "none",
                                    "padding": "8px 16px",
                                    "borderRadius": "4px",
                                },
                            ),
                            html.Button(
                                "🌏 Australia",
                                id="zoom-aus",
                                n_clicks=0,
                                style={
                                    "marginRight": "10px",
                                    "backgroundColor": "#27ae60",
                                    "color": "white",
                                    "border": "none",
                                    "padding": "8px 16px",
                                    "borderRadius": "4px",
                                },
                            ),
                            html.Button(
                                "🌍 Wide View",
                                id="zoom-wide",
                                n_clicks=0,
                                style={
                                    "backgroundColor": "#e74c3c",
                                    "color": "white",
                                    "border": "none",
                                    "padding": "8px 16px",
                                    "borderRadius": "4px",
                                },
                            ),
                        ]
                    ),
                ],
                style={
                    "marginBottom": 20,
                    "padding": 15,
                    "backgroundColor": "#f8f9fa",
                    "borderRadius": 8,
                    "border": "1px solid #dee2e6",
                },
            ),
            # Map
            html.Div([dcc.Graph(id="eds-map", style={"height": "700px"})]),
            # Data summary (visibility + counts)
            html.Div(
                [
                    html.H4("ℹ️ Data summary", style={"color": "#2c3e50"}),
                    html.Div(id="data-summary"),
                ],
                style={
                    "marginTop": 20,
                    "padding": 15,
                    "backgroundColor": "#f1f3f5",
                    "borderRadius": 8,
                    "border": "1px solid #dee2e6",
                },
            ),
            # QC Section
            html.Div(
                [
                    html.H2(
                        "🔍 Quality Control Review",
                        style={"color": "#2c3e50", "marginBottom": 20},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H3(
                                        "📋 Detection Review",
                                        style={"color": "#2c3e50"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                "Select Detection:",
                                                style={"fontWeight": "bold"},
                                            ),
                                            dcc.Dropdown(
                                                id="detection-dropdown",
                                                placeholder="Choose detection to review...",
                                                style={"marginBottom": 15},
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        id="detection-info", style={"marginBottom": 20}
                                    ),
                                    # Simple review form
                                    html.Div(
                                        [
                                            html.Label(
                                                "Reviewer:",
                                                style={"fontWeight": "bold"},
                                            ),
                                            dcc.Input(
                                                id="reviewer-input",
                                                type="text",
                                                placeholder="Your name...",
                                                style={
                                                    "width": "100%",
                                                    "marginBottom": "10px",
                                                },
                                            ),
                                            html.Label(
                                                "Decision:",
                                                style={"fontWeight": "bold"},
                                            ),
                                            dcc.RadioItems(
                                                id="decision-radio",
                                                options=[
                                                    {
                                                        "label": " ✅ Confirm",
                                                        "value": "confirmed",
                                                    },
                                                    {
                                                        "label": " ❌ Reject",
                                                        "value": "rejected",
                                                    },
                                                    {
                                                        "label": " ⚠️ Review",
                                                        "value": "requires_review",
                                                    },
                                                ],
                                                style={"marginBottom": "10px"},
                                            ),
                                            html.Label(
                                                "Confidence Level (1-5):",
                                                style={
                                                    "fontWeight": "bold",
                                                    "marginTop": "15px",
                                                },
                                            ),
                                            html.Div(
                                                [
                                                    dcc.Slider(
                                                        id="confidence-slider",
                                                        min=1,
                                                        max=5,
                                                        step=1,
                                                        value=3,
                                                        marks={
                                                            i: f"{i}"
                                                            for i in range(1, 6)
                                                        },
                                                        tooltip={
                                                            "placement": "bottom",
                                                            "always_visible": True,
                                                        },
                                                    )
                                                ],
                                                style={
                                                    "marginBottom": "20px",
                                                    "padding": "10px",
                                                    "border": "1px solid #ddd",
                                                    "borderRadius": "4px",
                                                    "backgroundColor": "#f8f9fa",
                                                },
                                            ),
                                            html.Label(
                                                "Comments:",
                                                style={"fontWeight": "bold"},
                                            ),
                                            dcc.Textarea(
                                                id="comments-input",
                                                placeholder="Optional comments...",
                                                style={
                                                    "width": "100%",
                                                    "height": 80,
                                                    "marginBottom": "10px",
                                                },
                                            ),
                                            html.Button(
                                                "💾 Submit Review",
                                                id="submit-btn",
                                                n_clicks=0,
                                                style={
                                                    "backgroundColor": "#27ae60",
                                                    "color": "white",
                                                    "border": "none",
                                                    "padding": "10px 20px",
                                                    "borderRadius": "4px",
                                                },
                                            ),
                                            html.Div(
                                                id="submit-message",
                                                style={"marginTop": 10},
                                            ),
                                        ]
                                    ),
                                ],
                                className="eight columns",
                            ),
                            html.Div(
                                [
                                    html.H3(
                                        "📊 Recent Reviews", style={"color": "#2c3e50"}
                                    ),
                                    html.Div(id="recent-reviews"),
                                ],
                                className="four columns",
                            ),
                        ],
                        className="row",
                    ),
                ],
                style={
                    "marginTop": 30,
                    "padding": 20,
                    "backgroundColor": "white",
                    "borderRadius": 8,
                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)",
                },
            ),
            # Update interval
            dcc.Interval(id="update-interval", interval=30000, n_intervals=0),
        ],
        style={
            "fontFamily": "Arial, sans-serif",
            "backgroundColor": "#f8f9fa",
            "padding": "20px",
        },
    )

    # Fixed callbacks - separate and simple
    @app.callback(
        [
            Output("basic-tiles-count", "children"),
            Output("basic-detections-count", "children"),
            Output("qc-pending-count", "children"),
            Output("qc-confirmed-count", "children"),
        ],
        [Input("update-interval", "n_intervals")],
    )
    def update_basic_counts(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                tiles = session.query(LandsatTile).count()
                detections = session.query(NVMSDetection).count()

                # QC counts - handle if tables don't exist yet
                try:
                    pending = (
                        session.query(QCValidation)
                        .filter(QCValidation.qc_status == "pending")
                        .count()
                    )
                    confirmed = (
                        session.query(QCValidation)
                        .filter(QCValidation.qc_status == "confirmed")
                        .count()
                    )
                except:
                    pending = 0
                    confirmed = 0

                return str(tiles), f"{detections:,}", str(pending), str(confirmed)

        except Exception as e:
            return "Error", "Error", "Error", "Error"

    @app.callback(
        Output("eds-map", "figure"),
        [
            Input("map-style-radio", "value"),
            Input("layer-toggles", "value"),
            Input("zoom-qld", "n_clicks"),
            Input("zoom-aus", "n_clicks"),
            Input("zoom-wide", "n_clicks"),
            Input("update-interval", "n_intervals"),
        ],
    )
    def update_map(map_style, layers, qld_clicks, aus_clicks, wide_clicks, _n):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            # Determine zoom
            ctx = callback_context
            center_lat, center_lon, zoom = -25, 135, 5

            if ctx.triggered:
                button_id = ctx.triggered[0]["prop_id"].split(".")[0]
                if button_id == "zoom-qld":
                    center_lat, center_lon, zoom = -23, 145, 7
                elif button_id == "zoom-aus":
                    center_lat, center_lon, zoom = -25, 135, 5
                elif button_id == "zoom-wide":
                    center_lat, center_lon, zoom = -25, 135, 3

            # Marker size based on zoom
            marker_size = max(8, min(25, zoom * 3))

            with db.get_session() as session:
                fig = go.Figure()

                # 1) Build a last-seen date per tile from multiple sources
                tiles = session.query(LandsatTile).all()
                tile_last_seen = {}
                for t in tiles:
                    if getattr(t, "last_processed", None):
                        tile_last_seen[t.tile_id] = t.last_processed

                # Latest NVMS detection per tile
                try:
                    nvms_last = (
                        session.query(
                            NVMSDetection.tile_id, func.max(NVMSDetection.imported_at)
                        )
                        .group_by(NVMSDetection.tile_id)
                        .all()
                    )
                    for tile_id, dt in nvms_last:
                        if tile_id and dt:
                            prev = tile_last_seen.get(tile_id)
                            if not prev or (dt and dt > prev):
                                tile_last_seen[tile_id] = dt
                except Exception as e2:
                    logger.debug(f"NVMS last-seen aggregation skipped: {e2}")

                # Latest alert per tile (raw SQL to avoid needing ORM model)
                try:
                    rows = session.execute(
                        text(
                            "SELECT tile_id, MAX(detection_date) AS last_dt FROM detection_alerts GROUP BY tile_id"
                        )
                    )
                    for row in rows:
                        tile_id = row[0]
                        dt = row[1]
                        if tile_id and dt:
                            prev = tile_last_seen.get(tile_id)
                            if not prev or (dt and dt > prev):
                                tile_last_seen[tile_id] = dt
                except Exception as e3:
                    logger.debug(f"Alert last-seen aggregation skipped: {e3}")

                # 2) Render tiles with color coding by last-seen
                if tiles and ("tiles" in (layers or [])):
                    tile_lats, tile_lons, tile_colors, tile_texts = [], [], [], []
                    for tile in tiles:
                        if tile.center_lat and tile.center_lon:
                            tile_lats.append(tile.center_lat)
                            tile_lons.append(tile.center_lon)

                            last_dt = tile_last_seen.get(tile.tile_id)
                            if last_dt:
                                try:
                                    days_ago = (datetime.now() - last_dt).days
                                except Exception:
                                    days_ago = 9999
                                if days_ago <= 7:
                                    color = "green"
                                elif days_ago <= 30:
                                    color = "orange"
                                else:
                                    color = "red"
                                last_text = (
                                    last_dt.strftime("%Y-%m-%d")
                                    if hasattr(last_dt, "strftime")
                                    else str(last_dt)
                                )
                            else:
                                color = "gray"
                                last_text = "Never"

                            tile_colors.append(color)
                            tile_texts.append(
                                f"Tile: {tile.tile_id}<br>Last Seen: {last_text}"
                            )

                    fig.add_trace(
                        go.Scattermapbox(
                            lat=tile_lats,
                            lon=tile_lons,
                            mode="markers",
                            marker=dict(
                                size=marker_size, color=tile_colors, opacity=0.55
                            ),
                            text=tile_texts,
                            name="EDS Tiles",
                            hovertemplate="%{text}<extra></extra>",
                        )
                    )

                # 3) Add detections: NVMS pilot detections
                try:
                    detections = (
                        session.query(NVMSDetection)
                        .order_by(NVMSDetection.id.desc())
                        .limit(200)
                        .all()
                    )
                    nvms_lats, nvms_lons, nvms_texts = [], [], []
                    for det in detections:
                        if getattr(det, "geom_geojson", None):
                            try:
                                import json

                                raw_g = det.geom_geojson
                                if isinstance(raw_g, str):
                                    geom = json.loads(raw_g)
                                else:
                                    geom = raw_g
                                coords = None
                                if geom["type"] == "Polygon":
                                    coords = geom["coordinates"][0]
                                elif geom["type"] == "MultiPolygon":
                                    coords = geom["coordinates"][0][0]
                                if coords:
                                    lats = [c[1] for c in coords]
                                    lons = [c[0] for c in coords]
                                    center_lat = sum(lats) / len(lats)
                                    center_lon = sum(lons) / len(lons)
                                    nvms_lats.append(center_lat)
                                    nvms_lons.append(center_lon)
                                    det_date = (
                                        det.imported_at.strftime("%Y-%m-%d")
                                        if getattr(det, "imported_at", None)
                                        else "Unknown"
                                    )
                                    nvms_texts.append(
                                        f"NVMS #{det.id}<br>Tile: {det.tile_id}<br>Imported: {det_date}"
                                    )
                            except Exception:
                                continue
                    if nvms_lats and ("nvms" in (layers or [])):
                        fig.add_trace(
                            go.Scattermapbox(
                                lat=nvms_lats,
                                lon=nvms_lons,
                                mode="markers",
                                marker=dict(
                                    size=11, color="red", symbol="circle", opacity=0.9
                                ),
                                text=nvms_texts,
                                name="NVMS Detections",
                                hovertemplate="%{text}<extra></extra>",
                            )
                        )
                except Exception as e4:
                    logger.debug(f"NVMS detections skipped: {e4}")

                # 4) Add live detection alerts
                try:
                    rows = session.execute(
                        text(
                            "SELECT id, tile_id, detection_date, detection_geojson FROM detection_alerts ORDER BY detection_date DESC LIMIT 300"
                        )
                    )
                    alert_lats, alert_lons, alert_texts = [], [], []
                    import json

                    for row in rows:
                        alert_id, tile_id, det_date, geojson = row
                        center_lat = center_lon = None
                        if geojson:
                            try:
                                if isinstance(geojson, str):
                                    geom = json.loads(geojson)
                                else:
                                    geom = geojson
                                coords = None
                                if geom.get("type") == "Polygon":
                                    coords = geom["coordinates"][0]
                                elif geom.get("type") == "MultiPolygon":
                                    coords = geom["coordinates"][0][0]
                                if coords:
                                    lats = [c[1] for c in coords]
                                    lons = [c[0] for c in coords]
                                    center_lat = sum(lats) / len(lats)
                                    center_lon = sum(lons) / len(lons)
                            except Exception:
                                center_lat = center_lon = None
                        if center_lat is not None and center_lon is not None:
                            alert_lats.append(center_lat)
                            alert_lons.append(center_lon)
                            date_text = (
                                det_date.strftime("%Y-%m-%d")
                                if hasattr(det_date, "strftime")
                                else str(det_date)
                            )
                            alert_texts.append(
                                f"Alert {alert_id}<br>Tile: {tile_id or 'Unknown'}<br>Date: {date_text}"
                            )

                    if alert_lats and ("alerts" in (layers or [])):
                        fig.add_trace(
                            go.Scattermapbox(
                                lat=alert_lats,
                                lon=alert_lons,
                                mode="markers",
                                marker=dict(
                                    size=12,
                                    color="orange",
                                    symbol="diamond",
                                    opacity=0.95,
                                ),
                                text=alert_texts,
                                name="Detection Alerts",
                                hovertemplate="%{text}<extra></extra>",
                            )
                        )
                except Exception as e5:
                    logger.debug(f"Alert detections skipped: {e5}")

                fig.update_layout(
                    mapbox=dict(
                        style=map_style,
                        center=dict(lat=center_lat, lon=center_lon),
                        zoom=zoom,
                    ),
                    height=700,
                    title=f'🛰️ EDS Tiles - {map_style.replace("-", " ").title()}',
                    margin=dict(r=0, t=40, l=0, b=0),
                    legend=dict(
                        title="Layers",
                        orientation="h",
                        yanchor="bottom",
                        y=0.01,
                        xanchor="left",
                        x=0.01,
                        bgcolor="rgba(255,255,255,0.7)",
                    ),
                )

                return fig

        except Exception as e:
            logger.error(f"Map error: {e}")
            fig = go.Figure()
            fig.add_annotation(text=f"Map Error: {e}", x=0.5, y=0.5, showarrow=False)
            return fig

    @app.callback(
        Output("data-summary", "children"), [Input("update-interval", "n_intervals")]
    )
    def update_summary(_n):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                tiles = session.query(LandsatTile).all()
                tile_last_seen = {}
                for t in tiles:
                    if getattr(t, "last_processed", None):
                        tile_last_seen[t.tile_id] = t.last_processed

                try:
                    nvms_last = (
                        session.query(
                            NVMSDetection.tile_id, func.max(NVMSDetection.imported_at)
                        )
                        .group_by(NVMSDetection.tile_id)
                        .all()
                    )
                    for tile_id, dt in nvms_last:
                        if tile_id and dt:
                            prev = tile_last_seen.get(tile_id)
                            if not prev or (dt and dt > prev):
                                tile_last_seen[tile_id] = dt
                except Exception:
                    pass

                try:
                    rows = session.execute(
                        text(
                            "SELECT tile_id, MAX(detection_date) AS last_dt FROM detection_alerts GROUP BY tile_id"
                        )
                    )
                    for row in rows:
                        tile_id, dt = row[0], row[1]
                        if tile_id and dt:
                            prev = tile_last_seen.get(tile_id)
                            if not prev or (dt and dt > prev):
                                tile_last_seen[tile_id] = dt
                except Exception:
                    pass

                # Buckets
                green = orange = red = gray = 0
                now = datetime.now()
                for t in tiles:
                    last_dt = tile_last_seen.get(t.tile_id)
                    if last_dt:
                        try:
                            days = (now - last_dt).days
                        except Exception:
                            days = 9999
                        if days <= 7:
                            green += 1
                        elif days <= 30:
                            orange += 1
                        else:
                            red += 1
                    else:
                        gray += 1

                # Detections counts
                nvms_total = session.query(NVMSDetection).count()
                try:
                    nvms_with_geom = (
                        session.query(NVMSDetection)
                        .filter(NVMSDetection.geom_geojson.isnot(None))
                        .count()
                    )
                except Exception:
                    nvms_with_geom = 0
                try:
                    alerts_total = (
                        session.execute(
                            text("SELECT COUNT(*) FROM detection_alerts")
                        ).scalar()
                        or 0
                    )
                    alerts_with_geo = (
                        session.execute(
                            text(
                                "SELECT COUNT(*) FROM detection_alerts WHERE detection_geojson IS NOT NULL"
                            )
                        ).scalar()
                        or 0
                    )
                except Exception:
                    alerts_total = 0
                    alerts_with_geo = 0

                # Compute plot candidate counts (same logic as map)
                def count_nvms_plot_points():
                    try:
                        c = 0
                        dets = (
                            session.query(NVMSDetection)
                            .order_by(NVMSDetection.id.desc())
                            .limit(200)
                            .all()
                        )
                        for det in dets:
                            g = det.geom_geojson
                            if not g:
                                continue
                            if isinstance(g, str):
                                import json as _json

                                try:
                                    g = _json.loads(g)
                                except Exception:
                                    continue
                            coords = None
                            if isinstance(g, dict):
                                t = (g.get("type") or "").lower()
                                if t == "polygon":
                                    coords = g.get("coordinates", [[]])[0]
                                elif t == "multipolygon":
                                    coords = (
                                        (g.get("coordinates", [[[]]])[0][0])
                                        if g.get("coordinates")
                                        else None
                                    )
                            if coords:
                                c += 1
                        return c
                    except Exception:
                        return 0

                def count_alert_plot_points():
                    try:
                        rows = session.execute(
                            text(
                                "SELECT detection_geojson FROM detection_alerts ORDER BY detection_date DESC LIMIT 300"
                            )
                        )
                        c = 0
                        import json as _json

                        for (geojson,) in rows:
                            if not geojson:
                                continue
                            g = (
                                _json.loads(geojson)
                                if isinstance(geojson, str)
                                else geojson
                            )
                            if isinstance(g, dict):
                                t = (g.get("type") or "").lower()
                                if t == "polygon":
                                    c += 1
                                elif t == "multipolygon":
                                    c += 1
                        return c
                    except Exception:
                        return 0

                nvms_plot = count_nvms_plot_points()
                alerts_plot = count_alert_plot_points()

                return html.Div(
                    [
                        html.Div(
                            [
                                html.Span(
                                    f"Tiles - green:{green} orange:{orange} red:{red} grey:{gray}"
                                )
                            ]
                        ),
                        html.Div(
                            [
                                html.Span(
                                    f"NVMS detections: {nvms_total} (with geometry: {nvms_with_geom}; plot candidates: {nvms_plot})"
                                )
                            ]
                        ),
                        html.Div(
                            [
                                html.Span(
                                    f"Alert detections: {alerts_total} (with geometry: {alerts_with_geo}; plot candidates: {alerts_plot})"
                                )
                            ]
                        ),
                    ],
                    style={"lineHeight": "1.8"},
                )

        except Exception as e:
            return f"Summary error: {e}"

    @app.callback(
        Output("detection-dropdown", "options"),
        [Input("update-interval", "n_intervals")],
    )
    def update_detection_options(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get some detections for QC
                detections = session.query(NVMSDetection).limit(20).all()

                options = []
                for det in detections:
                    label = f"Detection {det.id} - Tile {det.tile_id or 'Unknown'}"
                    options.append({"label": label, "value": det.id})

                return options

        except Exception as e:
            return [{"label": f"Error: {e}", "value": "error"}]

    @app.callback(
        Output("detection-info", "children"), [Input("detection-dropdown", "value")]
    )
    def show_detection_info(detection_id):
        if not detection_id or detection_id == "error":
            return "Select a detection to see details."

        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                detection = (
                    session.query(NVMSDetection)
                    .filter(NVMSDetection.id == detection_id)
                    .first()
                )

                if not detection:
                    return "Detection not found."

                # Create polygon preview map
                polygon_fig = go.Figure()

                # Try to parse and display the geometry (robust to Feature/MultiPolygon)
                try:
                    raw = getattr(detection, "geom_geojson", None)
                    if raw:
                        import json

                        # Handle double-encoded JSON strings
                        if (
                            isinstance(raw, str)
                            and raw.strip().startswith('"')
                            and raw.strip().endswith('"')
                        ):
                            raw = json.loads(raw)

                        geom = json.loads(raw) if isinstance(raw, str) else raw

                        # Unwrap Feature/FeatureCollection
                        g = geom
                        if isinstance(geom, dict) and geom.get("type") == "Feature":
                            g = geom.get("geometry") or {}
                        elif (
                            isinstance(geom, dict)
                            and geom.get("type") == "FeatureCollection"
                        ):
                            feats = geom.get("features") or []
                            g = (feats[0].get("geometry") if feats else {}) or {}

                        def outer_ring_from_polygon_or_multipolygon(geo: dict):
                            t = (geo or {}).get("type")
                            if not t:
                                return None
                            t = t.lower()
                            coords = geo.get("coordinates")
                            if not coords:
                                return None
                            if t == "polygon":
                                return coords[0]
                            if t == "multipolygon":
                                # choose the largest ring by shoelace area (approximate)
                                def area(ring):
                                    s = 0.0
                                    for i in range(len(ring)):
                                        x1, y1 = ring[i][0], ring[i][1]
                                        x2, y2 = (
                                            ring[(i + 1) % len(ring)][0],
                                            ring[(i + 1) % len(ring)][1],
                                        )
                                        s += x1 * y2 - x2 * y1
                                    return abs(s) / 2.0

                                candidates = []
                                for poly in coords:
                                    if poly and poly[0]:
                                        candidates.append(poly[0])
                                if not candidates:
                                    return None
                                best = max(candidates, key=area)
                                return best
                            return None

                        ring = outer_ring_from_polygon_or_multipolygon(g)

                        if ring:
                            # Ensure closed ring (first == last)
                            if ring[0] != ring[-1]:
                                ring = ring + [ring[0]]
                            lons = [pt[0] for pt in ring]
                            lats = [pt[1] for pt in ring]

                            polygon_fig.add_trace(
                                go.Scattermapbox(
                                    lon=lons,
                                    lat=lats,
                                    mode="lines",
                                    fill="toself",
                                    fillcolor="rgba(255, 0, 0, 0.25)",
                                    line=dict(color="red", width=2),
                                    name="Detection Polygon",
                                )
                            )

                            center_lat = sum(lats) / len(lats)
                            center_lon = sum(lons) / len(lons)
                            zoom = 15
                        else:
                            # Fallback: try to compute centroid from any coords list
                            def flatten_coords(obj):
                                if isinstance(obj, (list, tuple)):
                                    for el in obj:
                                        yield from flatten_coords(el)
                                else:
                                    return

                            # Attempt to fetch numeric pairs roughly [lon,lat]
                            pts = []

                            def collect_pairs(node):
                                if (
                                    isinstance(node, list)
                                    and len(node) >= 2
                                    and all(
                                        isinstance(v, (int, float)) for v in node[:2]
                                    )
                                ):
                                    pts.append(node[:2])
                                if isinstance(node, list):
                                    for el in node:
                                        collect_pairs(el)

                            collect_pairs(g.get("coordinates", []))
                            if pts:
                                lons = [p[0] for p in pts]
                                lats = [p[1] for p in pts]
                                center_lat = sum(lats) / len(lats)
                                center_lon = sum(lons) / len(lons)
                                polygon_fig.add_trace(
                                    go.Scattermapbox(
                                        lon=[center_lon],
                                        lat=[center_lat],
                                        mode="markers",
                                        marker=dict(size=12, color="red"),
                                        name="Detection Centroid",
                                    )
                                )
                                zoom = 12
                            else:
                                raise ValueError("Unsupported geometry structure")

                        polygon_fig.update_layout(
                            mapbox=dict(
                                style="open-street-map",
                                center=dict(lat=center_lat, lon=center_lon),
                                zoom=zoom,
                            ),
                            height=300,
                            margin=dict(l=5, r=5, t=30, b=5),
                            showlegend=False,
                            title={
                                "text": "🗺️ Detection Polygon Shape",
                                "x": 0.5,
                                "xanchor": "center",
                            },
                        )
                    else:
                        polygon_fig.update_layout(
                            height=150,
                            margin=dict(l=5, r=5, t=30, b=5),
                            title={
                                "text": "❌ No geometry data available",
                                "x": 0.5,
                                "xanchor": "center",
                            },
                        )
                        polygon_fig.add_annotation(
                            text="No polygon geometry found for this detection",
                            xref="paper",
                            yref="paper",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                            font=dict(size=14, color="red"),
                        )
                except Exception as geom_error:
                    polygon_fig.update_layout(
                        height=180,
                        margin=dict(l=5, r=5, t=30, b=5),
                        title={
                            "text": "⚠️ Geometry parse error",
                            "x": 0.5,
                            "xanchor": "center",
                        },
                    )
                    polygon_fig.add_annotation(
                        text=f"Geometry error: {str(geom_error)}",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                        showarrow=False,
                    )

                return html.Div(
                    [
                        html.Div(
                            [
                                html.Strong(
                                    f"Detection #{detection.id}",
                                    style={"fontSize": "16px", "color": "#2c3e50"},
                                ),
                                html.Br(),
                                f"Tile: {detection.tile_id or 'Unknown'}",
                                html.Br(),
                                f"Run: {detection.run_id or 'Unknown'}",
                                html.Br(),
                                f"Imported: {detection.imported_at.strftime('%Y-%m-%d') if detection.imported_at else 'Unknown'}",
                            ],
                            style={
                                "backgroundColor": "#f8f9fa",
                                "padding": 10,
                                "borderRadius": 5,
                                "marginBottom": 10,
                            },
                        ),
                        html.Div(
                            [
                                html.Strong(
                                    "🗺️ Polygon Shape Preview:",
                                    style={
                                        "marginBottom": 10,
                                        "display": "block",
                                        "fontSize": "16px",
                                    },
                                ),
                                dcc.Graph(
                                    figure=polygon_fig, config={"displayModeBar": False}
                                ),
                            ],
                            style={
                                "border": "2px solid #3498db",
                                "borderRadius": "8px",
                                "padding": "10px",
                                "backgroundColor": "#f8f9ff",
                                "marginTop": "10px",
                            },
                        ),
                    ]
                )

        except Exception as e:
            return f"Error: {e}"

    @app.callback(
        [
            Output("submit-message", "children"),
            Output("reviewer-input", "value"),
            Output("decision-radio", "value"),
            Output("confidence-slider", "value"),
            Output("comments-input", "value"),
        ],
        [Input("submit-btn", "n_clicks")],
        [
            State("detection-dropdown", "value"),
            State("reviewer-input", "value"),
            State("decision-radio", "value"),
            State("confidence-slider", "value"),
            State("comments-input", "value"),
        ],
    )
    def submit_review(n_clicks, detection_id, reviewer, decision, confidence, comments):
        if n_clicks == 0 or not detection_id or not reviewer or not decision:
            return "", "", None, 3, ""

        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Create QC record
                qc = QCValidation(
                    nvms_detection_id=detection_id,
                    tile_id="unknown",  # Will update this
                    qc_status=decision,
                    reviewed_by=reviewer,
                    reviewed_at=datetime.now(),
                    reviewer_comments=comments,
                    confidence_score=confidence,
                    is_confirmed_clearing=(decision == "confirmed"),
                )

                session.add(qc)
                session.commit()

                success_msg = html.Div(
                    f"✅ Review submitted! Detection {detection_id} marked as {decision} (confidence: {confidence}/5)",
                    style={"color": "#27ae60", "fontWeight": "bold"},
                )

                return success_msg, "", None, 3, ""

        except Exception as e:
            error_msg = html.Div(f"❌ Error: {e}", style={"color": "#e74c3c"})
            return error_msg, reviewer, decision, confidence, comments

    @app.callback(
        Output("recent-reviews", "children"),
        [Input("update-interval", "n_intervals"), Input("submit-btn", "n_clicks")],
    )
    def show_recent_reviews(n_intervals, submit_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                recent = (
                    session.query(QCValidation)
                    .order_by(QCValidation.reviewed_at.desc())
                    .limit(5)
                    .all()
                )

                if not recent:
                    return "No reviews yet."

                items = []
                for qc in recent:
                    color = {
                        "confirmed": "#27ae60",
                        "rejected": "#e74c3c",
                        "requires_review": "#f39c12",
                    }.get(qc.qc_status, "#95a5a6")

                    items.append(
                        html.Div(
                            [
                                html.Strong(f"Detection {qc.nvms_detection_id}"),
                                html.Br(),
                                html.Span(qc.qc_status.title(), style={"color": color}),
                                html.Br(),
                                html.Small(f"By {qc.reviewed_by}"),
                            ],
                            style={
                                "padding": 8,
                                "marginBottom": 8,
                                "backgroundColor": "#f8f9fa",
                                "borderRadius": 4,
                            },
                        )
                    )

                return items

        except Exception as e:
            return f"Error: {e}"

    # Add a version/health endpoint to verify process
    @app.server.route("/__version")
    def _version():
        from flask import Response

        payload = {
            "build": BUILD_STAMP,
            "instance": INSTANCE_ID,
            "port": 8061,
            "name": "eds_in_action_fixed",
        }
        return Response(json.dumps(payload), mimetype="application/json")

    # Run the app on a fresh port to avoid clashes with any stale process
    PORT = 8061
    print("🚀 EDS IN ACTION - FIXED VERSION")
    print("=" * 50)
    print(f"🌐 Local: http://localhost:{PORT}")
    print(f"📍 Network: http://10.0.0.14:{PORT}")
    print("")
    print("✅ FIXED ISSUES:")
    print("- Callback registration errors")
    print("- NVMSDetection attribute errors")
    print("- Simplified QC workflow")
    print("")
    print("Press Ctrl+C to stop")

    app.run_server(debug=False, host="0.0.0.0", port=PORT)

#!/usr/bin/env python3
"""
EDS Dashboard - Complete Version with All Features
=================================================
- Color-coded tile map
- Detection polygon visualization
- QC review with confidence slider
- Polygon shape preview
"""

import sys
from pathlib import Path
import json
import dash
from dash import dcc, html, Input, Output, State, callback_context
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import pandas as pd
from contextlib import contextmanager

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

# Database imports
from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
from src.database.qc_models import QCValidation, QCAuditLog

# Import detection alerts model if it exists
try:
    from src.database.detection_models import DetectionAlert

    HAS_DETECTION_ALERTS = True
except ImportError:
    HAS_DETECTION_ALERTS = False
    DetectionAlert = None


# Helper function to get database session
def get_db_session():
    """Get database session using connection manager"""
    db_manager = DatabaseManager()
    return db_manager.get_session()


# Initialize Dash app
import uuid

BUILD_STAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
INSTANCE_ID = str(uuid.uuid4())[:8]

app = dash.Dash(__name__)
app.title = "EDS Dashboard - Complete"

# App layout
app.layout = html.Div(
    [
        html.Div(
            [
                html.H1(
                    "🛰️ EDS - Early Detection System",
                    style={
                        "textAlign": "center",
                        "color": "#2c3e50",
                        "marginBottom": 10,
                    },
                ),
                html.P(
                    "Land Clearing Detection & Quality Control Dashboard",
                    style={"textAlign": "center", "color": "#7f8c8d", "fontSize": 18},
                ),
                html.Div(
                    [
                        html.Small(
                            f"Build: {BUILD_STAMP} | Instance: {INSTANCE_ID} | Port: 8060 | Add ?v={INSTANCE_ID} to URL to bypass cache",
                            style={"color": "#7f8c8d"},
                        )
                    ],
                    style={"textAlign": "center"},
                ),
            ],
            style={"backgroundColor": "#ecf0f1", "padding": 20, "marginBottom": 20},
        ),
        # Stats row
        html.Div(
            [
                html.Div(
                    [
                        html.H3("📊 System Stats", style={"color": "#2c3e50"}),
                        html.Div(id="stats-display"),
                    ],
                    className="twelve columns",
                    style={
                        "backgroundColor": "#f8f9fa",
                        "padding": 15,
                        "borderRadius": 5,
                    },
                )
            ],
            className="row",
            style={"marginBottom": 20},
        ),
        # Main content row
        html.Div(
            [
                # Left column - Map
                html.Div(
                    [
                        html.H3(
                            "🗺️ Landsat Tiles & Detections", style={"color": "#2c3e50"}
                        ),
                        html.Div(
                            [
                                html.Label(
                                    "Map Style:",
                                    style={"fontWeight": "bold", "marginRight": 10},
                                ),
                                dcc.RadioItems(
                                    id="map-style-radio",
                                    options=[
                                        {
                                            "label": " Street",
                                            "value": "open-street-map",
                                        },
                                        {"label": " Satellite", "value": "satellite"},
                                        {
                                            "label": " Terrain",
                                            "value": "stamen-terrain",
                                        },
                                    ],
                                    value="open-street-map",
                                    inline=True,
                                    style={"marginBottom": 10},
                                ),
                                html.Div(
                                    [
                                        html.Button(
                                            "🦘 Queensland",
                                            id="zoom-qld",
                                            n_clicks=0,
                                            style={
                                                "marginRight": 5,
                                                "padding": "5px 10px",
                                            },
                                        ),
                                        html.Button(
                                            "🇦🇺 Australia",
                                            id="zoom-aus",
                                            n_clicks=0,
                                            style={
                                                "marginRight": 5,
                                                "padding": "5px 10px",
                                            },
                                        ),
                                        html.Button(
                                            "🌍 Wide View",
                                            id="zoom-wide",
                                            n_clicks=0,
                                            style={"padding": "5px 10px"},
                                        ),
                                    ],
                                    style={"marginBottom": 15},
                                ),
                            ]
                        ),
                        dcc.Graph(id="main-map", style={"height": "600px"}),
                        # Legend
                        html.Div(
                            [
                                html.Strong("Legend: "),
                                html.Span(
                                    "🟢 Recent (≤7 days) ", style={"color": "green"}
                                ),
                                html.Span(
                                    "🟠 Medium (8-30 days) ", style={"color": "orange"}
                                ),
                                html.Span("🔴 Old (>30 days) ", style={"color": "red"}),
                                html.Span("⚫ Never Run ", style={"color": "gray"}),
                                html.Br(),
                                html.Span(
                                    "🔴 Red circles = NVMS pilot detections ",
                                    style={"color": "red", "fontWeight": "bold"},
                                ),
                                html.Span(
                                    "🟠 Orange diamonds = Live detection alerts",
                                    style={"color": "orange", "fontWeight": "bold"},
                                ),
                            ],
                            style={
                                "marginTop": 10,
                                "padding": 10,
                                "backgroundColor": "#f8f9fa",
                                "borderRadius": 5,
                            },
                        ),
                    ],
                    className="seven columns",
                ),
                # Right column - QC Panel
                html.Div(
                    [
                        html.H3(
                            "🎯 Quality Control Review", style={"color": "#2c3e50"}
                        ),
                        # Detection selection
                        html.Div(
                            [
                                html.Label(
                                    "Select Detection to Review:",
                                    style={"fontWeight": "bold"},
                                ),
                                dcc.Dropdown(
                                    id="detection-dropdown",
                                    placeholder="Choose a detection...",
                                    style={"marginBottom": 15},
                                ),
                            ]
                        ),
                        # Detection info and polygon preview
                        html.Div(id="detection-info", style={"marginBottom": 20}),
                        # QC Review Form
                        html.Div(
                            [
                                html.H4(
                                    "📝 Review Form",
                                    style={"color": "#34495e", "marginBottom": 15},
                                ),
                                html.Label(
                                    "Reviewer Name:", style={"fontWeight": "bold"}
                                ),
                                dcc.Input(
                                    id="reviewer-input",
                                    type="text",
                                    placeholder="Enter your name...",
                                    style={
                                        "width": "100%",
                                        "marginBottom": "15px",
                                        "padding": "8px",
                                    },
                                ),
                                html.Label("Decision:", style={"fontWeight": "bold"}),
                                dcc.RadioItems(
                                    id="decision-radio",
                                    options=[
                                        {
                                            "label": " ✅ Confirmed Clearing",
                                            "value": "confirmed",
                                        },
                                        {
                                            "label": " ❌ False Positive",
                                            "value": "rejected",
                                        },
                                        {
                                            "label": " ⚠️ Needs Review",
                                            "value": "requires_review",
                                        },
                                    ],
                                    style={"marginBottom": "20px"},
                                ),
                                html.Label(
                                    "Confidence Level:", style={"fontWeight": "bold"}
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
                                                1: "1-Low",
                                                2: "2",
                                                3: "3-Med",
                                                4: "4",
                                                5: "5-High",
                                            },
                                            tooltip={
                                                "placement": "bottom",
                                                "always_visible": True,
                                            },
                                        )
                                    ],
                                    style={
                                        "marginBottom": "20px",
                                        "padding": "15px",
                                        "border": "2px solid #3498db",
                                        "borderRadius": "8px",
                                        "backgroundColor": "#e8f4f8",
                                    },
                                ),
                                html.Label("Comments:", style={"fontWeight": "bold"}),
                                dcc.Textarea(
                                    id="comments-input",
                                    placeholder="Optional comments about this detection...",
                                    style={
                                        "width": "100%",
                                        "height": 80,
                                        "marginBottom": "15px",
                                        "padding": "8px",
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
                                        "padding": "12px 24px",
                                        "borderRadius": "6px",
                                        "fontSize": "16px",
                                        "cursor": "pointer",
                                        "width": "100%",
                                    },
                                ),
                                html.Div(id="submit-message", style={"marginTop": 15}),
                            ],
                            style={
                                "border": "1px solid #bdc3c7",
                                "borderRadius": "8px",
                                "padding": "20px",
                                "backgroundColor": "#f9f9f9",
                            },
                        ),
                    ],
                    className="five columns",
                ),
            ],
            className="row",
        ),
        # Update interval for real-time updates
        dcc.Interval(id="update-interval", interval=30000, n_intervals=0),
    ]
)

# Callbacks


@app.callback(
    Output("stats-display", "children"), [Input("update-interval", "n_intervals")]
)
def update_stats(n_intervals):
    try:
        with get_db_session() as session:
            total_tiles = session.query(LandsatTile).count()

            # Count both NVMS detections and detection alerts
            nvms_detections = session.query(NVMSDetection).count()

            # Query detection_alerts table directly
            try:
                result = session.execute("SELECT COUNT(*) FROM detection_alerts")
                alert_detections = result.scalar()
                total_detections = nvms_detections + alert_detections
            except:
                total_detections = nvms_detections

            recent_runs = (
                session.query(LandsatTile)
                .filter(
                    LandsatTile.last_processed >= datetime.now() - timedelta(days=7)
                )
                .count()
            )

            return html.Div(
                [
                    html.Div(
                        [
                            html.H4(
                                f"{total_tiles:,}",
                                style={"margin": 0, "color": "#2980b9"},
                            ),
                            html.P("Total Tiles", style={"margin": 0}),
                        ],
                        className="three columns",
                        style={"textAlign": "center"},
                    ),
                    html.Div(
                        [
                            html.H4(
                                f"{total_detections:,}",
                                style={"margin": 0, "color": "#e74c3c"},
                            ),
                            html.P(
                                f"Detections ({nvms_detections} NVMS)",
                                style={"margin": 0},
                            ),
                        ],
                        className="three columns",
                        style={"textAlign": "center"},
                    ),
                    html.Div(
                        [
                            html.H4(
                                f"{recent_runs:,}",
                                style={"margin": 0, "color": "#27ae60"},
                            ),
                            html.P("Recent Runs", style={"margin": 0}),
                        ],
                        className="three columns",
                        style={"textAlign": "center"},
                    ),
                    html.Div(
                        [
                            html.H4("✅", style={"margin": 0, "color": "#f39c12"}),
                            html.P("Status: Active", style={"margin": 0}),
                        ],
                        className="three columns",
                        style={"textAlign": "center"},
                    ),
                ],
                className="row",
            )

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        print(f"Stats error: {e}")
        print(f"Full traceback: {error_details}")
        return html.Div(
            [
                html.H4("Error Loading Stats", style={"color": "red"}),
                html.P(f"Error: {str(e)}", style={"color": "red", "fontSize": "12px"}),
                html.P(
                    "Check console for details",
                    style={"color": "gray", "fontSize": "10px"},
                ),
            ]
        )


@app.callback(
    Output("main-map", "figure"),
    [
        Input("map-style-radio", "value"),
        Input("zoom-qld", "n_clicks"),
        Input("zoom-aus", "n_clicks"),
        Input("zoom-wide", "n_clicks"),
        Input("update-interval", "n_intervals"),
    ],
)
def update_main_map(map_style, qld_clicks, aus_clicks, wide_clicks, n_intervals):
    try:
        # Determine zoom level and center
        ctx = callback_context
        center_lat, center_lon, zoom = -25, 135, 5  # Default Australia view

        if ctx.triggered:
            button_id = ctx.triggered[0]["prop_id"].split(".")[0]
            if button_id == "zoom-qld":
                center_lat, center_lon, zoom = -23, 145, 7
            elif button_id == "zoom-aus":
                center_lat, center_lon, zoom = -25, 135, 5
            elif button_id == "zoom-wide":
                center_lat, center_lon, zoom = -25, 135, 3

        # Create figure
        fig = go.Figure()

        with get_db_session() as session:
            # Add Landsat tiles with color coding
            tiles = session.query(LandsatTile).all()

            if tiles:
                tile_lats = []
                tile_lons = []
                tile_colors = []
                tile_texts = []

                for tile in tiles:
                    if tile.center_lat and tile.center_lon:
                        tile_lats.append(tile.center_lat)
                        tile_lons.append(tile.center_lon)

                        # Color based on last run date
                        if tile.last_processed:
                            days_ago = (datetime.now() - tile.last_processed).days
                            if days_ago <= 7:
                                color = "green"
                            elif days_ago <= 30:
                                color = "orange"
                            else:
                                color = "red"
                        else:
                            color = "gray"

                        tile_colors.append(color)
                        last_run_str = (
                            tile.last_processed.strftime("%Y-%m-%d")
                            if tile.last_processed
                            else "Never"
                        )
                        tile_texts.append(
                            f"Tile: {tile.tile_id}<br>Last Run: {last_run_str}"
                        )

                # Add tile markers
                fig.add_trace(
                    go.Scattermapbox(
                        lat=tile_lats,
                        lon=tile_lons,
                        mode="markers",
                        marker=dict(size=8, color=tile_colors, opacity=0.7),
                        text=tile_texts,
                        name="Landsat Tiles",
                        hovertemplate="%{text}<extra></extra>",
                    )
                )

            # Add NVMS detections (historical pilot data)
            nvms_detections = session.query(NVMSDetection).limit(100).all()

            if nvms_detections:
                det_lats = []
                det_lons = []
                det_texts = []

                for det in nvms_detections:
                    if det.geom_geojson:
                        try:
                            geom = det.geom_geojson
                            if geom["type"] == "Polygon":
                                # Calculate centroid
                                coords = geom["coordinates"][0]
                                lats = [coord[1] for coord in coords]
                                lons = [coord[0] for coord in coords]
                                center_lat_det = sum(lats) / len(lats)
                                center_lon_det = sum(lons) / len(lons)

                                det_lats.append(center_lat_det)
                                det_lons.append(center_lon_det)
                                det_texts.append(
                                    f"NVMS Detection #{det.id}<br>Tile: {det.tile_id}<br>Imported: {det.imported_at}"
                                )
                        except:
                            continue

                if det_lats:
                    fig.add_trace(
                        go.Scattermapbox(
                            lat=det_lats,
                            lon=det_lons,
                            mode="markers",
                            marker=dict(
                                size=6, color="red", symbol="circle", opacity=0.9
                            ),
                            text=det_texts,
                            name="NVMS Detections (Pilot)",
                            hovertemplate="%{text}<extra></extra>",
                        )
                    )

            # Add live detection alerts if they exist
            try:
                alert_query = """
                SELECT detection_lat, detection_lon, alert_id, tile_id, detection_date, area_hectares, confidence_score
                FROM detection_alerts 
                WHERE is_verified = false 
                LIMIT 100
                """
                alert_result = session.execute(alert_query)
                alerts = alert_result.fetchall()

                if alerts:
                    alert_lats = [float(alert[0]) for alert in alerts]
                    alert_lons = [float(alert[1]) for alert in alerts]
                    alert_texts = [
                        f"Alert #{alert[2]}<br>Tile: {alert[3]}<br>Date: {alert[4]}<br>Area: {alert[5]:.1f}ha<br>Confidence: {alert[6]:.2f}"
                        for alert in alerts
                    ]

                    fig.add_trace(
                        go.Scattermapbox(
                            lat=alert_lats,
                            lon=alert_lons,
                            mode="markers",
                            marker=dict(
                                size=8, color="orange", symbol="diamond", opacity=0.9
                            ),
                            text=alert_texts,
                            name="Live Detection Alerts",
                            hovertemplate="%{text}<extra></extra>",
                        )
                    )
            except Exception as e:
                print(f"Could not load detection alerts: {e}")

        # Update layout
        fig.update_layout(
            mapbox=dict(
                style=map_style, center=dict(lat=center_lat, lon=center_lon), zoom=zoom
            ),
            height=600,
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=True,
            legend=dict(x=0.01, y=0.99),
        )

        return fig

    except Exception as e:
        # Return empty map on error
        fig = go.Figure()
        fig.update_layout(
            title=f"Error loading map: {e}",
            height=600,
            margin=dict(l=0, r=0, t=50, b=0),
        )
        return fig


@app.callback(
    Output("detection-dropdown", "options"), [Input("update-interval", "n_intervals")]
)
def update_detection_options(n_intervals):
    try:
        with get_db_session() as session:
            options = []

            # Add NVMS detections
            nvms_detections = session.query(NVMSDetection).limit(25).all()
            for det in nvms_detections:
                label = f"NVMS #{det.id} - Tile {det.tile_id} ({det.imported_at.strftime('%Y-%m-%d') if det.imported_at else 'Unknown'})"
                options.append({"label": label, "value": f"nvms_{det.id}"})

            # Add detection alerts
            try:
                alert_query = """
                SELECT alert_id, tile_id, detection_date, area_hectares 
                FROM detection_alerts 
                ORDER BY detection_date DESC 
                LIMIT 25
                """
                alert_result = session.execute(alert_query)
                alerts = alert_result.fetchall()

                for alert in alerts:
                    date_str = alert[2].strftime("%Y-%m-%d") if alert[2] else "Unknown"
                    area_str = f"{alert[3]:.1f}ha" if alert[3] else "N/A"
                    label = (
                        f"Alert {alert[0]} - Tile {alert[1]} ({date_str}, {area_str})"
                    )
                    options.append({"label": label, "value": f"alert_{alert[0]}"})
            except Exception as e:
                print(f"Could not load detection alerts for dropdown: {e}")

            return options

    except Exception as e:
        return [{"label": f"Error: {e}", "value": "error"}]


@app.callback(
    Output("detection-info", "children"), [Input("detection-dropdown", "value")]
)
def update_detection_info(detection_id):
    if not detection_id or detection_id == "error":
        return html.Div(
            "Select a detection to see details and polygon shape.",
            style={"color": "#666", "fontStyle": "italic"},
        )

    try:
        with get_db_session() as session:

            # Determine if this is NVMS or Alert detection
            if detection_id.startswith("nvms_"):
                # NVMS Detection
                nvms_id = int(detection_id.replace("nvms_", ""))
                detection = (
                    session.query(NVMSDetection)
                    .filter(NVMSDetection.id == nvms_id)
                    .first()
                )

                if not detection:
                    return html.Div("NVMS Detection not found.", style={"color": "red"})

                # Create polygon preview
                polygon_fig = go.Figure()

                if detection.geom_geojson:
                    try:
                        geom = detection.geom_geojson
                        if geom["type"] == "Polygon":
                            coords = geom["coordinates"][0]
                            lons = [coord[0] for coord in coords]
                            lats = [coord[1] for coord in coords]

                            # Add polygon
                            polygon_fig.add_trace(
                                go.Scattermapbox(
                                    lon=lons,
                                    lat=lats,
                                    mode="lines",
                                    fill="toself",
                                    fillcolor="rgba(255, 0, 0, 0.3)",
                                    line=dict(color="red", width=3),
                                    name="Detection Area",
                                )
                            )

                            # Center map on polygon
                            center_lat = sum(lats) / len(lats)
                            center_lon = sum(lons) / len(lons)

                            polygon_fig.update_layout(
                                mapbox=dict(
                                    style="satellite",
                                    center=dict(lat=center_lat, lon=center_lon),
                                    zoom=16,
                                ),
                                height=300,
                                margin=dict(l=0, r=0, t=30, b=0),
                                showlegend=False,
                                title=dict(text="🛰️ NVMS Detection Polygon", x=0.5),
                            )
                        else:
                            polygon_fig.add_annotation(
                                text="Non-polygon geometry type",
                                xref="paper",
                                yref="paper",
                                x=0.5,
                                y=0.5,
                                showarrow=False,
                            )
                    except Exception as geom_error:
                        polygon_fig.add_annotation(
                            text=f"Geometry parsing error: {str(geom_error)}",
                            xref="paper",
                            yref="paper",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                        )
                else:
                    polygon_fig.add_annotation(
                        text="No geometry data available",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                        showarrow=False,
                    )

                return html.Div(
                    [
                        # Detection details
                        html.Div(
                            [
                                html.H4(
                                    f"🎯 NVMS Detection #{detection.id}",
                                    style={"color": "#2c3e50", "marginBottom": 10},
                                ),
                                html.P(
                                    [
                                        html.Strong("Type: "),
                                        "NVMS Pilot Data",
                                        html.Br(),
                                        html.Strong("Tile ID: "),
                                        f"{detection.tile_id}",
                                        html.Br(),
                                        html.Strong("Run ID: "),
                                        f"{detection.run_id}",
                                        html.Br(),
                                        html.Strong("Result ID: "),
                                        f"{detection.result_id}",
                                        html.Br(),
                                        html.Strong("Imported: "),
                                        (
                                            detection.imported_at.strftime(
                                                "%Y-%m-%d %H:%M"
                                            )
                                            if detection.imported_at
                                            else "Unknown"
                                        ),
                                    ]
                                ),
                            ],
                            style={
                                "backgroundColor": "#e8f6f3",
                                "padding": "15px",
                                "borderRadius": "8px",
                                "marginBottom": "15px",
                                "border": "1px solid #a3e4d7",
                            },
                        ),
                        # Polygon preview
                        html.Div(
                            [
                                html.Strong(
                                    "🗺️ Detection Shape Preview:",
                                    style={"display": "block", "marginBottom": "10px"},
                                ),
                                dcc.Graph(
                                    figure=polygon_fig, config={"displayModeBar": False}
                                ),
                            ],
                            style={
                                "border": "3px solid #e74c3c",
                                "borderRadius": "10px",
                                "padding": "10px",
                                "backgroundColor": "#fdf2f2",
                            },
                        ),
                    ]
                )

            elif detection_id.startswith("alert_"):
                # Detection Alert
                alert_id = detection_id.replace("alert_", "")

                alert_query = """
                SELECT alert_id, tile_id, detection_date, area_hectares, confidence_score, 
                       detection_lat, detection_lon, detection_geojson, clearing_type, severity
                FROM detection_alerts 
                WHERE alert_id = :alert_id
                """
                alert_result = session.execute(alert_query, {"alert_id": alert_id})
                alert = alert_result.fetchone()

                if not alert:
                    return html.Div(
                        "Detection Alert not found.", style={"color": "red"}
                    )

                # Create polygon preview
                polygon_fig = go.Figure()

                if alert[7]:  # detection_geojson
                    try:
                        geom = (
                            alert[7]
                            if isinstance(alert[7], dict)
                            else json.loads(alert[7])
                        )
                        if geom["type"] == "Polygon":
                            coords = geom["coordinates"][0]
                            lons = [coord[0] for coord in coords]
                            lats = [coord[1] for coord in coords]

                            # Add polygon
                            polygon_fig.add_trace(
                                go.Scattermapbox(
                                    lon=lons,
                                    lat=lats,
                                    mode="lines",
                                    fill="toself",
                                    fillcolor="rgba(255, 165, 0, 0.3)",
                                    line=dict(color="orange", width=3),
                                    name="Detection Area",
                                )
                            )

                            # Center map on polygon
                            center_lat = sum(lats) / len(lats)
                            center_lon = sum(lons) / len(lons)

                            polygon_fig.update_layout(
                                mapbox=dict(
                                    style="satellite",
                                    center=dict(lat=center_lat, lon=center_lon),
                                    zoom=16,
                                ),
                                height=300,
                                margin=dict(l=0, r=0, t=30, b=0),
                                showlegend=False,
                                title=dict(text="🛰️ Live Detection Alert", x=0.5),
                            )
                        else:
                            polygon_fig.add_annotation(
                                text="Non-polygon geometry type",
                                xref="paper",
                                yref="paper",
                                x=0.5,
                                y=0.5,
                                showarrow=False,
                            )
                    except Exception as geom_error:
                        polygon_fig.add_annotation(
                            text=f"Geometry parsing error: {str(geom_error)}",
                            xref="paper",
                            yref="paper",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                        )
                else:
                    # Use point location if no polygon
                    if alert[5] and alert[6]:  # detection_lat, detection_lon
                        polygon_fig.add_trace(
                            go.Scattermapbox(
                                lat=[alert[5]],
                                lon=[alert[6]],
                                mode="markers",
                                marker=dict(size=15, color="orange", symbol="diamond"),
                                name="Detection Point",
                            )
                        )

                        polygon_fig.update_layout(
                            mapbox=dict(
                                style="satellite",
                                center=dict(lat=alert[5], lon=alert[6]),
                                zoom=16,
                            ),
                            height=300,
                            margin=dict(l=0, r=0, t=30, b=0),
                            showlegend=False,
                            title=dict(text="🛰️ Detection Point Location", x=0.5),
                        )
                    else:
                        polygon_fig.add_annotation(
                            text="No location data available",
                            xref="paper",
                            yref="paper",
                            x=0.5,
                            y=0.5,
                            showarrow=False,
                        )

                return html.Div(
                    [
                        # Detection details
                        html.Div(
                            [
                                html.H4(
                                    f"🚨 Detection Alert {alert[0]}",
                                    style={"color": "#2c3e50", "marginBottom": 10},
                                ),
                                html.P(
                                    [
                                        html.Strong("Type: "),
                                        "Live Detection Alert",
                                        html.Br(),
                                        html.Strong("Tile ID: "),
                                        f"{alert[1]}",
                                        html.Br(),
                                        html.Strong("Detection Date: "),
                                        f"{alert[2]}",
                                        html.Br(),
                                        html.Strong("Area: "),
                                        (
                                            f"{alert[3]:.2f} hectares"
                                            if alert[3]
                                            else "N/A"
                                        ),
                                        html.Br(),
                                        html.Strong("Confidence: "),
                                        f"{alert[4]:.2f}" if alert[4] else "N/A",
                                        html.Br(),
                                        html.Strong("Clearing Type: "),
                                        f"{alert[8]}" if alert[8] else "Unknown",
                                        html.Br(),
                                        html.Strong("Severity: "),
                                        f"{alert[9]}" if alert[9] else "Unknown",
                                    ]
                                ),
                            ],
                            style={
                                "backgroundColor": "#fff3cd",
                                "padding": "15px",
                                "borderRadius": "8px",
                                "marginBottom": "15px",
                                "border": "1px solid #ffeaa7",
                            },
                        ),
                        # Polygon preview
                        html.Div(
                            [
                                html.Strong(
                                    "🗺️ Detection Shape Preview:",
                                    style={"display": "block", "marginBottom": "10px"},
                                ),
                                dcc.Graph(
                                    figure=polygon_fig, config={"displayModeBar": False}
                                ),
                            ],
                            style={
                                "border": "3px solid #f39c12",
                                "borderRadius": "10px",
                                "padding": "10px",
                                "backgroundColor": "#fef9e7",
                            },
                        ),
                    ]
                )

            else:
                return html.Div("Unknown detection type.", style={"color": "red"})

    except Exception as e:
        return html.Div(f"Error loading detection: {str(e)}", style={"color": "red"})


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
        with get_db_session() as session:
            # Extract the actual detection ID and type
            if detection_id.startswith("nvms_"):
                actual_id = int(detection_id.replace("nvms_", ""))
                detection_type = "nvms"
            elif detection_id.startswith("alert_"):
                actual_id = detection_id.replace("alert_", "")
                detection_type = "alert"
            else:
                actual_id = detection_id
                detection_type = "nvms"  # default

            # Create QC validation record
            qc = QCValidation(
                nvms_detection_id=actual_id if detection_type == "nvms" else None,
                tile_id="unknown",  # Will be updated
                qc_status=decision,
                reviewed_by=reviewer,
                reviewed_at=datetime.now(),
                reviewer_comments=(
                    f"[{detection_type.upper()}] {comments}"
                    if comments
                    else f"[{detection_type.upper()}]"
                ),
                confidence_score=confidence,
                is_confirmed_clearing=(decision == "confirmed"),
            )

            session.add(qc)
            session.commit()

            success_msg = html.Div(
                [
                    html.Strong("✅ Review Submitted Successfully!"),
                    html.Br(),
                    f"{detection_type.upper()} Detection {actual_id} marked as: {decision}",
                    html.Br(),
                    f"Confidence Level: {confidence}/5",
                ],
                style={
                    "color": "#27ae60",
                    "backgroundColor": "#d5f4e6",
                    "padding": "10px",
                    "borderRadius": "5px",
                },
            )

            return success_msg, "", None, 3, ""

    except Exception as e:
        error_msg = html.Div(
            f"❌ Error submitting review: {e}",
            style={
                "color": "#e74c3c",
                "backgroundColor": "#fadbd8",
                "padding": "10px",
                "borderRadius": "5px",
            },
        )
        return error_msg, reviewer, decision, confidence, comments


if __name__ == "__main__":
    print("🚀 EDS DASHBOARD - COMPLETE VERSION")
    print("=" * 50)
    print("🌐 Local: http://localhost:8060")
    print("📍 Network: http://10.0.0.14:8060")
    print()
    print("✅ FEATURES INCLUDED:")
    print("- Color-coded tile map (Green/Orange/Red/Gray)")
    print("- Detection polygon visualization")
    print("- QC review with confidence slider")
    print("- Polygon shape preview")
    print("- Real-time updates")
    print()
    print("Press Ctrl+C to stop")

    # Version endpoint for quick verification
    @app.server.route("/__version")
    def _version():
        from flask import Response

        payload = {
            "build": BUILD_STAMP,
            "instance": INSTANCE_ID,
            "port": 8060,
            "name": "eds_dashboard_complete",
        }
        return Response(json.dumps(payload), mimetype="application/json")

    app.run_server(debug=False, host="0.0.0.0", port=8060)

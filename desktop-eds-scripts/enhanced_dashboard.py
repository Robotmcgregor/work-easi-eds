#!/usr/bin/env python
"""
Enhanced EDS dashboard with proper NVMS data visualization and tile boundaries.
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta
    import logging

    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.config.settings import get_config

    # Initialize Dash app
    app = dash.Dash(__name__, title="EDS - Early Detection System")

    # Enhanced layout with proper overview
    app.layout = html.Div(
        [
            html.H1(
                "EDS - Early Detection System",
                style={"textAlign": "center", "color": "#2c3e50", "marginBottom": 20},
            ),
            html.P(
                "Land Clearing Detection Dashboard for Australia",
                style={"textAlign": "center", "marginBottom": 30},
            ),
            # Key metrics row
            html.Div(
                [
                    html.Div(
                        [
                            html.H3(id="total-tiles", children="..."),
                            html.P("Total Tiles"),
                        ],
                        className="metric-card",
                    ),
                    html.Div(
                        [
                            html.H3(id="processed-tiles", children="..."),
                            html.P("Processed Tiles"),
                        ],
                        className="metric-card",
                    ),
                    html.Div(
                        [
                            html.H3(id="total-detections", children="..."),
                            html.P("Total Detections"),
                        ],
                        className="metric-card",
                    ),
                    html.Div(
                        [
                            html.H3(id="cleared-detections", children="..."),
                            html.P("Cleared Areas"),
                        ],
                        className="metric-card",
                    ),
                ],
                style={
                    "display": "flex",
                    "justifyContent": "space-around",
                    "marginBottom": 30,
                },
            ),
            # Charts row
            html.Div(
                [
                    html.Div(
                        [dcc.Graph(id="run-breakdown-chart")],
                        style={"width": "50%", "display": "inline-block"},
                    ),
                    html.Div(
                        [dcc.Graph(id="processing-timeline-chart")],
                        style={"width": "50%", "display": "inline-block"},
                    ),
                ],
                style={"marginBottom": 30},
            ),
            # Map
            html.Div([dcc.Graph(id="main-map", style={"height": "600px"})]),
            dcc.Interval(
                id="interval", interval=30000, n_intervals=0
            ),  # Update every 30s
        ],
        style={
            "fontFamily": "Arial, sans-serif",
            "margin": "0",
            "padding": "20px",
            "backgroundColor": "#f8f9fa",
        },
    )

    @app.callback(
        [
            Output("total-tiles", "children"),
            Output("processed-tiles", "children"),
            Output("total-detections", "children"),
            Output("cleared-detections", "children"),
        ],
        [Input("interval", "n_intervals")],
    )
    def update_metrics(n_intervals):
        """Update the key metrics."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Count tiles
                total_tiles = session.query(LandsatTile).count()

                # Count processed tiles (those with NVMS results)
                processed_tiles = (
                    session.query(LandsatTile).join(NVMSResult).distinct().count()
                )

                # Count detections
                total_detections = session.query(NVMSDetection).count()

                # Count cleared detections from NVMSResult
                cleared_total = (
                    session.query(NVMSResult)
                    .filter(NVMSResult.cleared.isnot(None))
                    .all()
                )
                cleared_sum = sum(r.cleared or 0 for r in cleared_total)

                return (
                    str(total_tiles),
                    str(processed_tiles),
                    f"{total_detections:,}",
                    str(cleared_sum),
                )

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
            return "Error", "Error", "Error", "Error"

    @app.callback(
        Output("run-breakdown-chart", "figure"), [Input("interval", "n_intervals")]
    )
    def update_run_breakdown(n_intervals):
        """Show breakdown of processing by NVMS run."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                runs = session.query(NVMSRun).all()

                run_data = []
                for run in runs:
                    result_count = (
                        session.query(NVMSResult)
                        .filter(NVMSResult.run_id == run.run_id)
                        .count()
                    )
                    detection_count = (
                        session.query(NVMSDetection)
                        .filter(NVMSDetection.run_id == run.run_id)
                        .count()
                    )

                    run_data.append(
                        {
                            "Run": run.run_id.replace("NVMS_QLD_", ""),
                            "Tiles": result_count,
                            "Detections": detection_count,
                        }
                    )

                if not run_data:
                    return go.Figure().add_annotation(
                        text="No NVMS data", xref="paper", yref="paper", x=0.5, y=0.5
                    )

                df = pd.DataFrame(run_data)

                fig = px.bar(
                    df,
                    x="Run",
                    y=["Tiles", "Detections"],
                    title="NVMS Processing Summary by Run",
                    barmode="group",
                )
                fig.update_layout(height=300)
                return fig

        except Exception as e:
            logger.error(f"Error creating run breakdown: {e}")
            return go.Figure().add_annotation(
                text=f"Error: {str(e)}", xref="paper", yref="paper", x=0.5, y=0.5
            )

    @app.callback(
        Output("processing-timeline-chart", "figure"),
        [Input("interval", "n_intervals")],
    )
    def update_timeline(n_intervals):
        """Show processing timeline."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                results = (
                    session.query(NVMSResult)
                    .filter(NVMSResult.end_date_dt.isnot(None))
                    .all()
                )

                if not results:
                    return go.Figure().add_annotation(
                        text="No timeline data",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                    )

                timeline_data = []
                for result in results:
                    timeline_data.append(
                        {
                            "Date": result.end_date_dt.date(),
                            "Run": result.run_id.replace("NVMS_QLD_", ""),
                            "Detections": (result.cleared or 0)
                            + (result.not_cleared or 0),
                        }
                    )

                df = pd.DataFrame(timeline_data)

                # Group by date and run
                daily_summary = (
                    df.groupby(["Date", "Run"]).agg({"Detections": "sum"}).reset_index()
                )

                fig = px.line(
                    daily_summary,
                    x="Date",
                    y="Detections",
                    color="Run",
                    title="Detections Over Time by NVMS Run",
                )
                fig.update_layout(height=300)
                return fig

        except Exception as e:
            logger.error(f"Error creating timeline: {e}")
            return go.Figure().add_annotation(
                text=f"Error: {str(e)}", xref="paper", yref="paper", x=0.5, y=0.5
            )

    @app.callback(Output("main-map", "figure"), [Input("interval", "n_intervals")])
    def update_map(n_intervals):
        """Create map with tile boundaries color-coded by last NVMS run."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get all tiles with their last run info
                tiles = session.query(LandsatTile).all()

                if not tiles:
                    return go.Figure().add_annotation(
                        text="No tiles found", xref="paper", yref="paper", x=0.5, y=0.5
                    )

                # Find last run for each tile
                tile_data = []
                for tile in tiles:
                    # Get last NVMS result for this tile
                    last_result = (
                        session.query(NVMSResult)
                        .filter(NVMSResult.tile_id == tile.tile_id)
                        .order_by(NVMSResult.end_date_dt.desc())
                        .first()
                    )

                    last_run = None
                    if last_result:
                        if last_result.run_id == "NVMS_QLD_Run01":
                            last_run = "Run 1"
                        elif last_result.run_id == "NVMS_QLD_Run02":
                            last_run = "Run 2"
                        elif last_result.run_id == "NVMS_QLD_Run03":
                            last_run = "Run 3"
                    else:
                        last_run = "No runs"

                    tile_data.append(
                        {
                            "tile_id": tile.tile_id,
                            "lat": tile.center_lat,
                            "lon": tile.center_lon,
                            "last_run": last_run,
                            "path": tile.path,
                            "row": tile.row,
                            "bounds_geojson": tile.bounds_geojson,
                        }
                    )

                df = pd.DataFrame(tile_data)

                # Color mapping by last run
                color_map = {
                    "No runs": "black",
                    "Run 1": "yellow",
                    "Run 2": "orange",
                    "Run 3": "red",
                }

                # Create map figure
                fig = go.Figure()

                # Add tile boundaries if available
                tiles_with_bounds = df[df["bounds_geojson"].notna()]
                if len(tiles_with_bounds) > 0:
                    logger.info(f"Adding {len(tiles_with_bounds)} tile boundaries")

                    for _, tile in tiles_with_bounds.iterrows():
                        try:
                            bounds = json.loads(tile["bounds_geojson"])
                            coords = bounds["coordinates"][0]  # Assuming polygon

                            lons = [coord[0] for coord in coords]
                            lats = [coord[1] for coord in coords]

                            fig.add_trace(
                                go.Scattermapbox(
                                    mode="lines",
                                    lon=lons,
                                    lat=lats,
                                    line=dict(
                                        width=2, color=color_map[tile["last_run"]]
                                    ),
                                    name=tile["last_run"],
                                    showlegend=False,
                                    hovertemplate=f"<b>Tile {tile['tile_id']}</b><br>"
                                    + f"Path: {tile['path']}, Row: {tile['row']}<br>"
                                    + f"Last run: {tile['last_run']}<extra></extra>",
                                )
                            )
                        except Exception as e:
                            logger.error(
                                f"Error adding boundary for tile {tile['tile_id']}: {e}"
                            )
                            continue
                else:
                    # Fallback to center points if no boundaries
                    logger.info("No tile boundaries available, using center points")

                    for run_type in color_map.keys():
                        run_tiles = df[df["last_run"] == run_type]
                        if len(run_tiles) > 0:
                            fig.add_trace(
                                go.Scattermapbox(
                                    lat=run_tiles["lat"],
                                    lon=run_tiles["lon"],
                                    mode="markers",
                                    marker=dict(
                                        size=8, color=color_map[run_type], opacity=0.7
                                    ),
                                    text=run_tiles["tile_id"],
                                    name=run_type,
                                    hovertemplate="<b>Tile %{text}</b><br>Last run: "
                                    + run_type
                                    + "<extra></extra>",
                                )
                            )

                # Add detection points
                detections = (
                    session.query(NVMSDetection).limit(500).all()
                )  # Limit for performance
                if detections:
                    logger.info(f"Adding {len(detections)} detection points")

                    det_data = []
                    from shapely.geometry import shape

                    for det in detections:
                        if det.geom_geojson:
                            try:
                                geom = shape(det.geom_geojson)
                                centroid = geom.centroid
                                det_data.append(
                                    {
                                        "lat": centroid.y,
                                        "lon": centroid.x,
                                        "tile_id": det.tile_id,
                                        "run_id": det.run_id,
                                    }
                                )
                            except Exception:
                                continue

                    if det_data:
                        det_df = pd.DataFrame(det_data)
                        fig.add_trace(
                            go.Scattermapbox(
                                lat=det_df["lat"],
                                lon=det_df["lon"],
                                mode="markers",
                                marker=dict(size=4, color="blue", opacity=0.6),
                                name="Detections",
                                hovertemplate="<b>Detection</b><br>Tile: %{text}<extra></extra>",
                                text=det_df["tile_id"],
                            )
                        )

                # Update layout
                fig.update_layout(
                    mapbox_style="open-street-map",
                    mapbox=dict(
                        center=dict(lat=-25, lon=135), zoom=4  # Center on Australia
                    ),
                    height=600,
                    title="Landsat Tiles Color-Coded by Last NVMS Run",
                    legend=dict(x=0.02, y=0.98),
                )

                return fig

        except Exception as e:
            logger.error(f"Error creating map: {e}")
            return go.Figure().add_annotation(
                text=f"Error: {str(e)}", xref="paper", yref="paper", x=0.5, y=0.5
            )

    # Run the app
    print("Starting Enhanced EDS Dashboard...")
    print("Navigate to http://localhost:8050 in your browser")
    print("Features:")
    print("- NVMS data metrics and charts")
    print("- Tile boundaries color-coded by last run")
    print("- Black: No runs, Yellow: Run 1, Orange: Run 2, Red: Run 3")
    print("- Blue dots: Individual detections")
    print("Press Ctrl+C to stop")

    app.run_server(debug=True, host="0.0.0.0", port=8050)

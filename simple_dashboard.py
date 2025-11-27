#!/usr/bin/env python
"""
SIMPLE WORKING Dashboard - Focus on visibility and functionality
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output, callback_context
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime, timedelta
    import logging

    # Configure logging
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.config.settings import get_config

    # Initialize Dash app
    app = dash.Dash(__name__, 
                    title="EDS - Simple Dashboard",
                    external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])

    # Layout
    app.layout = html.Div([
        # Header
        html.Div([
            html.H1("🛰️ EDS - SIMPLE DASHBOARD (TILES VISIBLE)", 
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 10}),
            html.P("All Australia Landsat Tiles - Now Visible!", 
                  style={'textAlign': 'center', 'color': '#7f8c8d', 'marginBottom': 30}),
        ]),
        
        # Metrics row
        html.Div([
            html.Div([
                html.Div([
                    html.H2(id="tiles-count", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Total Tiles", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], style={'background': 'white', 'borderRadius': '8px', 'padding': '20px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #3498db'}),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="processed-count", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Processed Tiles", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], style={'background': 'white', 'borderRadius': '8px', 'padding': '20px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #e74c3c'}),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="detections-count", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Total Detections", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], style={'background': 'white', 'borderRadius': '8px', 'padding': '20px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #f39c12'}),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="cleared-count", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Cleared Areas", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], style={'background': 'white', 'borderRadius': '8px', 'padding': '20px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #27ae60'}),
            ], className="three columns"),
        ], className="row", style={'marginBottom': 30}),
        
        # Map controls
        html.Div([
            html.Div([
                html.Label("🗺️ Map Style:", style={'marginRight': 10, 'fontWeight': 'bold'}),
                dcc.RadioItems(
                    id='map-style-radio',
                    options=[
                        {'label': ' Street Map', 'value': 'open-street-map'},
                        {'label': ' Light Map', 'value': 'carto-positron'},
                        {'label': ' Dark Map', 'value': 'carto-darkmatter'},
                        {'label': ' Terrain', 'value': 'stamen-terrain'}
                    ],
                    value='open-street-map',
                    inline=True,
                    style={'marginLeft': 10}
                ),
            ], style={'marginBottom': '15px'}),
            
            html.Div([
                html.Label("Show Layers:", style={'marginRight': 10, 'fontWeight': 'bold'}),
                dcc.Checklist(
                    id='show-layers-check',
                    options=[
                        {'label': ' 🔲 Tile Boundaries', 'value': 'tiles'},
                        {'label': ' 🔵 Detection Points', 'value': 'detections'}
                    ],
                    value=['tiles'],
                    inline=True,
                    style={'marginLeft': 10}
                )
            ]),
            
            html.Div([
                html.Button("🔍 Zoom Queensland", id="zoom-qld-btn", n_clicks=0, 
                           style={'marginRight': '10px', 'backgroundColor': '#3498db', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
                html.Button("🌏 Zoom Australia", id="zoom-aus-btn", n_clicks=0,
                           style={'marginRight': '10px', 'backgroundColor': '#27ae60', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
                html.Button("🌍 Zoom Out Wide", id="zoom-wide-btn", n_clicks=0,
                           style={'backgroundColor': '#e74c3c', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
            ], style={'marginTop': '10px'})
        ], style={'marginBottom': 20, 'padding': 15, 'backgroundColor': '#f8f9fa', 'borderRadius': 8, 'border': '1px solid #dee2e6'}),
        
        # Map
        html.Div([
            dcc.Graph(id="simple-map", style={'height': '700px'})
        ]),
        
        # Update interval
        dcc.Interval(id='update-interval', interval=30000, n_intervals=0)
    ], style={'fontFamily': 'Arial, sans-serif', 'backgroundColor': '#f8f9fa', 'padding': '20px'})

    # Callbacks
    @app.callback(
        [Output('tiles-count', 'children'),
         Output('processed-count', 'children'),
         Output('detections-count', 'children'),
         Output('cleared-count', 'children')],
        [Input('update-interval', 'n_intervals')]
    )
    def update_counts(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                total_tiles = session.query(LandsatTile).count()
                processed_tiles = session.query(LandsatTile).join(NVMSResult).distinct().count()
                total_detections = session.query(NVMSDetection).count()
                
                cleared_results = session.query(NVMSResult).filter(NVMSResult.cleared.isnot(None)).all()
                cleared_sum = sum(r.cleared or 0 for r in cleared_results)

                return str(total_tiles), str(processed_tiles), f"{total_detections:,}", str(cleared_sum)

        except Exception as e:
            return "Error", "Error", "Error", "Error"

    @app.callback(
        Output('simple-map', 'figure'),
        [Input('map-style-radio', 'value'),
         Input('show-layers-check', 'value'),
         Input('zoom-qld-btn', 'n_clicks'),
         Input('zoom-aus-btn', 'n_clicks'),
         Input('zoom-wide-btn', 'n_clicks'),
         Input('update-interval', 'n_intervals')]
    )
    def update_simple_map(map_style, show_layers, zoom_qld_clicks, zoom_aus_clicks, zoom_wide_clicks, n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            # Determine zoom level and center
            ctx = callback_context
            center_lat, center_lon, zoom = -25, 135, 5
            
            if ctx.triggered:
                button_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if button_id == 'zoom-qld-btn':
                    center_lat, center_lon, zoom = -23, 145, 7
                elif button_id == 'zoom-aus-btn':
                    center_lat, center_lon, zoom = -25, 135, 5
                elif button_id == 'zoom-wide-btn':
                    center_lat, center_lon, zoom = -25, 135, 3

            # Calculate marker size based on zoom level
            # Zoom 3-4: size 8-12, Zoom 5-6: size 15-18, Zoom 7+: size 20-25
            if zoom <= 4:
                marker_size = max(8, min(12, zoom * 3))
            elif zoom <= 6:
                marker_size = max(12, min(18, zoom * 3))
            else:
                marker_size = max(18, min(25, zoom * 3.5))

            with db.get_session() as session:
                fig = go.Figure()
                
                # Add tile boundaries as zoom-responsive circles
                if 'tiles' in show_layers:
                    tiles = session.query(LandsatTile).all()
                    print(f"Adding {len(tiles)} tiles to map (size: {marker_size}px at zoom {zoom})")
                    
                    # Color coding
                    tile_colors = []
                    tile_lats = []
                    tile_lons = []
                    tile_texts = []
                    
                    for tile in tiles:
                        if tile.center_lat and tile.center_lon:
                            # Check EDS run status
                            last_result = session.query(NVMSResult).filter(
                                NVMSResult.tile_id == tile.tile_id
                            ).first()
                            
                            if last_result:
                                if 'Run01' in last_result.run_id:
                                    color = 'yellow'
                                elif 'Run02' in last_result.run_id:
                                    color = 'orange'
                                elif 'Run03' in last_result.run_id:
                                    color = 'red'
                                else:
                                    color = 'gray'
                            else:
                                color = 'gray'
                            
                            tile_colors.append(color)
                            tile_lats.append(tile.center_lat)
                            tile_lons.append(tile.center_lon)
                            tile_texts.append(f"{tile.tile_id}<br>Path: {tile.path:03d}, Row: {tile.row:03d}")
                    
                    # Add all tiles as one trace with zoom-responsive size
                    if tile_lats:
                        fig.add_trace(go.Scattermapbox(
                            lat=tile_lats,
                            lon=tile_lons,
                            mode='markers',
                            marker=dict(
                                size=marker_size,  # Dynamic size based on zoom
                                color=tile_colors,
                                opacity=0.8
                            ),
                            text=tile_texts,
                            name='EDS Tiles',
                            hovertemplate='<b>%{text}</b><extra></extra>'
                        ))

                # Add detection points
                if 'detections' in show_layers:
                    detections = session.query(NVMSDetection).limit(100).all()
                    if detections:
                        det_lats, det_lons, det_tiles = [], [], []
                        from shapely.geometry import shape
                        
                        for det in detections:
                            if det.geom_geojson:
                                try:
                                    geom = shape(det.geom_geojson)
                                    centroid = geom.centroid
                                    det_lats.append(centroid.y)
                                    det_lons.append(centroid.x)
                                    det_tiles.append(det.tile_id)
                                except:
                                    continue
                        
                        if det_lats:
                            fig.add_trace(go.Scattermapbox(
                                lat=det_lats,
                                lon=det_lons,
                                mode='markers',
                                marker=dict(size=8, color='blue'),
                                name='Detections',
                                text=det_tiles,
                                hovertemplate='<b>Detection</b><br>Tile: %{text}<extra></extra>'
                            ))

                # Simple map configuration
                fig.update_layout(
                    mapbox=dict(
                        style=map_style,
                        center=dict(lat=center_lat, lon=center_lon),
                        zoom=zoom
                    ),
                    height=700,
                    title=f'🗺️ EDS Australia Tiles - {map_style.replace("-", " ").title()}',
                    showlegend=True,
                    margin=dict(r=0, t=40, l=0, b=0)
                )

                return fig

        except Exception as e:
            logger.error(f"Map error: {e}")
            # Return empty map with error
            fig = go.Figure()
            fig.add_annotation(
                text=f"Map Error: {e}",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False
            )
            fig.update_layout(height=700, title="Map Error")
            return fig

    # Run the app
    print("🚀 STARTING SIMPLE DASHBOARD")
    print("=" * 60)
    print(f"🌐 Local: http://localhost:8056")
    print(f"📍 Network: http://10.0.0.14:8056")
    print("")
    print("🎯 SIMPLIFIED FEATURES:")
    print("✅ ZOOM-RESPONSIVE tile markers (8-25px)")
    print("✅ Simple radio button map controls")
    print("✅ All 466 tiles as colored circles")
    print("✅ Working zoom buttons (3 levels)")
    print("✅ No complex layers - just tiles!")
    print("")
    print("📏 MARKER SIZES BY ZOOM:")
    print("- Wide view (zoom 3): 8-12px markers")
    print("- Australia (zoom 5): 15px markers") 
    print("- Queensland (zoom 7): 20-25px markers")
    print("")
    print("🎨 TILE COLORS:")
    print("- Gray: No EDS runs")
    print("- Yellow: EDS Run 1")
    print("- Orange: EDS Run 2")
    print("- Red: EDS Run 3")
    print("")
    print("Press Ctrl+C to stop")
    
    app.run_server(debug=False, host='0.0.0.0', port=8056)
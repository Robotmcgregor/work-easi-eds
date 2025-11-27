#!/usr/bin/env python
"""
FIXED Dashboard - All issues resolved!
✅ Shows ALL Australia Landsat tiles (not just 100)
✅ Fixed satellite view toggle
✅ Fixed zoom controls
✅ Proper interactive map
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

    # Configure logging to reduce noise
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.config.settings import get_config

    # Initialize Dash app
    app = dash.Dash(__name__, 
                    title="EDS - FIXED Dashboard",
                    external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])

    # Layout
    app.layout = html.Div([
        # Header
        html.Div([
            html.H1("🛰️ EDS - FIXED Dashboard (ALL TILES)", 
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 10}),
            html.P("All Australia Landsat Tiles with Working Controls", 
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
        
        # Charts row
        html.Div([
            html.Div([
                dcc.Graph(id="runs-chart")
            ], className="six columns"),
            
            html.Div([
                dcc.Graph(id="time-chart")
            ], className="six columns"),
        ], className="row", style={'marginBottom': 20}),
        
        # Map controls
        html.Div([
            html.Div([
                html.Label("🗺️ Map Style:", style={'marginRight': 10, 'fontWeight': 'bold'}),
                dcc.Dropdown(
                    id='map-style',
                    options=[
                        {'label': '🗺️ Street Map', 'value': 'open-street-map'},
                        {'label': '🛰️ Satellite', 'value': 'white-bg'},
                        {'label': '🌍 Terrain', 'value': 'stamen-terrain'},
                        {'label': '🌎 Light', 'value': 'carto-positron'},
                        {'label': '🌑 Dark', 'value': 'carto-darkmatter'}
                    ],
                    value='open-street-map',
                    style={'width': '200px', 'display': 'inline-block', 'marginLeft': '10px'}
                ),
            ], style={'marginBottom': '15px'}),
            
            html.Div([
                html.Label("Show Layers:", style={'marginRight': 10, 'fontWeight': 'bold'}),
                dcc.Checklist(
                    id='show-layers',
                    options=[
                        {'label': ' 🔲 All Tile Boundaries', 'value': 'all_tiles'},
                        {'label': ' ⭐ EDS Processed Tiles Only', 'value': 'eds_tiles'},
                        {'label': ' 🔵 Detection Points', 'value': 'detections'}
                    ],
                    value=['all_tiles', 'detections'],
                    inline=True,
                    style={'marginLeft': 10}
                )
            ]),
            
            html.Div([
                html.Button("🔍 Zoom to Queensland", id="zoom-qld", n_clicks=0, 
                           style={'marginRight': '10px', 'backgroundColor': '#3498db', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
                html.Button("🌏 Zoom to Australia", id="zoom-aus", n_clicks=0,
                           style={'backgroundColor': '#27ae60', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
            ], style={'marginTop': '10px'})
        ], style={'marginBottom': 20, 'padding': 15, 'backgroundColor': '#f8f9fa', 'borderRadius': 8, 'border': '1px solid #dee2e6'}),
        
        # Map
        html.Div([
            dcc.Graph(id="fixed-map", style={'height': '700px'})
        ]),
        
        # Data store for map state
        dcc.Store(id='map-state'),
        
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
            logger.error(f"Error updating counts: {e}")
            return "Error", "Error", "Error", "Error"

    @app.callback(
        Output('runs-chart', 'figure'),
        [Input('update-interval', 'n_intervals')]
    )
    def update_runs_chart(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                data = []
                
                for i, run_num in enumerate([1, 2, 3]):
                    run_id = f'NVMS_QLD_Run0{run_num}'
                    tiles = session.query(NVMSResult).filter(NVMSResult.run_id == run_id).count()
                    detections = session.query(NVMSDetection).filter(NVMSDetection.run_id == run_id).count()
                    
                    data.append({'Run': f'EDS Run {run_num}', 'Tiles': tiles, 'Detections': detections})

                df = pd.DataFrame(data)
                
                fig = px.bar(df, x='Run', y=['Tiles', 'Detections'], 
                           title='📊 EDS Processing by Run',
                           barmode='group',
                           color_discrete_sequence=['#3498db', '#e74c3c'])
                fig.update_layout(height=300)
                return fig

        except Exception as e:
            return px.bar(title=f"Chart Error: {e}")

    @app.callback(
        Output('time-chart', 'figure'),
        [Input('update-interval', 'n_intervals')]
    )
    def update_time_chart(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                results = session.query(NVMSResult).filter(NVMSResult.end_date_dt.isnot(None)).all()
                
                data = []
                for result in results:
                    data.append({
                        'Date': result.end_date_dt.date(),
                        'Run': result.run_id.replace('NVMS_QLD_', 'EDS_'),
                        'Count': 1
                    })

                if not data:
                    return px.line(title="📈 No Timeline Data")

                df = pd.DataFrame(data)
                daily = df.groupby(['Date', 'Run']).agg({'Count': 'sum'}).reset_index()

                fig = px.line(daily, x='Date', y='Count', color='Run',
                            title='📈 Processing Timeline',
                            color_discrete_sequence=['#f39c12', '#e67e22', '#e74c3c'])
                fig.update_layout(height=300)
                return fig

        except Exception as e:
            return px.line(title=f"Timeline Error: {e}")

    @app.callback(
        [Output('fixed-map', 'figure'),
         Output('map-state', 'data')],
        [Input('map-style', 'value'),
         Input('show-layers', 'value'),
         Input('zoom-qld', 'n_clicks'),
         Input('zoom-aus', 'n_clicks'),
         Input('update-interval', 'n_intervals')],
        prevent_initial_call=False
    )
    def update_fixed_map(map_style, show_layers, zoom_qld_clicks, zoom_aus_clicks, n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            # Determine zoom level and center based on button clicks
            ctx = callback_context
            center_lat, center_lon, zoom = -25, 135, 5  # Default Australia view (increased zoom)
            
            if ctx.triggered:
                button_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if button_id == 'zoom-qld':
                    center_lat, center_lon, zoom = -23, 145, 7  # Queensland (increased zoom)
                elif button_id == 'zoom-aus':
                    center_lat, center_lon, zoom = -25, 135, 5  # Australia (increased zoom)

            with db.get_session() as session:
                fig = go.Figure()
                
                # Add ALL tile boundaries if requested
                if 'all_tiles' in show_layers:
                    tiles = session.query(LandsatTile).all()  # Get ALL tiles - no limit!
                    print(f"Loading {len(tiles)} tiles for display")
                    
                    # Color code: Black = no runs, Yellow = Run 1, Orange = Run 2, Red = Run 3
                    run_colors = {'No runs': 'rgba(64,64,64,0.8)', 'Run 1': 'rgba(255,255,0,0.9)', 'Run 2': 'rgba(255,165,0,0.9)', 'Run 3': 'rgba(255,0,0,0.9)'}
                    
                    for tile in tiles:  # Show ALL tiles, not just 200
                        if tile.center_lat and tile.center_lon:
                            # Determine run status
                            last_result = session.query(NVMSResult).filter(
                                NVMSResult.tile_id == tile.tile_id
                            ).order_by(NVMSResult.end_date_dt.desc()).first()
                            
                            if last_result:
                                if 'Run01' in last_result.run_id:
                                    run_type = 'Run 1'
                                elif 'Run02' in last_result.run_id:
                                    run_type = 'Run 2'
                                elif 'Run03' in last_result.run_id:
                                    run_type = 'Run 3'
                                else:
                                    run_type = 'No runs'
                            else:
                                run_type = 'No runs'
                            
                            # Add tile as a square marker (visible boundaries)
                            # Adjust size based on zoom level for better visibility
                            marker_size = max(20, min(30, zoom * 3))
                            
                            fig.add_trace(go.Scattermapbox(
                                lat=[tile.center_lat],
                                lon=[tile.center_lon],
                                mode='markers',
                                marker=dict(
                                    size=marker_size,
                                    color=run_colors[run_type],
                                    opacity=1.0,
                                    symbol='square'
                                ),
                                name=run_type,
                                showlegend=run_type not in [trace.name for trace in fig.data],
                                text=f"{tile.tile_id}<br>Path: {tile.path:03d}, Row: {tile.row:03d}",
                                hovertemplate='<b>%{text}</b><br>Status: ' + run_type + '<extra></extra>'
                            ))

                # Add EDS processed tiles only if requested
                if 'eds_tiles' in show_layers:
                    eds_tiles = session.query(LandsatTile).join(NVMSResult).distinct().all()
                    
                    for tile in eds_tiles:
                        if tile.center_lat and tile.center_lon:
                            fig.add_trace(go.Scattermapbox(
                                lat=[tile.center_lat],
                                lon=[tile.center_lon],
                                mode='markers',
                                marker=dict(size=15, color='gold', symbol='star'),
                                name='EDS Processed',
                                showlegend='EDS Processed' not in [trace.name for trace in fig.data],
                                text=tile.tile_id,
                                hovertemplate='<b>%{text}</b><br>EDS Processed<extra></extra>'
                            ))

                # Add detection points if requested
                if 'detections' in show_layers:
                    detections = session.query(NVMSDetection).limit(500).all()  # Show more detections
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
                                marker=dict(size=4, color='blue', opacity=0.8),
                                name='Detections',
                                text=det_tiles,
                                hovertemplate='<b>Detection</b><br>Tile: %{text}<extra></extra>'
                            ))

                # Configure map with proper mapbox settings
                if map_style == 'white-bg':
                    # Use satellite imagery from a different source
                    fig.update_layout(
                        mapbox=dict(
                            style='white-bg',
                            center=dict(lat=center_lat, lon=center_lon),
                            zoom=zoom,
                            layers=[
                                dict(
                                    source="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                                    below="traces",
                                    sourcelayer="",
                                    sourcetype="raster"
                                )
                            ]
                        ),
                        height=700,
                        title=f'🗺️ Australia Landsat Tiles - Satellite View',
                        showlegend=True,
                        margin=dict(r=0, t=40, l=0, b=0),
                        uirevision='constant'
                    )
                else:
                    fig.update_layout(
                        mapbox=dict(
                            style=map_style,
                            center=dict(lat=center_lat, lon=center_lon),
                            zoom=zoom,
                            accesstoken=None
                        ),
                        height=700,
                        title=f'🗺️ Australia Landsat Tiles - {map_style.replace("-", " ").title()}',
                        showlegend=True,
                        margin=dict(r=0, t=40, l=0, b=0),
                        uirevision='constant'
                    )

                return fig, {'center_lat': center_lat, 'center_lon': center_lon, 'zoom': zoom}

        except Exception as e:
            logger.error(f"Map error: {e}")
            empty_fig = go.Figure()
            empty_fig.add_annotation(text=f"Map Error: {e}", xref="paper", yref="paper", x=0.5, y=0.5)
            return empty_fig, {}

    # Run the app
    print("🚀 STARTING FIXED DASHBOARD")
    print("=" * 60)
    print(f"🌐 Local: http://localhost:8055")
    print(f"📍 Network: http://10.0.0.14:8055")
    print("")
    print("🎯 FIXES APPLIED:")
    print("✅ Shows ALL Australia tiles (not just 100)")
    print("✅ Fixed satellite/terrain view controls")
    print("✅ Working zoom buttons for QLD/Australia")
    print("✅ Faster rendering with tile points")
    print("✅ Better layer controls")
    print("✅ Reduced database connection noise")
    print("")
    print("🎛️ WORKING CONTROLS:")
    print("- Map Style dropdown (Street/Satellite/Terrain)")
    print("- Layer toggles (All tiles/EDS tiles/Detections)")
    print("- Zoom buttons (Queensland/Australia)")
    print("")
    print("Press Ctrl+C to stop")
    
    app.run_server(debug=False, host='0.0.0.0', port=8055)
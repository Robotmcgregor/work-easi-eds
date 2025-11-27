#!/usr/bin/env python
"""
WORKING Dashboard - Port 8054 to avoid conflicts.
This replaces the old empty plots with real NVMS data and satellite view.
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
    app = dash.Dash(__name__, 
                    title="EDS - Working Dashboard",
                    external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])

    # Layout
    app.layout = html.Div([
        # Header
        html.Div([
            html.H1("🛰️ EDS - Working Dashboard", 
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 10}),
            html.P("Land Clearing Detection Dashboard with Real NVMS Data", 
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
            html.Label("🗺️ Map Style:", style={'marginRight': 10, 'fontWeight': 'bold'}),
            dcc.RadioItems(
                id='map-style',
                options=[
                    {'label': ' Street Map', 'value': 'open-street-map'},
                    {'label': ' 🛰️ Satellite', 'value': 'satellite'},
                    {'label': ' 🌍 Terrain', 'value': 'stamen-terrain'}
                ],
                value='open-street-map',
                inline=True,
                style={'marginLeft': 10}
            ),
            html.Br(),
            html.Label("Show Layers:", style={'marginRight': 10, 'fontWeight': 'bold'}),
            dcc.Checklist(
                id='show-layers',
                options=[
                    {'label': ' Tile Boundaries', 'value': 'tiles'},
                    {'label': ' Blue Detection Dots', 'value': 'detections'}
                ],
                value=['tiles', 'detections'],
                inline=True,
                style={'marginLeft': 10}
            )
        ], style={'marginBottom': 20, 'padding': 15, 'backgroundColor': '#f8f9fa', 'borderRadius': 8, 'border': '1px solid #dee2e6'}),
        
        # Map
        html.Div([
            dcc.Graph(id="working-map", style={'height': '600px'})
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
                colors = ['#3498db', '#e67e22', '#e74c3c']
                
                for i, run_num in enumerate([1, 2, 3]):
                    run_id = f'NVMS_QLD_Run0{run_num}'
                    tiles = session.query(NVMSResult).filter(NVMSResult.run_id == run_id).count()
                    detections = session.query(NVMSDetection).filter(NVMSDetection.run_id == run_id).count()
                    
                    data.append({'Run': f'Run {run_num}', 'Tiles': tiles, 'Detections': detections})

                df = pd.DataFrame(data)
                
                fig = px.bar(df, x='Run', y=['Tiles', 'Detections'], 
                           title='📊 NVMS Processing by Run',
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
                        'Run': result.run_id.replace('NVMS_QLD_', ''),
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
        Output('working-map', 'figure'),
        [Input('update-interval', 'n_intervals'),
         Input('map-style', 'value'),
         Input('show-layers', 'value')]
    )
    def update_working_map(n_intervals, map_style, show_layers):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                fig = go.Figure()
                
                # Add tile boundaries if requested
                if 'tiles' in show_layers:
                    tiles = session.query(LandsatTile).all()  # Show ALL tiles, not just 100
                    
                    run_colors = {'No runs': 'black', 'Run 1': 'yellow', 'Run 2': 'orange', 'Run 3': 'red'}
                    
                    for tile in tiles:
                        # Determine run type
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
                        
                        # Add tile boundary or center point
                        if tile.bounds_geojson:
                            try:
                                bounds = json.loads(tile.bounds_geojson)
                                coords = bounds['coordinates'][0]
                                
                                lons = [coord[0] for coord in coords]
                                lats = [coord[1] for coord in coords]
                                
                                fig.add_trace(go.Scattermapbox(
                                    mode='lines',
                                    lon=lons,
                                    lat=lats,
                                    line=dict(width=2, color=run_colors[run_type]),
                                    name=run_type,
                                    showlegend=False,
                                    hovertemplate=f'<b>{tile.tile_id}</b><br>{run_type}<extra></extra>'
                                ))
                            except:
                                # Fallback to center point
                                fig.add_trace(go.Scattermapbox(
                                    lat=[tile.center_lat],
                                    lon=[tile.center_lon],
                                    mode='markers',
                                    marker=dict(size=6, color=run_colors[run_type]),
                                    name=run_type,
                                    showlegend=False,
                                    text=tile.tile_id,
                                    hovertemplate=f'<b>%{{text}}</b><br>{run_type}<extra></extra>'
                                ))

                # Add detection points if requested
                if 'detections' in show_layers:
                    detections = session.query(NVMSDetection).limit(200).all()  # Limit for performance
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
                                marker=dict(size=4, color='blue', opacity=0.7),
                                name='Detections',
                                text=det_tiles,
                                hovertemplate='<b>Detection</b><br>Tile: %{text}<extra></extra>'
                            ))

                # Configure map
                fig.update_layout(
                    mapbox_style=map_style,
                    mapbox=dict(
                        center=dict(lat=-25, lon=135),
                        zoom=4,
                        accesstoken=None  # Required for satellite view
                    ),
                    height=600,
                    title=f'🗺️ Australia Landsat Tiles - {map_style.replace("-", " ").title()}',
                    showlegend=True,
                    margin=dict(r=0, t=40, l=0, b=0),
                    uirevision='constant'  # Preserve zoom/pan state
                )

                return fig

        except Exception as e:
            logger.error(f"Map error: {e}")
            return go.Figure().add_annotation(text=f"Map Error: {e}", xref="paper", yref="paper", x=0.5, y=0.5)

    # Run the app on a different port
    print("🚀 STARTING WORKING DASHBOARD")
    print("=" * 50)
    print(f"🌐 Local: http://localhost:8054")
    print(f"📍 Network: http://10.0.0.14:8054")
    print("")
    print("🎯 FEATURES:")
    print("✅ Real NVMS data (no empty plots)")
    print("✅ 4 metric cards with actual numbers")
    print("✅ Working charts showing run data")
    print("✅ 🛰️ Satellite view toggle") 
    print("✅ Tile boundaries color-coded by run")
    print("✅ Blue detection dots overlay")
    print("")
    print("🎛️ CONTROLS:")
    print("- Map Style: Street/Satellite/Terrain")
    print("- Show Layers: Tiles/Detections toggle")
    print("")
    print("Press Ctrl+C to stop")
    
    app.run_server(debug=True, host='0.0.0.0', port=8054)
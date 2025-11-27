#!/usr/bin/env python
"""
WORKING EDS Dashboard - Completely new version that will replace the old empty plots.
Features: NVMS data, tile boundaries, satellite/street view toggle, working charts.
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output, callback
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

    # Initialize Dash app with external stylesheets
    app = dash.Dash(__name__, 
                    title="EDS - Early Detection System",
                    external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])

    # Define the complete layout
    app.layout = html.Div([
        # Header
        html.Div([
            html.H1("🛰️ EDS - Early Detection System", 
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 10}),
            html.P("Land Clearing Detection Dashboard for Australia", 
                  style={'textAlign': 'center', 'color': '#7f8c8d', 'marginBottom': 30}),
        ]),
        
        # Metrics row
        html.Div([
            html.Div([
                html.Div([
                    html.H2(id="total-tiles-display", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Total Tiles", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], className="metric-box"),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="processed-tiles-display", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Processed Tiles", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], className="metric-box"),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="total-detections-display", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Total Detections", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], className="metric-box"),
            ], className="three columns"),
            
            html.Div([
                html.Div([
                    html.H2(id="cleared-areas-display", children="...", style={'margin': 0, 'color': '#2c3e50'}),
                    html.P("Cleared Areas", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                ], className="metric-box"),
            ], className="three columns"),
        ], className="row", style={'marginBottom': 30}),
        
        # Charts row
        html.Div([
            html.Div([
                dcc.Graph(id="nvms-runs-chart")
            ], className="six columns"),
            
            html.Div([
                dcc.Graph(id="timeline-chart")
            ], className="six columns"),
        ], className="row", style={'marginBottom': 20}),
        
        # Map controls
        html.Div([
            html.Label("Map Style:", style={'marginRight': 10, 'fontWeight': 'bold'}),
            dcc.RadioItems(
                id='map-style-selector',
                options=[
                    {'label': ' 🗺️ Street Map', 'value': 'open-street-map'},
                    {'label': ' 🛰️ Satellite', 'value': 'satellite'},
                    {'label': ' 🌍 Terrain', 'value': 'stamen-terrain'}
                ],
                value='open-street-map',
                inline=True,
                style={'marginLeft': 10}
            ),
            html.Label("Show Detections:", style={'marginLeft': 30, 'marginRight': 10, 'fontWeight': 'bold'}),
            dcc.Checklist(
                id='show-detections',
                options=[{'label': ' Blue dots', 'value': 'show'}],
                value=['show'],
                inline=True
            )
        ], style={'marginBottom': 20, 'padding': 10, 'backgroundColor': '#f8f9fa', 'borderRadius': 5}),
        
        # Map
        html.Div([
            dcc.Graph(id="main-map-display", style={'height': '600px'})
        ], style={'marginBottom': 20}),
        
        # Update interval
        dcc.Interval(id='refresh-interval', interval=30000, n_intervals=0)
    ], className="container-fluid", style={'fontFamily': 'Arial, sans-serif', 'backgroundColor': '#f8f9fa', 'padding': '20px'})
    
    # Add custom CSS to the app
    app.index_string = '''
    <!DOCTYPE html>
    <html>
        <head>
            {%metas%}
            <title>{%title%}</title>
            {%favicon%}
            {%css%}
            <style>
                .metric-box {
                    background: white;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    margin: 10px;
                    border-left: 4px solid #3498db;
                }
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
    '''

    # Callbacks
    @app.callback(
        [Output('total-tiles-display', 'children'),
         Output('processed-tiles-display', 'children'),
         Output('total-detections-display', 'children'),
         Output('cleared-areas-display', 'children')],
        [Input('refresh-interval', 'n_intervals')]
    )
    def update_metrics_display(n_intervals):
        """Update the key metrics with real NVMS data."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get real counts
                total_tiles = session.query(LandsatTile).count()
                processed_tiles = session.query(LandsatTile).join(NVMSResult).distinct().count()
                total_detections = session.query(NVMSDetection).count()
                
                # Get cleared areas count
                cleared_results = session.query(NVMSResult).filter(NVMSResult.cleared.isnot(None)).all()
                cleared_sum = sum(r.cleared or 0 for r in cleared_results)

                return str(total_tiles), str(processed_tiles), f"{total_detections:,}", str(cleared_sum)

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
            return "Error", "Error", "Error", "Error"

    @app.callback(
        Output('nvms-runs-chart', 'figure'),
        [Input('refresh-interval', 'n_intervals')]
    )
    def update_runs_chart(n_intervals):
        """Create NVMS runs breakdown chart."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                runs_data = []
                
                for run_num in [1, 2, 3]:
                    run_id = f'NVMS_QLD_Run0{run_num}'
                    tile_count = session.query(NVMSResult).filter(NVMSResult.run_id == run_id).count()
                    detection_count = session.query(NVMSDetection).filter(NVMSDetection.run_id == run_id).count()
                    
                    runs_data.append({
                        'Run': f'Run {run_num}',
                        'Tiles Processed': tile_count,
                        'Detections Found': detection_count
                    })

                df = pd.DataFrame(runs_data)
                
                fig = px.bar(df, x='Run', y=['Tiles Processed', 'Detections Found'], 
                           title='NVMS Processing Summary by Run',
                           barmode='group',
                           color_discrete_sequence=['#3498db', '#e74c3c'])
                fig.update_layout(height=300, showlegend=True)
                return fig

        except Exception as e:
            logger.error(f"Error creating runs chart: {e}")
            return px.bar(title="Error loading runs data")

    @app.callback(
        Output('timeline-chart', 'figure'),
        [Input('refresh-interval', 'n_intervals')]
    )
    def update_timeline_chart(n_intervals):
        """Create processing timeline chart."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                results = session.query(NVMSResult).filter(NVMSResult.end_date_dt.isnot(None)).all()
                
                timeline_data = []
                for result in results:
                    timeline_data.append({
                        'Date': result.end_date_dt.date(),
                        'Run': result.run_id.replace('NVMS_QLD_', ''),
                        'Detections': (result.cleared or 0) + (result.not_cleared or 0)
                    })

                if not timeline_data:
                    return px.line(title="No timeline data available")

                df = pd.DataFrame(timeline_data)
                
                # Group by date and run
                daily_summary = df.groupby(['Date', 'Run']).agg({
                    'Detections': 'sum'
                }).reset_index()

                fig = px.line(daily_summary, x='Date', y='Detections', color='Run',
                            title='Detections Over Time by NVMS Run',
                            color_discrete_sequence=['#f39c12', '#e67e22', '#e74c3c'])
                fig.update_layout(height=300)
                return fig

        except Exception as e:
            logger.error(f"Error creating timeline: {e}")
            return px.line(title="Error loading timeline data")

    @app.callback(
        Output('main-map-display', 'figure'),
        [Input('refresh-interval', 'n_intervals'),
         Input('map-style-selector', 'value'),
         Input('show-detections', 'value')]
    )
    def update_main_map(n_intervals, map_style, show_detections):
        """Create the main map with tile boundaries and detections."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get tiles with run information
                tiles = session.query(LandsatTile).all()
                
                if not tiles:
                    return go.Figure().add_annotation(text="No tiles found", 
                                                    xref="paper", yref="paper", x=0.5, y=0.5)

                # Create figure
                fig = go.Figure()
                
                # Process tiles by run type
                run_colors = {
                    'No runs': 'black',
                    'Run 1': 'yellow',
                    'Run 2': 'orange', 
                    'Run 3': 'red'
                }
                
                tiles_by_run = {'No runs': [], 'Run 1': [], 'Run 2': [], 'Run 3': []}
                
                for tile in tiles:
                    # Find last run for this tile
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
                    
                    tiles_by_run[run_type].append(tile)

                # Add tile boundaries or points for each run type
                for run_type, run_tiles in tiles_by_run.items():
                    if not run_tiles:
                        continue
                        
                    # Try to add boundaries, fallback to points
                    added_boundaries = False
                    for tile in run_tiles[:50]:  # Limit for performance
                        if tile.bounds_geojson:
                            try:
                                bounds = json.loads(tile.bounds_geojson)
                                coords = bounds['coordinates'][0]
                                
                                boundary_lons = [coord[0] for coord in coords]
                                boundary_lats = [coord[1] for coord in coords]
                                
                                fig.add_trace(go.Scattermapbox(
                                    mode='lines',
                                    lon=boundary_lons,
                                    lat=boundary_lats,
                                    line=dict(width=2, color=run_colors[run_type]),
                                    name=run_type if not added_boundaries else None,
                                    showlegend=not added_boundaries,
                                    hovertemplate=f'<b>Tile {tile.tile_id}</b><br>Last run: {run_type}<extra></extra>'
                                ))
                                added_boundaries = True
                            except Exception as e:
                                logger.error(f"Error adding boundary for {tile.tile_id}: {e}")
                    
                    # If no boundaries worked, add center points
                    if not added_boundaries and run_tiles:
                        lats = [t.center_lat for t in run_tiles]
                        lons = [t.center_lon for t in run_tiles]
                        tile_ids = [t.tile_id for t in run_tiles]
                        
                        fig.add_trace(go.Scattermapbox(
                            lat=lats,
                            lon=lons,
                            mode='markers',
                            marker=dict(size=6, color=run_colors[run_type], opacity=0.7),
                            text=tile_ids,
                            name=run_type,
                            hovertemplate='<b>Tile %{text}</b><br>Last run: ' + run_type + '<extra></extra>'
                        ))

                # Add detection points if requested
                if 'show' in show_detections:
                    detections = session.query(NVMSDetection).limit(500).all()  # Limit for performance
                    if detections:
                        det_data = []
                        from shapely.geometry import shape
                        
                        for det in detections:
                            if det.geom_geojson:
                                try:
                                    geom = shape(det.geom_geojson)
                                    centroid = geom.centroid
                                    det_data.append({
                                        'lat': centroid.y,
                                        'lon': centroid.x,
                                        'tile_id': det.tile_id
                                    })
                                except Exception:
                                    continue
                        
                        if det_data:
                            det_df = pd.DataFrame(det_data)
                            fig.add_trace(go.Scattermapbox(
                                lat=det_df['lat'],
                                lon=det_df['lon'],
                                mode='markers',
                                marker=dict(size=4, color='blue', opacity=0.6),
                                name='Detections',
                                text=det_df['tile_id'],
                                hovertemplate='<b>Detection</b><br>Tile: %{text}<extra></extra>'
                            ))

                # Configure map layout
                fig.update_layout(
                    mapbox_style=map_style,
                    mapbox=dict(
                        center=dict(lat=-25, lon=135),
                        zoom=4
                    ),
                    height=600,
                    title=f'Australian Landsat Tiles - {map_style.replace("-", " ").title()} View',
                    legend=dict(x=0.02, y=0.98),
                    margin=dict(r=0, t=40, l=0, b=0)
                )

                return fig

        except Exception as e:
            logger.error(f"Error creating main map: {e}")
            return go.Figure().add_annotation(text=f"Map Error: {str(e)}", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)

    # Run the app
    print("🚀 Starting NEW EDS Dashboard...")
    print("🌐 Navigate to: http://localhost:8050")
    print("📍 Network: http://10.0.0.14:8050")
    print("")
    print("✨ NEW FEATURES:")
    print("- Real NVMS metrics and charts")
    print("- Tile boundaries color-coded by run")
    print("- 🛰️ Satellite view toggle")
    print("- 🗺️ Street/terrain map options")
    print("- Detection overlay toggle")
    print("")
    print("Press Ctrl+C to stop")
    
    # Bind to all interfaces so it's accessible via network IP
    app.run_server(debug=True, host='0.0.0.0', port=8050)
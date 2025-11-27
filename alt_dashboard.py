#!/usr/bin/env python
"""
Alternative dashboard with different map configuration for compatibility.
"""

import sys
from pathlib import Path
import json

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output
    import plotly.graph_objects as go
    import pandas as pd

    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult
    from src.config.settings import get_config

    app = dash.Dash(__name__, title="Alternative Map Dashboard")

    app.layout = html.Div([
        html.H1("EDS - Alternative Map View", style={'textAlign': 'center'}),
        html.Div(id="map-status"),
        dcc.Graph(id="alt-map", style={'height': '700px'}),
        dcc.Interval(id='interval', interval=10000, n_intervals=0)
    ])

    @app.callback(
        [Output('map-status', 'children'),
         Output('alt-map', 'figure')],
        [Input('interval', 'n_intervals')]
    )
    def update_alt_map(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get all tiles
                tiles = session.query(LandsatTile).all()
                
                status_msg = f"Loaded {len(tiles)} tiles"
                
                if not tiles:
                    return html.P("No tiles found"), go.Figure()

                # Create figure with alternative map style
                fig = go.Figure()
                
                # Get tile data with run info
                tile_data = []
                for tile in tiles:
                    last_result = session.query(NVMSResult).filter(
                        NVMSResult.tile_id == tile.tile_id
                    ).order_by(NVMSResult.end_date_dt.desc()).first()
                    
                    if last_result:
                        if 'Run01' in last_result.run_id:
                            color = 'yellow'
                            run_type = 'Run 1'
                        elif 'Run02' in last_result.run_id:
                            color = 'orange'
                            run_type = 'Run 2'
                        elif 'Run03' in last_result.run_id:
                            color = 'red'
                            run_type = 'Run 3'
                        else:
                            color = 'gray'
                            run_type = 'Other'
                    else:
                        color = 'black'
                        run_type = 'No runs'
                    
                    tile_data.append({
                        'lat': tile.center_lat,
                        'lon': tile.center_lon,
                        'tile_id': tile.tile_id,
                        'color': color,
                        'run_type': run_type,
                        'bounds': tile.bounds_geojson
                    })

                df = pd.DataFrame(tile_data)
                
                # Add tile points grouped by color/run
                for run_type in ['No runs', 'Run 1', 'Run 2', 'Run 3']:
                    run_tiles = df[df['run_type'] == run_type]
                    if len(run_tiles) > 0:
                        color_map = {
                            'No runs': 'black',
                            'Run 1': 'yellow', 
                            'Run 2': 'orange',
                            'Run 3': 'red'
                        }
                        
                        fig.add_trace(go.Scattermapbox(
                            lat=run_tiles['lat'],
                            lon=run_tiles['lon'],
                            mode='markers',
                            marker=dict(size=6, color=color_map[run_type], opacity=0.8),
                            text=run_tiles['tile_id'],
                            name=run_type,
                            hovertemplate='<b>%{text}</b><br>Run: ' + run_type + '<extra></extra>'
                        ))

                # Try different map styles
                for style in ['open-street-map', 'carto-positron', 'stamen-terrain']:
                    try:
                        fig.update_layout(
                            mapbox_style=style,
                            mapbox=dict(
                                center=dict(lat=-25, lon=135),
                                zoom=4
                            ),
                            height=700,
                            title=f'Landsat Tiles - Using {style} basemap',
                            showlegend=True
                        )
                        status_msg += f" | Using {style} basemap"
                        break
                    except:
                        continue

                return html.P(status_msg), fig

        except Exception as e:
            return html.P(f"Error: {e}"), go.Figure()

    print("🗺️ Starting ALTERNATIVE DASHBOARD...")
    print("Navigate to http://localhost:8053 in your browser")
    print("This uses different map settings that might work better")
    print("Press Ctrl+C to stop")
    
    app.run_server(debug=True, host='0.0.0.0', port=8053)
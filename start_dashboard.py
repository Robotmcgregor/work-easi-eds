"""
Start the EDS dashboard with NVMS detection visualization.
"""

import sys
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    from datetime import datetime
    import logging

    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult
    from src.config.settings import get_config

    # Initialize Dash app
    app = dash.Dash(__name__, title="EDS - Early Detection System")

    # Simple layout for testing
    app.layout = html.Div([
        html.H1("EDS - Early Detection System", style={'textAlign': 'center'}),
        html.P("Land Clearing Detection Dashboard for Australia", style={'textAlign': 'center'}),
        dcc.Graph(id="main-map"),
        dcc.Interval(id='interval', interval=10000, n_intervals=0)  # Update every 10s
    ])

    @app.callback(
        Output('main-map', 'figure'),
        [Input('interval', 'n_intervals')]
    )
    def update_map(n_intervals):
        """Create map with tiles and NVMS detections."""
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get tiles
                tiles = session.query(LandsatTile).filter(LandsatTile.is_active == True).all()
                
                if not tiles:
                    return go.Figure().add_annotation(text="No active tiles found", 
                                                    xref="paper", yref="paper", x=0.5, y=0.5)

                # Prepare tile data
                tile_data = []
                for tile in tiles:
                    tile_data.append({
                        'tile_id': tile.tile_id,
                        'lat': tile.center_lat,
                        'lon': tile.center_lon,
                        'status': tile.status,
                        'path': tile.path,
                        'row': tile.row
                    })

                df = pd.DataFrame(tile_data)
                
                # Color map for tile status
                color_map = {
                    'completed': 'green',
                    'processing': 'orange', 
                    'pending': 'gray',
                    'failed': 'red'
                }
                
                # Create base map with tiles
                fig = px.scatter_mapbox(
                    df,
                    lat='lat',
                    lon='lon',
                    hover_name='tile_id',
                    hover_data={'path': True, 'row': True, 'status': True},
                    color='status',
                    color_discrete_map=color_map,
                    size_max=15,
                    zoom=4,
                    height=600,
                    title="Australian Landsat Tiles & NVMS Detections"
                )
                fig.update_layout(mapbox_style='open-street-map')
                fig.update_traces(marker={'size': 8, 'opacity': 0.7})

                # Add NVMS detection overlay
                detections = session.query(NVMSDetection).all()
                if detections:
                    logger.info(f"Found {len(detections)} NVMS detections")
                    
                    det_data = []
                    from shapely.geometry import shape
                    
                    for det in detections[:100]:  # Limit to first 100 for performance
                        if det.geom_geojson:
                            try:
                                geom = shape(det.geom_geojson)
                                centroid = geom.centroid
                                det_data.append({
                                    'lat': centroid.y,
                                    'lon': centroid.x,
                                    'tile_id': det.tile_id,
                                    'run_id': det.run_id
                                })
                            except Exception as e:
                                logger.error(f"Error processing detection geometry: {e}")
                                continue
                    
                    if det_data:
                        det_df = pd.DataFrame(det_data)
                        
                        # Add detection points as red markers
                        fig.add_trace(go.Scattermapbox(
                            lat=det_df['lat'],
                            lon=det_df['lon'],
                            mode='markers',
                            marker=dict(size=6, color='red', opacity=0.8),
                            text=det_df['tile_id'],
                            hovertemplate='<b>Detection</b><br>Tile: %{text}<br>Run: ' + det_df['run_id'].astype(str) + '<extra></extra>',
                            name='NVMS Detections'
                        ))
                        
                        logger.info(f"Added {len(det_data)} detection markers to map")

                return fig

        except Exception as e:
            logger.error(f"Error creating map: {e}")
            return go.Figure().add_annotation(text=f"Error: {str(e)}", 
                                            xref="paper", yref="paper", x=0.5, y=0.5)

    # Run the app
    print("Starting EDS Dashboard...")
    print("Navigate to http://localhost:8050 in your browser")
    print("Press Ctrl+C to stop")
    app.run_server(debug=True, host='0.0.0.0', port=8050)
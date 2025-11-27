"""
Main dashboard application using Dash/Plotly for the EDS system.
"""

import dash
from dash import dcc, html, Input, Output, State
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import json
import logging

from ..database import TileManager, JobManager, AlertManager, SystemStatusManager
from ..processing import EDSPipelineManager, get_scheduler_status
from ..database.connection import DatabaseManager
from ..database.nvms_models import NVMSDetection

logger = logging.getLogger(__name__)

# Initialize Dash app
app = dash.Dash(__name__, title="EDS - Early Detection System")

# Define the layout
app.layout = html.Div([
    dcc.Store(id='tile-data-store'),
    dcc.Store(id='alert-data-store'),
    dcc.Interval(
        id='interval-component',
        interval=30*1000,  # Update every 30 seconds
        n_intervals=0
    ),
    
    # Header
    html.Div([
        html.H1("EDS - Early Detection System", className="header-title"),
        html.P("Land Clearing Detection Dashboard for Australia", className="header-subtitle"),
        html.Div(id="system-status", className="system-status"),
    ], className="header"),
    
    # Main content tabs
    dcc.Tabs(id="main-tabs", value="overview", children=[
        
        # Overview Tab
        dcc.Tab(label="Overview", value="overview", children=[
            html.Div([
                
                # Key metrics row
                html.Div([
                    html.Div([
                        html.H3(id="total-tiles"),
                        html.P("Total Tiles")
                    ], className="metric-card"),
                    
                    html.Div([
                        html.H3(id="active-jobs"),
                        html.P("Active Jobs")
                    ], className="metric-card"),
                    
                    html.Div([
                        html.H3(id="alerts-today"),
                        html.P("Alerts Today")
                    ], className="metric-card"),
                    
                    html.Div([
                        html.H3(id="processing-rate"),
                        html.P("Processing Rate")
                    ], className="metric-card"),
                ], className="metrics-row"),
                
                # Charts row
                html.Div([
                    html.Div([
                        dcc.Graph(id="tile-status-chart")
                    ], className="chart-container"),
                    
                    html.Div([
                        dcc.Graph(id="processing-timeline")
                    ], className="chart-container"),
                ], className="charts-row"),
                
                # Map and alerts
                html.Div([
                    html.Div([
                        dcc.Graph(id="tile-map")
                    ], className="map-container"),
                    
                    html.Div([
                        html.H4("Recent Alerts"),
                        html.Div(id="recent-alerts-list")
                    ], className="alerts-container"),
                ], className="map-alerts-row"),
                
            ])
        ]),
        
        # Tile Management Tab
        dcc.Tab(label="Tile Management", value="tiles", children=[
            html.Div([
                
                # Tile controls
                html.Div([
                    html.Div([
                        html.Label("Select Tile(s):"),
                        dcc.Dropdown(
                            id="tile-selector",
                            multi=True,
                            placeholder="Select tiles to process..."
                        ),
                    ], className="control-group"),
                    
                    html.Div([
                        html.Label("Processing Options:"),
                        html.Div([
                            html.Button("Process Selected", id="process-selected-btn", className="btn-primary"),
                            html.Button("Process All Pending", id="process-pending-btn", className="btn-secondary"),
                            html.Button("Process All", id="process-all-btn", className="btn-warning"),
                        ], className="button-group"),
                    ], className="control-group"),
                    
                    html.Div([
                        html.Label("Time Range (days back):"),
                        dcc.Slider(
                            id="days-back-slider",
                            min=1,
                            max=30,
                            value=7,
                            marks={i: f"{i}d" for i in [1, 7, 14, 30]},
                            tooltip={"placement": "bottom", "always_visible": True}
                        ),
                    ], className="control-group"),
                    
                ], className="tile-controls"),
                
                # Tile status table
                html.Div([
                    html.H4("Tile Status"),
                    html.Div(id="tile-status-table")
                ], className="table-container"),
                
            ])
        ]),
        
        # Processing Jobs Tab
        dcc.Tab(label="Processing Jobs", value="jobs", children=[
            html.Div([
                
                # Job filters
                html.Div([
                    html.Div([
                        html.Label("Status Filter:"),
                        dcc.Dropdown(
                            id="job-status-filter",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "Processing", "value": "processing"},
                                {"label": "Completed", "value": "completed"},
                                {"label": "Failed", "value": "failed"},
                            ],
                            value="all"
                        ),
                    ], className="filter-group"),
                    
                    html.Div([
                        html.Label("Time Range:"),
                        dcc.DatePickerRange(
                            id="job-date-range",
                            start_date=datetime.now() - timedelta(days=7),
                            end_date=datetime.now(),
                            display_format="YYYY-MM-DD"
                        ),
                    ], className="filter-group"),
                    
                ], className="job-filters"),
                
                # Jobs table
                html.Div([
                    html.H4("Processing Jobs"),
                    html.Div(id="jobs-table")
                ], className="table-container"),
                
            ])
        ]),
        
        # Alerts Tab
        dcc.Tab(label="Alerts", value="alerts", children=[
            html.Div([
                
                # Alert filters
                html.Div([
                    html.Div([
                        html.Label("Verification Status:"),
                        dcc.Dropdown(
                            id="alert-verification-filter",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "Pending", "value": "pending"},
                                {"label": "Confirmed", "value": "confirmed"},
                                {"label": "False Positive", "value": "false_positive"},
                            ],
                            value="all"
                        ),
                    ], className="filter-group"),
                    
                    html.Div([
                        html.Label("Confidence Threshold:"),
                        dcc.Slider(
                            id="confidence-threshold",
                            min=0,
                            max=1,
                            value=0.7,
                            step=0.1,
                            marks={i/10: f"{i/10:.1f}" for i in range(0, 11, 2)},
                            tooltip={"placement": "bottom", "always_visible": True}
                        ),
                    ], className="filter-group"),
                    
                ], className="alert-filters"),
                
                # Alerts chart and table
                html.Div([
                    html.Div([
                        dcc.Graph(id="alerts-map")
                    ], className="chart-container"),
                    
                    html.Div([
                        html.H4("Detection Alerts"),
                        html.Div(id="alerts-table")
                    ], className="table-container"),
                ], className="alerts-content"),
                
            ])
        ]),
        
        # System Tab
        dcc.Tab(label="System", value="system", children=[
            html.Div([
                
                # System status
                html.Div([
                    html.H4("System Status"),
                    html.Div(id="system-health-status"),
                ], className="system-status-container"),
                
                # Scheduler status
                html.Div([
                    html.H4("Scheduler"),
                    html.Div(id="scheduler-status"),
                    html.Div([
                        html.Button("Start Scheduler", id="start-scheduler-btn", className="btn-primary"),
                        html.Button("Stop Scheduler", id="stop-scheduler-btn", className="btn-secondary"),
                    ], className="scheduler-controls"),
                ], className="scheduler-container"),
                
                # Database statistics
                html.Div([
                    html.H4("Database Statistics"),
                    html.Div(id="database-stats"),
                ], className="db-stats-container"),
                
            ])
        ]),
        
    ]),
    
    # Processing status modal
    html.Div([
        html.Div([
            html.H3("Processing Status"),
            html.Div(id="processing-status-content"),
            html.Button("Close", id="close-modal-btn", className="btn-secondary"),
        ], className="modal-content"),
    ], id="processing-modal", className="modal"),
    
], className="app-container")


# Callbacks for interactivity
@app.callback(
    [Output('tile-data-store', 'data'),
     Output('alert-data-store', 'data')],
    [Input('interval-component', 'n_intervals')]
)
def update_data_stores(n):
    """Update data stores with fresh data from database."""
    try:
        # Get tile data
        tiles = TileManager.get_all_tiles()
        tile_data = []
        for tile in tiles:
            tile_data.append({
                'tile_id': tile.tile_id,
                'path': tile.path,
                'row': tile.row,
                'status': tile.status,
                'center_lat': tile.center_lat,
                'center_lon': tile.center_lon,
                'last_processed': tile.last_processed.isoformat() if tile.last_processed else None,
                'priority': tile.processing_priority,
                'is_active': tile.is_active,
            })
        
        # Get recent alerts
        alerts = AlertManager.get_recent_alerts(hours_back=24)
        alert_data = []
        for alert in alerts:
            alert_data.append({
                'alert_id': alert.alert_id,
                'tile_id': alert.tile_id,
                'detection_lat': alert.detection_lat,
                'detection_lon': alert.detection_lon,
                'detection_date': alert.detection_date.isoformat(),
                'confidence_score': alert.confidence_score,
                'area_hectares': alert.area_hectares,
                'clearing_type': alert.clearing_type,
                'verification_status': alert.verification_status,
            })
        
        return tile_data, alert_data
        
    except Exception as e:
        logger.error(f"Error updating data stores: {e}")
        return [], []


@app.callback(
    [Output('total-tiles', 'children'),
     Output('active-jobs', 'children'),
     Output('alerts-today', 'children'),
     Output('processing-rate', 'children'),
     Output('system-status', 'children')],
    [Input('tile-data-store', 'data'),
     Input('alert-data-store', 'data')]
)
def update_overview_metrics(tile_data, alert_data):
    """Update the overview metrics."""
    try:
        # Calculate metrics
        total_tiles = len([t for t in tile_data if t['is_active']])
        
        # Get system stats
        stats = SystemStatusManager.get_system_stats()
        active_jobs = stats.get('active_jobs', 0)
        alerts_today = stats.get('alerts_today', 0)
        
        # Calculate processing rate (tiles processed today)
        processing_rate = stats.get('jobs_today', 0)
        
        # System status indicator
        status_color = "green"  # Assume healthy
        status_text = "System Healthy"
        
        status_div = html.Div([
            html.Span("●", style={"color": status_color, "font-size": "20px"}),
            html.Span(f" {status_text}", style={"margin-left": "5px"})
        ])
        
        return str(total_tiles), str(active_jobs), str(alerts_today), str(processing_rate), status_div
        
    except Exception as e:
        logger.error(f"Error updating metrics: {e}")
        return "Error", "Error", "Error", "Error", "Error"


@app.callback(
    Output('tile-status-chart', 'figure'),
    [Input('tile-data-store', 'data')]
)
def update_tile_status_chart(tile_data):
    """Update the tile status pie chart."""
    try:
        if not tile_data:
            return go.Figure()
        
        df = pd.DataFrame(tile_data)
        active_tiles = df[df['is_active'] == True]
        
        status_counts = active_tiles['status'].value_counts()
        
        fig = px.pie(
            values=status_counts.values,
            names=status_counts.index,
            title="Tile Processing Status",
            color_discrete_map={
                'completed': '#28a745',
                'processing': '#ffc107', 
                'pending': '#6c757d',
                'failed': '#dc3545'
            }
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Error creating tile status chart: {e}")
        return go.Figure()


@app.callback(
    Output('tile-map', 'figure'),
    [Input('tile-data-store', 'data')]
)
def update_tile_map(tile_data):
    """Update the tile map visualization."""
    try:
        if not tile_data:
            return go.Figure()
        
        df = pd.DataFrame(tile_data)
        active_tiles = df[df['is_active'] == True]
        
        # Color mapping for status
        color_map = {
            'completed': 'green',
            'processing': 'orange',
            'pending': 'gray',
            'failed': 'red'
        }
        
        colors = [color_map.get(status, 'gray') for status in active_tiles['status']]
        
        # Use Mapbox OpenStreetMap style for a free basemap and overlay detections
        # Create base figure with tiles as scatter_mapbox
        try:
            # Prepare tile scatter
            tile_fig = px.scatter_mapbox(
                active_tiles,
                lat='center_lat',
                lon='center_lon',
                hover_name='tile_id',
                hover_data={'path':True,'row':True,'status':True},
                color=active_tiles['status'].map(lambda s: color_map.get(s, 'gray')),
                size_max=10,
                zoom=4,
                height=500
            )
            tile_fig.update_layout(mapbox_style='open-street-map')
            tile_fig.update_traces(marker={'size':8, 'opacity':0.8})

            # Query NVMS detections and overlay as small red markers
            config = None
            try:
                from ..config.settings import get_config
                config = get_config()
            except Exception:
                config = None

            if config is not None:
                db = DatabaseManager(config.database.connection_url)
                with db.get_session() as session:
                    detections = session.query(NVMSDetection).all()
                    if detections:
                        from shapely.geometry import shape
                        rows = []
                        for det in detections:
                            geom_json = det.geom_geojson
                            if not geom_json:
                                continue
                            try:
                                shp = shape(geom_json)
                            except Exception as e:
                                logger.error(f"Error converting geometry JSON for detection {getattr(det,'id',None)}: {e}")
                                continue
                            centroid = shp.centroid
                            rows.append({
                                'lon': centroid.x,
                                'lat': centroid.y,
                                'tile_id': det.tile_id,
                                'run_id': det.run_id,
                            })
                        if rows:
                            ddf = pd.DataFrame(rows)
                            det_fig = px.scatter_mapbox(
                                ddf,
                                lat='lat', lon='lon', hover_name='tile_id',
                                color_discrete_sequence=['red'],
                                size_max=6,
                                zoom=4,
                            )
                            det_fig.update_traces(marker={'size':6, 'opacity':0.9})
                            det_fig.update_layout(mapbox_style='open-street-map')

                            # Combine layers by adding traces from det_fig to tile_fig
                            for trace in det_fig.data:
                                tile_fig.add_trace(trace)

            tile_fig.update_layout(title='Landsat Tiles & NVMS Detections (OpenStreetMap)')
            return tile_fig

        except Exception as e:
            logger.error(f"Error creating mapbox map: {e}")
            return go.Figure()
        
    except Exception as e:
        logger.error(f"Error creating tile map: {e}")
        return go.Figure()


# Add CSS styling
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            .app-container { font-family: Arial, sans-serif; margin: 0; padding: 0; }
            .header { background: #2c3e50; color: white; padding: 20px; text-align: center; }
            .header-title { margin: 0; font-size: 2.5em; }
            .header-subtitle { margin: 10px 0 0 0; font-size: 1.2em; opacity: 0.8; }
            .system-status { margin-top: 10px; }
            .metrics-row { display: flex; justify-content: space-around; padding: 20px; }
            .metric-card { background: white; border-radius: 8px; padding: 20px; text-align: center; 
                          box-shadow: 0 2px 4px rgba(0,0,0,0.1); min-width: 150px; }
            .metric-card h3 { margin: 0; font-size: 2em; color: #2c3e50; }
            .metric-card p { margin: 10px 0 0 0; color: #7f8c8d; }
            .charts-row { display: flex; padding: 20px; gap: 20px; }
            .chart-container { flex: 1; background: white; border-radius: 8px; 
                              box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .map-alerts-row { display: flex; padding: 20px; gap: 20px; }
            .map-container { flex: 2; background: white; border-radius: 8px; 
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .alerts-container { flex: 1; background: white; border-radius: 8px; 
                               box-shadow: 0 2px 4px rgba(0,0,0,0.1); padding: 20px; }
            .btn-primary { background: #3498db; color: white; border: none; padding: 10px 20px; 
                          border-radius: 4px; cursor: pointer; margin: 5px; }
            .btn-secondary { background: #95a5a6; color: white; border: none; padding: 10px 20px; 
                            border-radius: 4px; cursor: pointer; margin: 5px; }
            .btn-warning { background: #f39c12; color: white; border: none; padding: 10px 20px; 
                          border-radius: 4px; cursor: pointer; margin: 5px; }
            .button-group { display: flex; gap: 10px; }
            .tile-controls { background: white; border-radius: 8px; padding: 20px; margin: 20px; 
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .control-group { margin-bottom: 20px; }
            .table-container { background: white; border-radius: 8px; padding: 20px; margin: 20px; 
                              box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
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


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialize database
    from ..database import init_database
    init_database()
    
    # Run the app
    app.run_server(debug=True, host='0.0.0.0', port=8050)
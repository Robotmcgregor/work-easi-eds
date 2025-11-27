#!/usr/bin/env python
"""
EDS IN ACTION Dashboard - Working tile visualization
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

    # Configure logging
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
    from src.database.qc_models import QCValidation, QCAuditLog, QCStatus
    from src.config.settings import get_config

    # Initialize Dash app
    app = dash.Dash(__name__, 
                    title="EDS in Action",
                    external_stylesheets=['https://codepen.io/chriddyp/pen/bWLwgP.css'])

    # Layout
    app.layout = html.Div([
        # Header
        html.Div([
            html.H1("🛰️ EDS IN ACTION", 
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': 10}),
            html.P("Early Detection System - Australia Landsat Tiles", 
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
                html.Button("🔍 Queensland", id="zoom-qld", n_clicks=0, 
                           style={'marginRight': '10px', 'backgroundColor': '#3498db', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
                html.Button("🌏 Australia", id="zoom-aus", n_clicks=0,
                           style={'marginRight': '10px', 'backgroundColor': '#27ae60', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
                html.Button("🌍 Wide View", id="zoom-wide", n_clicks=0,
                           style={'backgroundColor': '#e74c3c', 'color': 'white', 'border': 'none', 'padding': '8px 16px', 'borderRadius': '4px'}),
            ], style={'marginTop': '10px'})
        ], style={'marginBottom': 20, 'padding': 15, 'backgroundColor': '#f8f9fa', 'borderRadius': 8, 'border': '1px solid #dee2e6'}),
        
        # Map
        html.Div([
            dcc.Graph(id="eds-map", style={'height': '700px'})
        ]),
        
        # QC Validation Section
        html.Div([
            html.H2("🔍 Quality Control & Validation", style={'color': '#2c3e50', 'marginBottom': 20}),
            
            # QC Summary Cards
            html.Div([
                html.Div([
                    html.Div([
                        html.H3(id="pending-qc-count", children="...", style={'margin': 0, 'color': '#e74c3c'}),
                        html.P("Pending QC Review", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                    ], style={'background': 'white', 'borderRadius': '8px', 'padding': '15px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #e74c3c'}),
                ], className="three columns"),
                
                html.Div([
                    html.Div([
                        html.H3(id="confirmed-qc-count", children="...", style={'margin': 0, 'color': '#27ae60'}),
                        html.P("Confirmed Clearings", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                    ], style={'background': 'white', 'borderRadius': '8px', 'padding': '15px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #27ae60'}),
                ], className="three columns"),
                
                html.Div([
                    html.Div([
                        html.H3(id="rejected-qc-count", children="...", style={'margin': 0, 'color': '#f39c12'}),
                        html.P("Rejected Detections", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                    ], style={'background': 'white', 'borderRadius': '8px', 'padding': '15px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #f39c12'}),
                ], className="three columns"),
                
                html.Div([
                    html.Div([
                        html.H3(id="field-visit-count", children="...", style={'margin': 0, 'color': '#9b59b6'}),
                        html.P("Field Visits Required", style={'margin': '5px 0 0 0', 'color': '#7f8c8d'})
                    ], style={'background': 'white', 'borderRadius': '8px', 'padding': '15px', 'textAlign': 'center', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)', 'margin': '10px', 'borderLeft': '4px solid #9b59b6'}),
                ], className="three columns"),
            ], className="row", style={'marginBottom': 20}),
            
            # QC Review Form
            html.Div([
                html.Div([
                    html.H3("📋 Detection Review Form", style={'color': '#2c3e50', 'marginBottom': 15}),
                    
                    # Detection selection
                    html.Div([
                        html.Label("Select Detection for Review:", style={'fontWeight': 'bold', 'marginBottom': 5}),
                        dcc.Dropdown(
                            id='detection-dropdown',
                            placeholder="Choose a detection to review...",
                            style={'marginBottom': 15}
                        )
                    ]),
                    
                    # Detection details display
                    html.Div(id="detection-details", style={'marginBottom': 20}),
                    
                    # Review form
                    html.Div([
                        html.Div([
                            html.Label("Staff Member:", style={'fontWeight': 'bold'}),
                            dcc.Input(
                                id='reviewer-name',
                                type='text',
                                placeholder='Enter your name...',
                                style={'width': '100%', 'padding': '8px', 'marginBottom': '10px'}
                            )
                        ], className="six columns"),
                        
                        html.Div([
                            html.Label("Validation Decision:", style={'fontWeight': 'bold'}),
                            dcc.RadioItems(
                                id='validation-decision',
                                options=[
                                    {'label': ' ✅ Confirm Clearing', 'value': 'confirmed'},
                                    {'label': ' ❌ Reject Detection', 'value': 'rejected'},
                                    {'label': ' ⚠️ Needs More Review', 'value': 'requires_review'}
                                ],
                                style={'marginBottom': '10px'}
                            )
                        ], className="six columns"),
                    ], className="row"),
                    
                    html.Div([
                        html.Div([
                            html.Label("Confidence (1-5):", style={'fontWeight': 'bold'}),
                            dcc.Slider(
                                id='confidence-slider',
                                min=1, max=5, step=1, value=3,
                                marks={i: str(i) for i in range(1, 6)},
                                tooltip={"placement": "bottom", "always_visible": True}
                            )
                        ], className="six columns"),
                        
                        html.Div([
                            html.Label("Priority Level:", style={'fontWeight': 'bold'}),
                            dcc.Dropdown(
                                id='priority-dropdown',
                                options=[
                                    {'label': 'Low', 'value': 'low'},
                                    {'label': 'Normal', 'value': 'normal'},
                                    {'label': 'High', 'value': 'high'},
                                    {'label': 'Urgent', 'value': 'urgent'}
                                ],
                                value='normal'
                            )
                        ], className="six columns"),
                    ], className="row", style={'marginBottom': 15}),
                    
                    html.Div([
                        html.Label("Comments:", style={'fontWeight': 'bold'}),
                        dcc.Textarea(
                            id='reviewer-comments',
                            placeholder='Enter your comments about this detection...',
                            style={'width': '100%', 'height': 100, 'marginBottom': '10px'}
                        )
                    ]),
                    
                    html.Div([
                        dcc.Checklist(
                            id='field-visit-checkbox',
                            options=[{'label': ' Requires field visit', 'value': 'field_visit'}],
                            style={'marginBottom': '15px'}
                        )
                    ]),
                    
                    html.Div([
                        html.Button("💾 Submit Review", id="submit-review", n_clicks=0,
                                   style={'backgroundColor': '#27ae60', 'color': 'white', 'border': 'none', 'padding': '12px 24px', 'borderRadius': '4px', 'fontSize': '16px', 'marginRight': '10px'}),
                        html.Button("🔄 Clear Form", id="clear-form", n_clicks=0,
                                   style={'backgroundColor': '#95a5a6', 'color': 'white', 'border': 'none', 'padding': '12px 24px', 'borderRadius': '4px', 'fontSize': '16px'}),
                    ]),
                    
                    # Status message
                    html.Div(id="submit-status", style={'marginTop': 15})
                    
                ], className="eight columns"),
                
                # Recent QC Activity
                html.Div([
                    html.H3("📊 Recent QC Activity", style={'color': '#2c3e50', 'marginBottom': 15}),
                    html.Div(id="recent-qc-activity")
                ], className="four columns")
                
            ], className="row")
            
        ], style={'marginTop': 30, 'padding': 20, 'backgroundColor': 'white', 'borderRadius': 8, 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'}),
        
        # Update interval
        dcc.Interval(id='update-interval', interval=30000, n_intervals=0)
    ], style={'fontFamily': 'Arial, sans-serif', 'backgroundColor': '#f8f9fa', 'padding': '20px'})

    # Callbacks
    @app.callback(
        [Output('tiles-count', 'children'),
         Output('processed-count', 'children'),
         Output('detections-count', 'children'),
         Output('cleared-count', 'children'),
         Output('pending-qc-count', 'children'),
         Output('confirmed-qc-count', 'children'),
         Output('rejected-qc-count', 'children'),
         Output('field-visit-count', 'children')],
        [Input('update-interval', 'n_intervals')]
    )
    def update_all_counts(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Original counts
                total_tiles = session.query(LandsatTile).count()
                processed_tiles = session.query(LandsatTile).join(NVMSResult).distinct().count()
                total_detections = session.query(NVMSDetection).count()
                
                cleared_results = session.query(NVMSResult).filter(NVMSResult.cleared.isnot(None)).all()
                cleared_sum = sum(r.cleared or 0 for r in cleared_results)
                
                # QC counts
                pending_qc = session.query(QCValidation).filter(QCValidation.qc_status == QCStatus.PENDING.value).count()
                confirmed_qc = session.query(QCValidation).filter(QCValidation.qc_status == QCStatus.CONFIRMED.value).count()
                rejected_qc = session.query(QCValidation).filter(QCValidation.qc_status == QCStatus.REJECTED.value).count()
                field_visits = session.query(QCValidation).filter(QCValidation.requires_field_visit == True).count()

                return (str(total_tiles), str(processed_tiles), f"{total_detections:,}", str(cleared_sum),
                       str(pending_qc), str(confirmed_qc), str(rejected_qc), str(field_visits))

        except Exception as e:
            return "Error", "Error", "Error", "Error", "Error", "Error", "Error", "Error"

    @app.callback(
        Output('eds-map', 'figure'),
        [Input('map-style-radio', 'value'),
         Input('show-layers-check', 'value'),
         Input('zoom-qld', 'n_clicks'),
         Input('zoom-aus', 'n_clicks'),
         Input('zoom-wide', 'n_clicks'),
         Input('update-interval', 'n_intervals')]
    )
    def update_eds_map(map_style, show_layers, zoom_qld_clicks, zoom_aus_clicks, zoom_wide_clicks, n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            # Determine zoom level and center
            ctx = callback_context
            center_lat, center_lon, zoom = -25, 135, 5
            
            if ctx.triggered:
                button_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if button_id == 'zoom-qld':
                    center_lat, center_lon, zoom = -23, 145, 7
                elif button_id == 'zoom-aus':
                    center_lat, center_lon, zoom = -25, 135, 5
                elif button_id == 'zoom-wide':
                    center_lat, center_lon, zoom = -25, 135, 3

            # Calculate marker size based on zoom level
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
                    print(f"EDS: Loading {len(tiles)} tiles (size: {marker_size}px at zoom {zoom})")
                    
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
                                size=marker_size,
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
                    title=f'🛰️ EDS in Action - {map_style.replace("-", " ").title()}',
                    showlegend=True,
                    margin=dict(r=0, t=40, l=0, b=0)
                )

                return fig

        except Exception as e:
            logger.error(f"EDS Map error: {e}")
            # Return empty map with error
            fig = go.Figure()
            fig.add_annotation(
                text=f"EDS Map Error: {e}",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False
            )
            fig.update_layout(height=700, title="EDS Map Error")
            return fig

    # QC-related callbacks
    @app.callback(
        Output('detection-dropdown', 'options'),
        [Input('update-interval', 'n_intervals')]
    )
    def update_detection_dropdown(n_intervals):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get detections that need QC review (not yet validated)
                detections = session.query(NVMSDetection).outerjoin(QCValidation).filter(
                    QCValidation.id.is_(None)  # No QC record exists
                ).limit(50).all()  # Limit for performance
                
                options = []
                for det in detections:
                    label = f"Detection {det.id} - Tile {det.tile_id}"
                    if det.run_id:
                        label += f" ({det.run_id.replace('NVMS_QLD_', '')})"
                    options.append({'label': label, 'value': det.id})
                
                return options

        except Exception as e:
            return [{'label': f'Error loading detections: {e}', 'value': 'error'}]

    @app.callback(
        Output('detection-details', 'children'),
        [Input('detection-dropdown', 'value')]
    )
    def update_detection_details(detection_id):
        if not detection_id or detection_id == 'error':
            return html.Div("Select a detection to see details.", style={'color': '#7f8c8d'})
        
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                detection = session.query(NVMSDetection).filter(NVMSDetection.id == detection_id).first()
                
                if not detection:
                    return html.Div("Detection not found.", style={'color': '#e74c3c'})
                
                return html.Div([
                    html.H4(f"Detection #{detection.id}", style={'color': '#2c3e50', 'marginBottom': 10}),
                    html.P([
                        html.Strong("Tile ID: "), detection.tile_id, html.Br(),
                        html.Strong("Run: "), detection.run_id.replace('NVMS_QLD_', '') if detection.run_id else 'Unknown', html.Br(),
                        html.Strong("Properties: "), str(detection.properties) if detection.properties else 'No additional data', html.Br(),
                        html.Strong("Imported: "), detection.imported_at.strftime('%Y-%m-%d %H:%M') if detection.imported_at else 'Unknown', html.Br(),
                        html.Strong("Geometry: "), "Available" if detection.geom_geojson else "No geometry data"
                    ], style={'backgroundColor': '#f8f9fa', 'padding': 15, 'borderRadius': 5})
                ])

        except Exception as e:
            return html.Div(f"Error loading detection details: {e}", style={'color': '#e74c3c'})

    @app.callback(
        [Output('submit-status', 'children'),
         Output('reviewer-name', 'value'),
         Output('validation-decision', 'value'),
         Output('confidence-slider', 'value'),
         Output('priority-dropdown', 'value'),
         Output('reviewer-comments', 'value'),
         Output('field-visit-checkbox', 'value')],
        [Input('submit-review', 'n_clicks'),
         Input('clear-form', 'n_clicks')],
        [State('detection-dropdown', 'value'),
         State('reviewer-name', 'value'),
         State('validation-decision', 'value'),
         State('confidence-slider', 'value'),
         State('priority-dropdown', 'value'),
         State('reviewer-comments', 'value'),
         State('field-visit-checkbox', 'value')]
    )
    def handle_form_submission(submit_clicks, clear_clicks, detection_id, reviewer_name, 
                              validation_decision, confidence, priority, comments, field_visit):
        ctx = callback_context
        if not ctx.triggered:
            return "", "", None, 3, 'normal', "", []
        
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        # Clear form
        if button_id == 'clear-form':
            return "", "", None, 3, 'normal', "", []
        
        # Submit review
        if button_id == 'submit-review' and submit_clicks > 0:
            if not detection_id or not reviewer_name or not validation_decision:
                return html.Div("Please fill in all required fields.", 
                               style={'color': '#e74c3c', 'fontWeight': 'bold'}), reviewer_name, validation_decision, confidence, priority, comments, field_visit
            
            try:
                config = get_config()
                db = DatabaseManager(config.database.connection_url)

                with db.get_session() as session:
                    # Get the detection
                    detection = session.query(NVMSDetection).filter(NVMSDetection.id == detection_id).first()
                    if not detection:
                        return html.Div("Detection not found.", style={'color': '#e74c3c'}), reviewer_name, validation_decision, confidence, priority, comments, field_visit
                    
                    # Create QC validation record
                    qc_validation = QCValidation(
                        nvms_detection_id=detection_id,
                        tile_id=detection.tile_id,
                        qc_status=validation_decision,
                        reviewed_by=reviewer_name,
                        reviewed_at=datetime.now(),
                        is_confirmed_clearing=(validation_decision == 'confirmed'),
                        confidence_score=confidence,
                        reviewer_comments=comments,
                        requires_field_visit=('field_visit' in field_visit if field_visit else False),
                        priority_level=priority
                    )
                    
                    session.add(qc_validation)
                    session.commit()
                    
                    # Create audit log entry
                    audit_log = QCAuditLog(
                        qc_validation_id=qc_validation.id,
                        action='created',
                        new_value=f'QC review completed: {validation_decision}',
                        changed_by=reviewer_name,
                        change_reason='Initial QC review submission'
                    )
                    session.add(audit_log)
                    session.commit()
                    
                    success_msg = html.Div([
                        html.Strong("✅ Review submitted successfully!"),
                        html.Br(),
                        f"Detection {detection_id} marked as {validation_decision} by {reviewer_name}"
                    ], style={'color': '#27ae60', 'fontWeight': 'bold', 'backgroundColor': '#d4edda', 'padding': 10, 'borderRadius': 5})
                    
                    # Clear form after successful submission
                    return success_msg, "", None, 3, 'normal', "", []

            except Exception as e:
                error_msg = html.Div(f"Error submitting review: {e}", 
                                   style={'color': '#e74c3c', 'fontWeight': 'bold'})
                return error_msg, reviewer_name, validation_decision, confidence, priority, comments, field_visit
        
        return "", reviewer_name, validation_decision, confidence, priority, comments, field_visit

    @app.callback(
        Output('recent-qc-activity', 'children'),
        [Input('update-interval', 'n_intervals'),
         Input('submit-review', 'n_clicks')]
    )
    def update_recent_qc_activity(n_intervals, submit_clicks):
        try:
            config = get_config()
            db = DatabaseManager(config.database.connection_url)

            with db.get_session() as session:
                # Get recent QC validations
                recent_qc = session.query(QCValidation).order_by(
                    QCValidation.reviewed_at.desc()
                ).limit(10).all()
                
                if not recent_qc:
                    return html.Div("No recent QC activity.", style={'color': '#7f8c8d'})
                
                activity_items = []
                for qc in recent_qc:
                    if qc.reviewed_at:
                        status_color = {
                            'confirmed': '#27ae60',
                            'rejected': '#e74c3c',
                            'requires_review': '#f39c12',
                            'pending': '#95a5a6'
                        }.get(qc.qc_status, '#95a5a6')
                        
                        activity_items.append(
                            html.Div([
                                html.Strong(f"Detection {qc.nvms_detection_id}"),
                                html.Br(),
                                html.Span(qc.qc_status.title(), style={'color': status_color}),
                                html.Br(),
                                html.Small(f"By {qc.reviewed_by} on {qc.reviewed_at.strftime('%Y-%m-%d %H:%M')}")
                            ], style={'padding': 8, 'marginBottom': 8, 'backgroundColor': '#f8f9fa', 'borderRadius': 4, 'borderLeft': f'3px solid {status_color}'})
                        )
                
                return activity_items

        except Exception as e:
            return html.Div(f"Error loading activity: {e}", style={'color': '#e74c3c'})

    # Run the app
    print("🚀 STARTING EDS IN ACTION")
    print("=" * 60)
    print(f"🌐 Local: http://localhost:8057")
    print(f"📍 Network: http://10.0.0.14:8057")
    print("")
    print("🎯 EDS IN ACTION FEATURES:")
    print("✅ ZOOM-RESPONSIVE tile markers (8-25px)")
    print("✅ Reliable radio button controls")
    print("✅ All 466 Australia tiles visible")
    print("✅ 3-level zoom system")
    print("✅ Fixed callback inputs")
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
    
    app.run_server(debug=False, host='0.0.0.0', port=8057)
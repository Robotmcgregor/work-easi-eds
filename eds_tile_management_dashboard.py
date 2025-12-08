#!/usr/bin/env python
"""
EDS Tile Management Dashboard

A dashboard for managing EDS processing workflow:
- View tile status and assignments
- Assign tiles to staff members
- Execute EDS data preparation scripts
- Track processing progress and results
- Manage user tasks and priorities
"""

import sys
from pathlib import Path
import json
import subprocess
import threading
import time
from datetime import datetime, timedelta

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

if __name__ == "__main__":
    import dash
    from dash import dcc, html, Input, Output, State, callback, dash_table
    import plotly.express as px
    import plotly.graph_objects as go
    import pandas as pd
    import logging
    from dash.exceptions import PreventUpdate

    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Import our modules
    from src.database.connection import DatabaseManager
    from src.database.models import LandsatTile
    from src.config.settings import get_config

    # Global variables for tracking running processes
    active_processes = {}
    process_logs = {}

    # Initialize database
    config = get_config()
    db_manager = DatabaseManager()

    def get_all_tiles():
        """Get all tiles with their current status."""
        with db_manager.get_session() as session:
            tiles = session.query(LandsatTile).all()

            tile_data = []
            for tile in tiles:
                tile_info = {
                    "tile_id": tile.tile_id,
                    "path": tile.path,
                    "row": tile.row,
                    "status": tile.status or "unassigned",
                    "assigned_to": getattr(tile, "assigned_to", None),
                    "priority": tile.processing_priority or 0,
                    "last_processed": tile.last_processed,
                    "processing_notes": tile.processing_notes or "",
                    "data_quality_score": tile.data_quality_score,
                    "is_active": tile.is_active,
                }
                tile_data.append(tile_info)

            return pd.DataFrame(tile_data)

    def update_tile_status(tile_id, status, assigned_to=None, notes=None):
        """Update tile status and assignment."""
        with db_manager.get_session() as session:
            tile = (
                session.query(LandsatTile)
                .filter(LandsatTile.tile_id == tile_id)
                .first()
            )
            if tile:
                tile.status = status
                if assigned_to:
                    # Add assigned_to field if it doesn't exist
                    if not hasattr(tile, "assigned_to"):
                        # You might need to add this column to your database schema
                        pass
                    else:
                        tile.assigned_to = assigned_to
                if notes:
                    tile.processing_notes = notes
                tile.last_updated = datetime.now()
                session.commit()
                return True
        return False

    def run_eds_script(script_name, tile_id, start_date, end_date, **kwargs):
        """Run an EDS script in the background."""
        process_id = f"{script_name}_{tile_id}_{int(time.time())}"

        # Build command
        if script_name == "data_pipeline":
            cmd = [
                sys.executable,
                "scripts/eds_master_data_pipeline.py",
                "--tile",
                tile_id,
                "--start-date",
                start_date,
                "--end-date",
                end_date,
            ]
        elif script_name == "eds_processing":
            cmd = [sys.executable, "scripts/run_eds.py", "--tile", tile_id]
        else:
            return None, "Unknown script"

        # Add additional kwargs
        for key, value in kwargs.items():
            if value:
                cmd.extend([f"--{key}", str(value)])

        try:
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            active_processes[process_id] = {
                "process": process,
                "tile_id": tile_id,
                "script": script_name,
                "start_time": datetime.now(),
                "status": "running",
            }

            process_logs[process_id] = []

            def monitor_process():
                """Monitor process output."""
                try:
                    while True:
                        line = process.stdout.readline()
                        if not line and process.poll() is not None:
                            break
                        if line:
                            process_logs[process_id].append(
                                {
                                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                                    "message": line.strip(),
                                }
                            )

                    # Process finished
                    return_code = process.poll()
                    active_processes[process_id]["status"] = (
                        "completed" if return_code == 0 else "failed"
                    )
                    active_processes[process_id]["end_time"] = datetime.now()

                    # Update tile status
                    if return_code == 0:
                        update_tile_status(
                            tile_id,
                            "completed",
                            notes=f"Completed {script_name} at {datetime.now()}",
                        )
                    else:
                        update_tile_status(
                            tile_id,
                            "failed",
                            notes=f"Failed {script_name} at {datetime.now()}",
                        )

                except Exception as e:
                    logger.error(f"Error monitoring process {process_id}: {e}")
                    active_processes[process_id]["status"] = "error"

            # Start monitoring thread
            threading.Thread(target=monitor_process, daemon=True).start()

            return process_id, "Process started successfully"

        except Exception as e:
            logger.error(f"Error starting process: {e}")
            return None, str(e)

    # Create Dash app
    app = dash.Dash(__name__)
    app.title = "EDS Tile Management"

    app.layout = html.Div(
        [
            # Header
            html.Div(
                [
                    html.H1(
                        "🗺️ EDS Tile Management Dashboard",
                        style={"textAlign": "center", "color": "#2c3e50"},
                    ),
                    html.P(
                        "Manage EDS processing workflow, assign tiles to staff, and execute scripts",
                        style={"textAlign": "center", "color": "#7f8c8d"},
                    ),
                ],
                style={"padding": "20px", "backgroundColor": "#ecf0f1"},
            ),
            # Control Panel
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("📋 Tile Management"),
                            dcc.Dropdown(
                                id="staff-dropdown",
                                options=[
                                    {"label": "Alice Johnson", "value": "alice"},
                                    {"label": "Bob Smith", "value": "bob"},
                                    {"label": "Carol Davis", "value": "carol"},
                                    {"label": "David Wilson", "value": "david"},
                                    {"label": "Unassigned", "value": "unassigned"},
                                ],
                                placeholder="Select staff member",
                                style={"marginBottom": "10px"},
                            ),
                            dcc.Dropdown(
                                id="status-dropdown",
                                options=[
                                    {"label": "🔴 Not Started", "value": "not_started"},
                                    {"label": "📥 Data Prep", "value": "data_prep"},
                                    {"label": "⚙️ Processing", "value": "processing"},
                                    {"label": "🔍 Review", "value": "review"},
                                    {"label": "✅ Completed", "value": "completed"},
                                    {"label": "❌ Failed", "value": "failed"},
                                ],
                                placeholder="Select status",
                                style={"marginBottom": "10px"},
                            ),
                            html.Button(
                                "Update Selected Tiles",
                                id="update-tiles-btn",
                                className="btn btn-primary",
                                style={"marginBottom": "10px"},
                            ),
                        ],
                        style={
                            "width": "30%",
                            "display": "inline-block",
                            "verticalAlign": "top",
                            "padding": "20px",
                        },
                    ),
                    html.Div(
                        [
                            html.H3("🚀 Script Execution"),
                            dcc.Input(
                                id="tile-input",
                                type="text",
                                placeholder="Tile ID (e.g., 089_078)",
                                style={"width": "100%", "marginBottom": "10px"},
                            ),
                            dcc.Input(
                                id="start-date-input",
                                type="text",
                                placeholder="Start Date (YYYYMMDD)",
                                style={
                                    "width": "48%",
                                    "display": "inline-block",
                                    "marginRight": "2%",
                                },
                            ),
                            dcc.Input(
                                id="end-date-input",
                                type="text",
                                placeholder="End Date (YYYYMMDD)",
                                style={
                                    "width": "48%",
                                    "display": "inline-block",
                                    "marginLeft": "2%",
                                },
                            ),
                            html.Br(),
                            dcc.Dropdown(
                                id="script-dropdown",
                                options=[
                                    {
                                        "label": "📦 Data Pipeline",
                                        "value": "data_pipeline",
                                    },
                                    {
                                        "label": "⚙️ EDS Processing",
                                        "value": "eds_processing",
                                    },
                                ],
                                placeholder="Select script to run",
                                style={"marginTop": "10px", "marginBottom": "10px"},
                            ),
                            html.Button(
                                "🚀 Run Script",
                                id="run-script-btn",
                                className="btn btn-success",
                            ),
                        ],
                        style={
                            "width": "30%",
                            "display": "inline-block",
                            "verticalAlign": "top",
                            "padding": "20px",
                        },
                    ),
                    html.Div(
                        [html.H3("📊 Quick Stats"), html.Div(id="stats-panel")],
                        style={
                            "width": "30%",
                            "display": "inline-block",
                            "verticalAlign": "top",
                            "padding": "20px",
                        },
                    ),
                ],
                style={"backgroundColor": "#f8f9fa", "margin": "10px"},
            ),
            # Main content tabs
            dcc.Tabs(
                id="main-tabs",
                value="tiles-tab",
                children=[
                    dcc.Tab(label="🗺️ Tiles Overview", value="tiles-tab"),
                    dcc.Tab(label="🏃 Active Processes", value="processes-tab"),
                    dcc.Tab(label="📈 Analytics", value="analytics-tab"),
                ],
            ),
            # Tab content
            html.Div(id="tab-content"),
            # Status messages
            html.Div(
                id="status-message", style={"padding": "10px", "textAlign": "center"}
            ),
            # Auto-refresh interval
            dcc.Interval(
                id="interval-component",
                interval=5 * 1000,  # Update every 5 seconds
                n_intervals=0,
            ),
            # Hidden div to store selected tiles
            html.Div(id="selected-tiles", style={"display": "none"}),
        ]
    )

    @app.callback(
        Output("tab-content", "children"),
        Input("main-tabs", "value"),
        Input("interval-component", "n_intervals"),
    )
    def update_tab_content(active_tab, n):
        if active_tab == "tiles-tab":
            return render_tiles_tab()
        elif active_tab == "processes-tab":
            return render_processes_tab()
        elif active_tab == "analytics-tab":
            return render_analytics_tab()
        return html.Div("Select a tab")

    def render_tiles_tab():
        """Render the tiles overview tab."""
        df = get_all_tiles()

        return html.Div(
            [
                html.H3("Tile Status Overview"),
                dash_table.DataTable(
                    id="tiles-table",
                    columns=[
                        {"name": "Tile ID", "id": "tile_id"},
                        {"name": "Path", "id": "path"},
                        {"name": "Row", "id": "row"},
                        {"name": "Status", "id": "status"},
                        {"name": "Assigned To", "id": "assigned_to"},
                        {"name": "Priority", "id": "priority"},
                        {"name": "Last Processed", "id": "last_processed"},
                        {"name": "Notes", "id": "processing_notes"},
                    ],
                    data=df.to_dict("records"),
                    row_selectable="multi",
                    style_cell={"textAlign": "left"},
                    style_data_conditional=[
                        {
                            "if": {"filter_query": "{status} = completed"},
                            "backgroundColor": "#d4edda",
                            "color": "black",
                        },
                        {
                            "if": {"filter_query": "{status} = failed"},
                            "backgroundColor": "#f8d7da",
                            "color": "black",
                        },
                        {
                            "if": {"filter_query": "{status} = processing"},
                            "backgroundColor": "#fff3cd",
                            "color": "black",
                        },
                    ],
                    page_size=20,
                ),
            ]
        )

    def render_processes_tab():
        """Render the active processes tab."""
        process_data = []
        for pid, info in active_processes.items():
            process_data.append(
                {
                    "process_id": pid,
                    "tile_id": info["tile_id"],
                    "script": info["script"],
                    "status": info["status"],
                    "start_time": info["start_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "duration": str(datetime.now() - info["start_time"]).split(".")[0],
                }
            )

        process_df = pd.DataFrame(process_data) if process_data else pd.DataFrame()

        return html.Div(
            [
                html.H3("Active Processes"),
                dash_table.DataTable(
                    id="processes-table",
                    columns=[
                        {"name": "Process ID", "id": "process_id"},
                        {"name": "Tile", "id": "tile_id"},
                        {"name": "Script", "id": "script"},
                        {"name": "Status", "id": "status"},
                        {"name": "Start Time", "id": "start_time"},
                        {"name": "Duration", "id": "duration"},
                    ],
                    data=process_df.to_dict("records") if not process_df.empty else [],
                    style_cell={"textAlign": "left"},
                    page_size=10,
                ),
                html.Div(
                    [html.H4("Process Logs"), html.Div(id="process-logs")],
                    style={"marginTop": "20px"},
                ),
            ]
        )

    def render_analytics_tab():
        """Render the analytics tab."""
        df = get_all_tiles()

        # Status distribution
        status_counts = df["status"].value_counts()
        status_fig = px.pie(
            values=status_counts.values,
            names=status_counts.index,
            title="Tile Status Distribution",
        )

        # Assignment distribution
        if "assigned_to" in df.columns:
            assigned_counts = df["assigned_to"].value_counts()
            assigned_fig = px.bar(
                x=assigned_counts.index,
                y=assigned_counts.values,
                title="Tiles by Staff Assignment",
            )
        else:
            assigned_fig = px.bar(title="No assignment data available")

        return html.Div(
            [
                html.Div(
                    [dcc.Graph(figure=status_fig)],
                    style={"width": "50%", "display": "inline-block"},
                ),
                html.Div(
                    [dcc.Graph(figure=assigned_fig)],
                    style={"width": "50%", "display": "inline-block"},
                ),
            ]
        )

    @app.callback(
        Output("stats-panel", "children"), Input("interval-component", "n_intervals")
    )
    def update_stats_panel(n):
        """Update the statistics panel."""
        df = get_all_tiles()

        total_tiles = len(df)
        completed = (
            len(df[df["status"] == "completed"]) if "status" in df.columns else 0
        )
        in_progress = (
            len(df[df["status"].isin(["processing", "data_prep"])])
            if "status" in df.columns
            else 0
        )
        failed = len(df[df["status"] == "failed"]) if "status" in df.columns else 0

        return html.Div(
            [
                html.P(f"📊 Total Tiles: {total_tiles}"),
                html.P(f"✅ Completed: {completed}"),
                html.P(f"⚙️ In Progress: {in_progress}"),
                html.P(f"❌ Failed: {failed}"),
                html.P(f"🏃 Active Processes: {len(active_processes)}"),
            ]
        )

    @app.callback(
        Output("selected-tiles", "children"),
        Input("tiles-table", "selected_rows"),
        State("tiles-table", "data"),
    )
    def store_selected_tiles(selected_rows, table_data):
        """Store selected tile IDs."""
        if selected_rows and table_data:
            selected_tile_ids = [table_data[i]["tile_id"] for i in selected_rows]
            return json.dumps(selected_tile_ids)
        return json.dumps([])

    @app.callback(
        Output("status-message", "children"),
        [Input("update-tiles-btn", "n_clicks"), Input("run-script-btn", "n_clicks")],
        [
            State("selected-tiles", "children"),
            State("staff-dropdown", "value"),
            State("status-dropdown", "value"),
            State("tile-input", "value"),
            State("start-date-input", "value"),
            State("end-date-input", "value"),
            State("script-dropdown", "value"),
        ],
    )
    def handle_actions(
        update_clicks,
        run_clicks,
        selected_tiles_json,
        staff_member,
        new_status,
        tile_id,
        start_date,
        end_date,
        script,
    ):
        """Handle button clicks for updating tiles and running scripts."""
        ctx = dash.callback_context
        if not ctx.triggered:
            raise PreventUpdate

        button_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if button_id == "update-tiles-btn" and update_clicks:
            if not selected_tiles_json:
                return html.Div("⚠️ No tiles selected", style={"color": "orange"})

            selected_tiles = json.loads(selected_tiles_json)
            if not staff_member or not new_status:
                return html.Div(
                    "⚠️ Please select staff member and status", style={"color": "orange"}
                )

            updated_count = 0
            for tile_id in selected_tiles:
                if update_tile_status(tile_id, new_status, staff_member):
                    updated_count += 1

            return html.Div(
                f"✅ Updated {updated_count} tiles", style={"color": "green"}
            )

        elif button_id == "run-script-btn" and run_clicks:
            if not tile_id or not start_date or not end_date or not script:
                return html.Div(
                    "⚠️ Please fill all script parameters", style={"color": "orange"}
                )

            process_id, message = run_eds_script(script, tile_id, start_date, end_date)

            if process_id:
                update_tile_status(
                    tile_id, "processing", notes=f"Started {script} at {datetime.now()}"
                )
                return html.Div(
                    f"🚀 {message} (ID: {process_id})", style={"color": "green"}
                )
            else:
                return html.Div(f"❌ {message}", style={"color": "red"})

        raise PreventUpdate

    @app.callback(
        Output("process-logs", "children"), Input("interval-component", "n_intervals")
    )
    def update_process_logs(n):
        """Update process logs display."""
        if not process_logs:
            return html.P("No active processes")

        log_components = []
        for pid, logs in process_logs.items():
            if logs:  # Only show if there are logs
                recent_logs = logs[-10:]  # Show last 10 log entries
                log_text = "\n".join(
                    [f"[{log['timestamp']}] {log['message']}" for log in recent_logs]
                )

                log_components.append(
                    html.Div(
                        [
                            html.H5(f"Process: {pid}"),
                            html.Pre(
                                log_text,
                                style={
                                    "backgroundColor": "#f8f9fa",
                                    "padding": "10px",
                                    "border": "1px solid #dee2e6",
                                    "maxHeight": "200px",
                                    "overflowY": "scroll",
                                },
                            ),
                        ]
                    )
                )

        return log_components if log_components else html.P("No process logs available")

    # Run the app
    if __name__ == "__main__":
        app.run_server(debug=True, host="127.0.0.1", port=8060)

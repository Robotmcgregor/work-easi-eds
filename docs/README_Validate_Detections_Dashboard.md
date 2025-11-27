# EDS - Validate Detections Dashboard

A focused Dash app for reviewing land-clearing detections, built on the working tiles + detections baseline and extended with a QC workflow.

File: `new_dashboard_with_qc.py`
Port: 8055 (default)

## What it does

- **Filtering**: Only displays detections where `IsClearing == 'y'` (probabilistically identified clearing events)
- Map with layers
  - NVMS run tiles outlined and color-coded by run (Run 1/2/3...). Hover shows PathRow (e.g., 090084).
  - Clearing detections plotted as points, colored by QC status:
    - Green = Confirmed
    - Red = Rejected
    - Yellow = Requires review
    - Blue = No QC yet
- QC panel
  - Dropdown of detections to review (excludes those already Confirmed/Rejected)
  - Reviewer, Decision (Confirm/Reject/Requires review), Confidence (1–5), Comments
  - Polygon preview for the selected detection (handles GeoJSON dict/string; Polygon/MultiPolygon; centroid fallback)
  - Submit saves a QCValidation row, clears the selection, refreshes dropdown, map, metrics, and charts
- Summary widgets (top row)
  - Total Tiles
  - Latest Run (Run N): count of tiles in the most recent NVMS run
  - Total Detections
  - Confirmed Clearing: unique detections with QC status = confirmed
- Charts
  - Tiles Processed per Run (from NVMSResult)
  - Detections over Time (last 90 days; DB aggregation with Python fallback)
- Build banner
  - Shows a build timestamp and port to confirm you’re on the latest instance

## Prerequisites

- **Conda Environment**: Use the `slats` conda environment (see `slats.yml` or create manually)
- **Python**: 3.11+ (tested with slats environment)
- **Dependencies**: All required packages installed in slats environment:
  - `dash`, `plotly`, `geopandas`, `sqlalchemy`, `psycopg2`, `geoalchemy2`, `schedule`, etc.
- **Database**: Configured via `.env` (see `.env.example`)
  - The app reads connection via `src.config.settings.get_config()`
- **Data Tables**: NVMS and QC tables populated:
  - `NVMSRun`, `NVMSResult`, `NVMSDetection` (import via `import_nvms_shapefiles.py`)
  - `QCValidation` (create via `create_qc_tables.py` if needed)
- **Detection Data**: Only detections with `properties->>'IsClearing' = 'y'` are displayed

## Run

**Option 1: Using conda run (recommended)**
```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -n slats python new_dashboard_with_qc.py
```

**Option 2: Direct interpreter**
```powershell
C:\ProgramData\anaconda3\envs\slats\python.exe new_dashboard_with_qc.py
```

**Option 3: Activate environment first**
```powershell
conda activate slats
python new_dashboard_with_qc.py
```

- App binds to `http://localhost:8055` by default
- Press Ctrl+C in the terminal to stop

## Configuration

- Port: change at the bottom of `new_dashboard_with_qc.py` (app.run_server(..., port=8055))
- Map styles: choose Street, Satellite, or Terrain via the radio control
- Detection limit: currently loads up to ~2000 latest detections for color-coding
- Tile outlines: caps each run at ~120 tiles per run for performance

## Data model fields used

- `LandsatTile`: tile_id, path, row, center_lat, center_lon, bounds_geojson, last_processed
- `NVMSRun`: run_id, run_number, created_at
- `NVMSResult`: run_id, tile_id
- `NVMSDetection`: id, tile_id, geom_geojson (JSONB dict or JSON string), properties (JSONB with IsClearing field), imported_at
- `QCValidation`: nvms_detection_id, tile_id, qc_status, reviewed_by, reviewed_at, reviewer_comments, confidence_score, is_confirmed_clearing

**Important**: Only detections where `properties->>'IsClearing' = 'y'` are loaded and displayed in the dashboard.

## QC workflow

1. Pick a detection from the dropdown (unreviewed only)
2. Inspect polygon preview and details
3. Enter reviewer, select decision and confidence, optionally add comments
4. Submit
   - The selection clears; the reviewed detection disappears from dropdown
   - The map recolors the detection by new status
   - Metrics and charts refresh immediately

Note: By default, detections with `requires_review` remain in the dropdown. If you want to also exclude those, we can add that filter.

## Troubleshooting

- I don’t see changes after code updates
  - Hard refresh the browser (Ctrl+F5) to reload the Dash callback map
  - Close other tabs of the app; keep a single tab open
- Port already in use
  - Another server may be running on 8055. Stop the other instance or change the port in `new_dashboard_with_qc.py`
- Dropdown doesn’t update after submit
  - Ensure you’re on the latest build (check the build timestamp under the header)
  - Try Ctrl+F5 to refresh the callback map
- Map shows blue-only detections
  - The map colors detections by their latest `QCValidation` status; ensure QC rows exist
- Polygon preview error
  - The app handles dict or string GeoJSON, Polygon/MultiPolygon, and has a centroid fallback; if geometry is malformed, it’ll show an error in the preview panel

## Notes & conventions

- **Clearing Filter**: Dashboard automatically filters to only show detections where `IsClearing == 'y'`
- **Environment**: Uses the `slats` conda environment with all required geospatial dependencies
- Hover for tile outlines shows `PathRow: PPPRRR` using `path`+`row` from `LandsatTile`
- The app assumes `NVMSDetection.geom_geojson` often arrives as JSONB/dict from Postgres drivers
- "Latest Run" is picked by highest `run_number`, then by newest `created_at`
- Detection properties are stored in JSONB format with IsClearing, Area_ha, Notes, etc.

## Environment Setup

If you don't have the slats environment yet:

```powershell
# Create from slats.yml (if available)
conda env create -f slats.yml

# Or create manually and install key packages
conda create -n slats python=3.11
conda activate slats
conda install -c conda-forge geopandas rasterio gdal
pip install dash plotly sqlalchemy psycopg2-binary geoalchemy2 schedule python-dotenv
```

## Change log (high level)

- v1.1 (2025-11-12)
  - **Added IsClearing filter**: Only displays detections where `IsClearing == 'y'`
  - **Updated for slats environment**: Uses conda environment with all geo dependencies
  - **Improved filtering**: All queries now filtered to clearing detections only
- v1 (2025-11-03)
  - Initial release of "EDS - Validate Detections Dashboard"
  - Added QC form and submission flow
  - Color-coded detections by QC status
  - Latest run tiles count + label
  - Detections over Time (90d) chart
  - Build banner for easy verification

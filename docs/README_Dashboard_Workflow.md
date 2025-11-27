# Dashboard Workflow

Quickstart to explore detections and related datasets via the dashboard scripts in this repo.

Tested on Windows PowerShell with a conda env containing the required packages.

## 0. Environment

- Activate the unified `slats` conda environment and ensure all dashboard/DB/processing packages are installed.
- Run commands from the repo root: `C:\Users\DCCEEW\code\eds`.
- If starting fresh, install dependencies (PostgreSQL client libs, GDAL, etc.) then:

```powershell
# (Optional) Create env if not present
conda create -y -p C:\Users\DCCEEW\mmroot\envs\slats python=3.11

# Activate (PowerShell)
conda activate C:\Users\DCCEEW\mmroot\envs\slats

# Core DB + dashboard + geospatial dependencies
python -m pip install -r requirements.txt

# If psycopg2 build fails on Windows, use conda-forge:
conda install -y -c conda-forge psycopg2

# Verify critical modules
python -c "import sqlalchemy, psycopg2, dash, pandas, shapely; print('OK')"
```

Place database connection settings in a `.env` file (see `.env.example`).

## 1. Prepare data (optional)

If you followed the EDS workflow, relevant outputs live under `data/compat/files/<scene>/` and can be pointed to by the dashboard.

## 2. Start the dashboard

There are different dashboards for different purposes:

### Detection Validation Dashboard
```powershell
# Main validation dashboard with QC workflow (IsClearing filtering)
python new_dashboard_with_qc.py
```

### EDS Tile Management Dashboard  
```powershell
# New management dashboard for staff assignment and script execution
python eds_tile_management_dashboard.py
```

### General Purpose Dashboard
```powershell
# General-purpose starter dashboard
python start_dashboard.py
```

### Enhanced Visualization Dashboard
```powershell  
# Enhanced dashboard with tile boundaries and NVMS visualization
python enhanced_dashboard.py
```

If the dashboard expects a database connection, see `SETUP_GUIDE.md` and `setup_database.py` for initialization, and `create_eds_user.py` to provision users.

## 3. Troubleshooting

- If maps don’t render or layers are missing, ensure file paths within the dashboard config/scripts point to your generated rasters and shapefiles (e.g., under `data/compat/files/<scene>/`).
- Use the helper scripts:
  - `inspect_db.py` for DB checks
  - `verify_dashboard_data.py` to validate data presence

## 4. Notes

- Large shapefiles (millions of features) will be heavy in the browser—prefer the cleaned, dissolved, and clipped versions (strict / r095 / r070) to reduce load.
- For web map performance, consider simplifying geometries offline and serving as vector tiles.
- Use `inspect_db.py` after environment setup to confirm tables (requires `python-dotenv`, `sqlalchemy`, `psycopg2`).

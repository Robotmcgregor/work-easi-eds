# Django Admin Quick Start

## 🚀 Start the Server
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\run.bat runserver
```

Done! No conda needed. The `run.bat` script uses Python's built-in venv.

## 🔐 Login
- **URL:** http://127.0.0.1:8000/admin/
- **Username:** `admin`
- **Password:** `admin123`

## 📊 What You Can Do

### Browse Data
- **Landsat Tiles** (466 records) - Australian Sentinel-2 tile grid
- **EDS Runs** (3 runs) - Processing runs with descriptions
- **EDS Results** (483 records) - Per-tile processing results
- **Detections** (14,735 records) - Individual detections with geometry
- **Detection Alerts** (0) - Verification tracking
- **QC Validations** (10) - Quality control records
- **QC Audit Log** (0) - Audit trail of all changes

### Search & Filter
- Click "Search" box to find records
- Use "Filters" on the right to narrow results
- View related records via ForeignKey links

### Edit Records
- Click any record to view/edit details
- Change values and click "Save"
- Changes are logged in admin history

### Inspect Relationships
- Click ForeignKey links to jump to related records
- See all detection for a run, or all validations for a detection
- One-click navigation between related data

## 📋 Key Tables

| Table | Records | Purpose |
|-------|---------|---------|
| landsat_tiles | 466 | Tile definitions |
| eds_runs | 3 | Processing runs |
| eds_results | 483 | Per-tile results |
| eds_detections | 14,735 | Individual detections |
| qc_validations | 10 | QC records |

## 🛠️ Common Tasks

### View all tiles
1. Click "Landsat Tiles"
2. See all 466 tiles with status/quality

### Check a specific run's results
1. Click "EDS Runs"
2. Click on a run number
3. See detections_total and cleared_tiles counts

### Find detections in a tile
1. Click "EDS Detections"
2. Use Filters → Tile ID to narrow results
3. Browse the 14,735 detections

### Review QC validations
1. Click "QC Validations"
2. See status (pending, confirmed, rejected)
3. Filter by confidence score or reviewer
4. See audit history in QC Audit Log

## ⚙️ System Info

- **Database:** SQLite at `../data/eds_database.db`
- **Records:** 16,182 total
- **Size:** 114.6 MB
- **All models:** read-only (managed=False in Django)

## 📞 Need Help?

See `ADMIN_INTERFACE_READY.md` for full documentation.


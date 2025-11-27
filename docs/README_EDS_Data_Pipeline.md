# EDS Data Preparation Pipeline

This pipeline downloads and prepares all required satellite data for EDS (Environmental Detection System) processing from multiple sources (S3 and GA DEA) with automated masking.

## Overview

The EDS processing requires:
- **SR (Surface Reflectance) composites (LS8/LS9 only)** for start and end dates
- **FC (Fractional Cover) seasonal data (LS8/LS9 provenance only)** spanning 10 years for July-October periods  
- **Clear masks applied** to all FC data (fmask value = 1)
- **Proper file naming** and folder structure for EDS compatibility

## Quick Start

### Single Command Execution
```bash
# Download all required data for a tile
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831

# With custom parameters
python scripts/eds_master_data_pipeline.py \
  --tile 089_078 \
  --start-date 20230720 \
  --end-date 20240831 \
  --dest "D:\data\lsat" \
  --span-years 10 \
  --cloud-cover 40 \
  --search-days 7
```

## Scripts Overview

### Master Script
- **`eds_master_data_pipeline.py`** - Single entry point that orchestrates the entire data acquisition workflow

### Individual Components
1. **`download_fc_from_s3.py`** - Fast download from S3 (limited availability)
2. **`download_seasonal_fc_from_ga.py`** - Comprehensive FC download from GA DEA (10 years seasonal)
3. **`ensure_sr_dates_for_eds.py`** - SR start/end date acquisition with fallback to GA
4. **`derive_fc_clr.py`** - Apply clear masks to FC data (fmask == 1)

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--tile` | Required | Landsat WRS2 tile in format `089_078` |
| `--start-date` | Required | Start date in YYYYMMDD format (e.g., `20230720`) |
| `--end-date` | Required | End date in YYYYMMDD format (e.g., `20240831`) |
| `--dest` | `D:\data\lsat` | Destination directory for downloaded data |
| `--span-years` | `10` | Number of years of seasonal FC data to download |
| `--cloud-cover` | `50` | Maximum cloud cover percentage to accept |
| `--search-days` | `7` | Days to search around target dates for SR composites |

## Data Sources Priority

### 1. S3 First (Fast)
- Checks S3 bucket for existing processed data
- Validates each FC file's provenance via DEA STAC and only downloads if produced from Landsat 8 or 9 (L5/L7 are skipped)
- Downloads if available and valid (much faster than GA processing)

### 2. GA DEA Fallback (Comprehensive)  
- Queries GA's Data Explorer API
- Filters strictly to Landsat 8/9 platforms
- Downloads raw bands and processes locally
- Applies standardized naming conventions

### 3. Automated Masking
- Downloads corresponding fmasks
- Applies clear masks (fmask == 1) to all FC data
- Creates `*_clr.tif` files for EDS processing

## Output Structure

```
D:\data\lsat\{tile}\
├── {year}\{yearmonth}\ (SR start/end dates)
│   ├── ga_ls{X}c_ard_{pathrow}_{YYYYMMDD}_srb{6|7}.tif
│   ├── ga_ls{X}c_ard_{pathrow}_{YYYYMMDD}_fmask.tif  
│   ├── ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms.tif
│   └── ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms_clr.tif ✓
└── {year}\{yearmonth}\ (10 years seasonal FC July-Oct)
    ├── ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms.tif
    └── ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms_clr.tif ✓
```

Where:
- `{X}` = Landsat sensor (8 or 9 only)
- `{pathrow}` = 6-digit path+row (e.g., `089078`)
- `✓` = Files ready for EDS processing

## Processing Workflow

1. **Validate Parameters** - Check tile exists in database, validate dates
2. **Check S3 Sources** - Attempt fast download of existing processed data
3. **SR Date Acquisition** - Ensure start/end SR composites exist
4. **FC Seasonal Download** - Get 10 years of July-Oct FC data from GA
5. **Mask Application** - Apply clear masks to all FC products  
6. **Provenance Validation (optional)** - Confirm all FC are LS8/LS9-only; report or quarantine non-compliant items
7. **Validation** - Verify all required files are present and properly formatted

## Requirements

### Environment
- Python environment with geospatial libraries (use `slats` conda env)
- Database connection to EDS PostgreSQL database
- Internet access for GA DEA API and S3

### Dependencies
```bash
# Core processing
rasterio geopandas sqlalchemy psycopg2 python-dotenv

# Web APIs  
s3fs urllib3 requests

# Optional: RIOS for advanced masking
rios
```

### Database Configuration
Set environment variables in `.env`:
```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=eds_database
DB_USER=your_username
DB_PASSWORD=your_password
```

## Usage Examples

### Basic Usage
```bash
# Download all data for tile 089_078 
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831
```

### Custom Destination
```bash
# Use different output directory
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --dest "E:\satellite_data"
```

### Relaxed Cloud Cover
```bash
# Allow higher cloud cover for sparse data regions
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --cloud-cover 70
```

### Extended Time Range
```bash
# Get 15 years of seasonal FC data
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --span-years 15
```

### Flexible Date Search
```bash
# Search ±14 days around target dates for SR composites
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --search-days 14
```

## Individual Script Usage

### Download from S3 Only
```bash
python scripts/download_fc_from_s3.py --tile 089_078 --start-yyyymm 202307 --end-yyyymm 202410 --dest "D:\data\lsat"
```

### Download Seasonal FC from GA
```bash
python scripts/download_seasonal_fc_from_ga.py --tile 089_078 --start-year 2014 --end-year 2024 --dest "D:\data\lsat"
```

### Ensure SR Dates Exist  
```bash
python scripts/ensure_sr_dates_for_eds.py --tile 089_078 --start-date 20230720 --end-date 20240831 --dest "D:\data\lsat"
```

### Apply Clear Masks
```bash
python scripts/derive_fc_clr.py --dir "D:\data\lsat\089_078" --preset clr
```

### Validate FC Provenance (LS8/LS9-only)
```bash
# Report only (writes CSV report)
python scripts/validate_fc_provenance.py --tile 089_078 --root D:\data\lsat --out data\fc_089_078_provenance.csv

# Quarantine any legacy L5/L7 FC to a folder under the tile
python scripts/validate_fc_provenance.py --tile 089_078 --root D:\data\lsat --action move --quarantine-dir _quarantine
```

### Run Provenance Check from the Master Pipeline
```bash
# Enable provenance validation at the end of the pipeline (report-only)
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --validate-fc-provenance

# Quarantine non-LS8/9 FC after processing
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --validate-fc-provenance --prov-action move --prov-quarantine-dir _quarantine

# Tune SR fallback window for identification
python scripts/eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --validate-fc-provenance --prov-search-days 14
```

## Troubleshooting

### Common Issues

**Database Connection Errors**
- Verify `.env` file exists with correct database credentials
- Check database is running and accessible

**S3 Download Failures**
- S3 has limited data coverage - this is expected
- Script automatically falls back to GA DEA download

**GA API Rate Limits**
- Script includes automatic delays (1-5 seconds) between requests
- If rate limited, wait and retry

**Missing Fmask Data**
- Some older Landsat scenes may not have fmask available
- Script logs warnings but continues processing

**Disk Space Issues**
- 10 years of seasonal data can be 50-100GB per tile
- Ensure adequate disk space at destination

### Performance Tips

- **Use SSD storage** for faster I/O during processing
- **Sufficient RAM** (16GB+) for large raster operations  
- **Stable internet** for reliable GA API access
- **Run overnight** for large time spans (10+ years)

## File Naming Conventions

The pipeline follows EDS-standard naming:

### Surface Reflectance (LS8/LS9 only)
```
ga_ls{sensor}c_ard_{pathrow}_{YYYYMMDD}_srb{bandcount}.tif
ga_ls{sensor}c_ard_{pathrow}_{YYYYMMDD}_fmask.tif
```

### Fractional Cover (LS8/LS9 provenance only)
```
ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms.tif      # 3-band stack (BS,PV,NPV)
ga_ls_fc_{pathrow}_{YYYYMMDD}_fc3ms_clr.tif  # Clear masked (EDS ready)
```

## Integration with EDS

After successful data preparation:

1. **Verify Data** - Check all required files exist with correct naming
2. **Run EDS Model** - Use `eds_legacy_method_window.py` or `run_eds.py`
3. **Vector Processing** - Process outputs with `polygonize_*.py` scripts

## Support

For issues with:
- **Data acquisition**: Check S3/GA API status and network connectivity
- **Database queries**: Verify `landsat_tiles` table structure and tile coverage
- **File processing**: Check available disk space and file permissions
- **EDS integration**: Ensure output files match expected naming patterns
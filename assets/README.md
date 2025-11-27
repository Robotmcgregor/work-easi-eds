# Assets Folder

This folder contains static assets for the EDS (Early Detection System), primarily shapefiles and related geospatial data.

## Shapefile Structure

Place your Landsat tile boundary shapefiles in this folder. The system will automatically detect and process `.shp` files.

### Expected Shapefile Format

The shapefile should contain Australian Landsat tile boundaries with the following attributes:

**Required Fields** (one of these naming conventions):
- `PATH` and `ROW` - Landsat path and row numbers
- `WRS_PATH` and `WRS_ROW` - World Reference System path and row
- `PR` or `PATH_ROW` - Combined path/row field (format: "090066")

**Optional Fields:**
- Any additional metadata about the tiles
- Tile names, acquisition dates, etc.

### File Organization

```
assets/
├── README.md                    # This file
├── landsat_tiles.shp           # Main shapefile
├── landsat_tiles.shx           # Shapefile index
├── landsat_tiles.dbf           # Attribute data
├── landsat_tiles.prj           # Projection information
└── landsat_tiles.cpg           # Code page (optional)
```

**Note:** All shapefile components (.shp, .shx, .dbf, .prj) must be present for proper loading.

## Integration Process

After placing your shapefiles in this folder:

1. **Validate the shapefile:**
   ```powershell
   py integrate_shapefile.py
   ```

2. **Review validation results** to ensure:
   - Path/row data is correctly detected
   - Coordinate system is appropriate (WGS84 preferred)
   - Tile boundaries cover Australian Landsat coverage area

3. **Proceed with integration** to update the database with accurate tile geometries

## Coordinate System

- **Preferred:** WGS84 (EPSG:4326)
- **Supported:** Any geographic coordinate system
- The system will automatically reproject to WGS84 if needed

## Coverage Area

Expected coverage for Australian Landsat tiles:
- **Paths:** 90-116 (Landsat WRS-2)
- **Rows:** 66-90
- **Total tiles:** ~300 tiles covering continental Australia

## Troubleshooting

### Common Issues:

1. **"No path/row data found"**
   - Check field names in your shapefile
   - Ensure path/row values are numeric
   - Review the validation output for available fields

2. **"Shapefile not found"**
   - Verify all shapefile components are present
   - Check file permissions
   - Ensure files are not corrupted

3. **"Coordinate system issues"**
   - Verify .prj file is present and valid
   - Consider manually setting CRS if needed

### Getting Help:

Run the validation script to see detailed information about your shapefile:
```powershell
py integrate_shapefile.py
```

The validation will show:
- Total number of features
- Available attribute fields
- Sample tile data
- Coordinate system information
- Path/row ranges detected

## Data Sources

Common sources for Landsat tile boundary shapefiles:
- **USGS Earth Explorer** - Download WRS-2 scene boundaries
- **USGS Landsat Tools** - Administrative boundary datasets
- **State/Territory agencies** - Local Landsat processing centers

## Integration with EDS System

Once integrated, the shapefile data will:
- Update tile boundaries in the PostgreSQL database
- Provide accurate tile polygons for the dashboard
- Enable precise geographic querying
- Support spatial analysis and processing planning

The system will use this data to:
- Plan processing jobs by geographic extent
- Display accurate tile boundaries on maps
- Calculate processing priorities based on tile size/importance
- Enable spatial filtering and analysis
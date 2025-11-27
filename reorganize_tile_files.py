#!/usr/bin/env python3
"""
Analyze FC files to determine their actual Landsat path/row based on geospatial coordinates,
then rename and move them to the correct directory structure.

This script:
1. Reads the geospatial bounds of each FC file
2. Determines the actual Landsat path/row based on center coordinates
3. Renames files to match their actual tile content
4. Moves them to the correct directory structure
5. Also moves corresponding FMASK files
"""

import os
import shutil
from pathlib import Path
from osgeo import gdal
import re
from typing import Dict, Tuple, Optional
from collections import defaultdict

# Landsat WRS-2 tile center coordinates (approximate)
# Format: (path, row): (center_x_albers, center_y_albers)
TILE_CENTERS = {
    (88, 78): (520000, -2875000),   # Approximate Albers coordinates
    (88, 79): (520000, -2740000),
    (89, 78): (565000, -2875000),   # Target tile
    (89, 79): (565000, -2740000),
    (90, 78): (610000, -2875000),
    (90, 79): (610000, -2740000),
}

def get_file_center_coords(filepath: Path) -> Tuple[float, float]:
    """Get the center coordinates of a raster file."""
    ds = gdal.Open(str(filepath))
    if not ds:
        raise ValueError(f"Cannot open file: {filepath}")
    
    gt = ds.GetGeoTransform()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    
    # Calculate center coordinates
    center_x = gt[0] + gt[1] * xsize / 2
    center_y = gt[3] + gt[5] * ysize / 2
    
    return center_x, center_y

def determine_actual_tile(center_x: float, center_y: float) -> Tuple[int, int]:
    """Determine actual Landsat path/row based on center coordinates."""
    min_distance = float('inf')
    best_tile = None
    
    for (path, row), (tile_x, tile_y) in TILE_CENTERS.items():
        distance = ((center_x - tile_x) ** 2 + (center_y - tile_y) ** 2) ** 0.5
        if distance < min_distance:
            min_distance = distance
            best_tile = (path, row)
    
    return best_tile

def extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract date from filename."""
    match = re.search(r'(\d{8})', filename)
    return match.group(1) if match else None

def create_correct_filename(original_filename: str, actual_path: int, actual_row: int) -> str:
    """Create correct filename with actual path/row."""
    # Extract date and other components
    date = extract_date_from_filename(original_filename)
    if not date:
        raise ValueError(f"Cannot extract date from filename: {original_filename}")
    
    # Determine file type
    if '_fc3ms.tif' in original_filename:
        return f"ga_ls_fc_{actual_path:03d}{actual_row:03d}_{date}_fc3ms.tif"
    elif '_fmask.tif' in original_filename:
        # Extract sensor info if possible
        if 'ls5t' in original_filename:
            sensor = 'ga_ls5t_oa'
        elif 'ls7e' in original_filename:
            sensor = 'ga_ls7e_oa'
        elif 'ls8c' in original_filename:
            sensor = 'ga_ls8c_oa'
        elif 'ls9c' in original_filename:
            sensor = 'ga_ls9c_oa'
        else:
            sensor = 'ga_ls_oa'  # Generic fallback
        return f"{sensor}_{actual_path:03d}{actual_row:03d}_{date}_fmask.tif"
    else:
        # Keep original name but update path/row
        return re.sub(r'(\d{6})', f"{actual_path:03d}{actual_row:03d}", original_filename)

def ensure_directory_structure(base_path: Path, path: int, row: int, year: str, yearmonth: str) -> Path:
    """Ensure correct directory structure exists."""
    tile_dir = base_path / f"{path:03d}_{row:03d}"
    year_dir = tile_dir / year / yearmonth
    year_dir.mkdir(parents=True, exist_ok=True)
    return year_dir

def find_corresponding_files(fc_file: Path, base_dir: Path) -> list:
    """Find corresponding FMASK and other files for an FC file."""
    corresponding_files = []
    
    # Extract date from FC filename
    date = extract_date_from_filename(fc_file.name)
    if not date:
        return corresponding_files
    
    # Look for files with same date in same directory
    for file_path in fc_file.parent.rglob("*"):
        if file_path.is_file() and date in file_path.name and file_path != fc_file:
            # Check if it's a related file type
            if any(suffix in file_path.name for suffix in ['_fmask.tif', '_clr.tif', '_oa.tif']):
                corresponding_files.append(file_path)
    
    return corresponding_files

def main():
    base_dir = Path(r"D:\data\lsat")
    source_dir = base_dir / "089_078"
    
    if not source_dir.exists():
        print(f"Source directory does not exist: {source_dir}")
        return
    
    print("Analyzing files and determining actual tile locations...")
    print("=" * 60)
    
    # Find all FC files
    fc_files = list(source_dir.rglob("*_fc3ms.tif"))
    print(f"Found {len(fc_files)} FC files to analyze")
    
    # Track files by actual tile
    files_by_tile = defaultdict(list)
    analysis_results = []
    
    for fc_file in fc_files:
        try:
            # Get center coordinates
            center_x, center_y = get_file_center_coords(fc_file)
            
            # Determine actual tile
            actual_path, actual_row = determine_actual_tile(center_x, center_y)
            
            # Extract date for directory structure
            date = extract_date_from_filename(fc_file.name)
            year = date[:4]
            yearmonth = date[:6]
            
            result = {
                'original_file': fc_file,
                'center_coords': (center_x, center_y),
                'actual_path': actual_path,
                'actual_row': actual_row,
                'date': date,
                'year': year,
                'yearmonth': yearmonth,
                'corresponding_files': find_corresponding_files(fc_file, source_dir)
            }
            
            analysis_results.append(result)
            files_by_tile[(actual_path, actual_row)].append(result)
            
            print(f"{fc_file.name}")
            print(f"  Center: ({center_x:.0f}, {center_y:.0f})")
            print(f"  Actual tile: {actual_path:03d}_{actual_row:03d}")
            print(f"  Corresponding files: {len(result['corresponding_files'])}")
            print()
            
        except Exception as e:
            print(f"ERROR analyzing {fc_file.name}: {e}")
    
    # Show summary by tile
    print("\nSummary by actual tile:")
    print("-" * 40)
    for (path, row), file_list in sorted(files_by_tile.items()):
        print(f"Tile {path:03d}_{row:03d}: {len(file_list)} files")
    
    # Ask for confirmation before moving
    print(f"\nThis will reorganize {len(analysis_results)} FC files and their corresponding files.")
    print("The files will be moved from 089_078 to their correct tile directories.")
    
    confirm = input("\nProceed with moving files? (y/N): ").lower().strip()
    if confirm != 'y':
        print("Operation cancelled.")
        return
    
    print("\nMoving files to correct locations...")
    print("=" * 40)
    
    moved_count = 0
    error_count = 0
    
    for result in analysis_results:
        try:
            fc_file = result['original_file']
            actual_path = result['actual_path']
            actual_row = result['actual_row']
            year = result['year']
            yearmonth = result['yearmonth']
            
            # Create correct directory structure
            dest_dir = ensure_directory_structure(base_dir, actual_path, actual_row, year, yearmonth)
            
            # Move and rename FC file
            new_fc_name = create_correct_filename(fc_file.name, actual_path, actual_row)
            new_fc_path = dest_dir / new_fc_name
            
            print(f"Moving: {fc_file.name}")
            print(f"  To: {new_fc_path.relative_to(base_dir)}")
            
            shutil.move(str(fc_file), str(new_fc_path))
            moved_count += 1
            
            # Move corresponding files (FMASK, etc.)
            for corr_file in result['corresponding_files']:
                try:
                    new_corr_name = create_correct_filename(corr_file.name, actual_path, actual_row)
                    new_corr_path = dest_dir / new_corr_name
                    
                    print(f"  Moving: {corr_file.name}")
                    print(f"    To: {new_corr_path.relative_to(base_dir)}")
                    
                    shutil.move(str(corr_file), str(new_corr_path))
                    
                except Exception as e:
                    print(f"  ERROR moving {corr_file.name}: {e}")
                    error_count += 1
            
            print()
            
        except Exception as e:
            print(f"ERROR processing {fc_file.name}: {e}")
            error_count += 1
    
    print(f"\n=== Reorganization Complete ===")
    print(f"Files moved successfully: {moved_count}")
    print(f"Errors encountered: {error_count}")
    
    # Check if source directory is now empty (except for year folders)
    remaining_files = list(source_dir.rglob("*.tif"))
    if remaining_files:
        print(f"\nWarning: {len(remaining_files)} files remain in source directory")
    else:
        print(f"\nSource directory {source_dir.name} is now empty of .tif files")
    
    # Show final structure
    print("\nFinal directory structure:")
    for tile_dir in sorted(base_dir.glob("???_???")):
        if tile_dir.is_dir():
            fc_count = len(list(tile_dir.rglob("*_fc3ms.tif")))
            fmask_count = len(list(tile_dir.rglob("*_fmask.tif")))
            if fc_count > 0 or fmask_count > 0:
                print(f"  {tile_dir.name}: {fc_count} FC files, {fmask_count} FMASK files")

if __name__ == "__main__":
    main()
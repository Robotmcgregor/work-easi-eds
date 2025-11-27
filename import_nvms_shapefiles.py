#!/usr/bin/env python
"""
Import NVMS pilot shapefiles into the database as NVMSDetection records.
Assumptions:
 - Run id for these shapefiles is NVMS_QLD_Run03 (adjustable via RUN_ID)
 - Shapefile directories are under data/pilot_shp
 - Tile id is encoded in folder/filename as pXXXrYYY (e.g. p090r086 -> tile_id '090086')

This script will create NVMSRun if missing, link detections to NVMSResult when present,
store original properties as JSONB and geometry as MULTIPOLYGON in EPSG:4326.

Usage:
  py import_nvms_shapefiles.py [--force]

--force : re-import even if there are existing detections for the run/tile
"""

import sys
import re
from pathlib import Path
from datetime import datetime
import argparse
import geopandas as gpd
from shapely.geometry import mapping
from hashlib import md5

# add src to path
proj_root = Path(__file__).parent
sys.path.insert(0, str(proj_root / 'src'))

from src.database.connection import DatabaseManager
from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
from src.config.settings import get_config

RUN_ID = 'NVMS_QLD_Run03'
# Default input directory for shapefiles (can be overridden with --input-dir)
DEFAULT_INPUT_DIR = proj_root / 'data' / 'processing_results' / 'Run3'

TILE_RE = re.compile(r'p(\d{3})r(\d{3})', re.IGNORECASE)


def find_shapefiles(base_dir):
    return list(base_dir.rglob('*.shp'))


def extract_tile_id_from_path(p: Path):
    m = TILE_RE.search(p.name)
    if not m:
        # try parent dir
        m = TILE_RE.search(str(p.parent.name))
    if m:
        path_str = m.group(1)
        row_str = m.group(2)
        return f"{path_str}{row_str}"
    return None


def ensure_run(session, run_id=RUN_ID):
    run = session.query(NVMSRun).filter_by(run_id=run_id).first()
    if not run:
        run = NVMSRun(run_id=run_id, run_number=3, description='Imported NVMS Run 3 shapefiles')
        session.add(run)
        session.flush()
    return run


def import_shapefile(session, shp_path: Path, run_id=RUN_ID, force=False):
    print(f"Importing {shp_path}")
    tile_id = extract_tile_id_from_path(shp_path)
    if not tile_id:
        print(f"  Could not extract tile id from {shp_path}; skipping")
        return 0

    # Check existing detections for this run/tile
    existing_count = session.query(NVMSDetection).filter(
        NVMSDetection.run_id == run_id,
        NVMSDetection.tile_id == tile_id
    ).count()
    if existing_count and not force:
        print(f"  Detections already exist for {run_id} / {tile_id} ({existing_count}), skipping (use --force to re-import)")
        return 0

    # Read shapefile
    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        # assume EPSG:4326
        gdf = gdf.set_crs(epsg=4326)
    else:
        gdf = gdf.to_crs(epsg=4326)

    # Find linking NVMSResult (if previously inserted)
    nvms_result = session.query(NVMSResult).filter(
        NVMSResult.run_id == run_id,
        NVMSResult.tile_id == tile_id
    ).first()

    imported = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        # properties: all fields except geometry
        props = {k: v for k, v in row.items() if k != gdf.geometry.name}

        # store geometry as geojson + WKT (no PostGIS required)
        geojson_geom = mapping(geom)
        # normalize WKT by squeezing spaces
        wkt = geom.wkt
        normalized_wkt = " ".join(wkt.split())
        # build deterministic hash across run/tile/geometry
        h = md5(f"{run_id}|{tile_id}|{normalized_wkt}".encode('utf-8')).hexdigest()

        det = NVMSDetection(
            run_id=run_id,
            result_id=nvms_result.id if nvms_result else None,
            tile_id=tile_id,
            properties=props,
            geom_geojson=geojson_geom,
            geom_wkt=normalized_wkt,
            geom_hash=h,
            imported_at=datetime.utcnow()
        )
        # Avoid duplicate inserts by catching unique constraint violations
        try:
            session.add(det)
            session.flush()
        except Exception as e:
            # IntegrityError if duplicate geom_hash; safe to ignore
            session.rollback()
            session.begin()
        imported += 1

    session.flush()
    print(f"  Imported {imported} detection(s) for tile {tile_id}")
    return imported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Re-import even if detections exist')
    parser.add_argument('--input-dir', type=str, help='Override input directory containing shapefiles (default: data/processing_results/Run3)')
    args = parser.parse_args()

    config = get_config()
    db = DatabaseManager(config.database.connection_url)

    # Ensure tables exist (will create new nvms_detections table if model added)
    # Ensure PostGIS extension exists (required for Geometry column)
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
            conn.commit()
    except Exception as e:
        print(f"Warning: could not create PostGIS extension: {e}\nIf your database does not have PostGIS enabled, the geometry column creation will fail.")

    db.create_tables()

    input_dir = Path(args.input_dir) if args.input_dir else DEFAULT_INPUT_DIR
    if not input_dir.exists():
        print(f"Input directory {input_dir} does not exist; aborting.")
        return
    shp_files = find_shapefiles(input_dir)
    print(f"Found {len(shp_files)} shapefiles under {input_dir}")

    total = 0
    with db.get_session() as session:
        ensure_run(session, RUN_ID)
        for shp in shp_files:
            try:
                imported = import_shapefile(session, shp, run_id=RUN_ID, force=args.force)
                total += imported
            except Exception as e:
                print(f"Error importing {shp}: {e}")
                session.rollback()
        session.commit()

    print(f"Done. Total detections imported: {total}")

if __name__ == '__main__':
    main()

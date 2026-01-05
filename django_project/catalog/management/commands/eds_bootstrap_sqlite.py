from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import sqlite3
from pathlib import Path

class Command(BaseCommand):
    help = "Bootstrap SQLite legacy schema and import Landsat tiles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tiles-shp",
            required=True,
            help="Path to Landsat tile grid shapefile",
        )

    def handle(self, *args, **options):
        db_path = settings.DATABASES["default"]["NAME"]
        shp_path = Path(options["tiles_shp"]).expanduser()

        if not shp_path.exists():
            raise CommandError(f"Shapefile not found: {shp_path}")

        self.stdout.write(f"Using DB: {db_path}")
        self.stdout.write(f"Using tiles shapefile: {shp_path}")

        # ---- connect to SQLite ----
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        # ---- create landsat_tiles table if missing ----
        self.stdout.write("Ensuring landsat_tiles table exists…")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS landsat_tiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tile_id TEXT UNIQUE NOT NULL,
            path INTEGER NOT NULL,
            row INTEGER NOT NULL,
            bounds_geojson TEXT,
            status TEXT DEFAULT 'pending',
            is_active BOOLEAN DEFAULT 1
        );
        """)

        con.commit()

        # ---- import tiles from shapefile ----
        try:
            import geopandas as gpd
        except ImportError:
            raise CommandError("geopandas is required to import tiles")

        gdf = gpd.read_file(shp_path)

        required_cols = {"path", "row"}
        missing = required_cols - set(gdf.columns)
        if missing:
            raise CommandError(f"Missing required columns: {missing}")

        inserted = 0
        updated = 0

        for _, r in gdf.iterrows():
            try:
                path_val = int(r["path"])
                row_val = int(r["row"])
            except Exception:
                continue

            tile_id = f"p{path_val:03d}r{row_val:03d}"

            geom_json = None
            if r.geometry is not None:
                geom_json = r.geometry.__geo_interface__

            cur.execute("""
                INSERT INTO landsat_tiles (tile_id, path, row, bounds_geojson, status, is_active)
                VALUES (?, ?, ?, ?, 'pending', 1)
                ON CONFLICT(tile_id) DO UPDATE SET
                    path=excluded.path,
                    row=excluded.row,
                    bounds_geojson=excluded.bounds_geojson,
                    is_active=1;
            """, (
                tile_id,
                path_val,
                row_val,
                str(geom_json) if geom_json else None,
            ))

            if cur.rowcount == 1:
                inserted += 1
            else:
                updated += 1

        con.commit()
        con.close()

        self.stdout.write(self.style.SUCCESS(
            f"Bootstrap complete: {inserted} inserted, {updated} updated"
        ))

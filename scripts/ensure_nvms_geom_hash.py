"""Ensure nvms_detections has geom_hash populated and unique index.
Run: python scripts\ensure_nvms_geom_hash.py
"""
from hashlib import md5
from sqlalchemy import text
from src.config import load_config
from src.database.connection import DatabaseManager

DEF_INDEX = 'ux_nvms_geom_hash'

UPDATE_BATCH_SQL = """
UPDATE nvms_detections
SET geom_hash = md5(run_id || '|' || tile_id || '|' || geom_wkt)
WHERE geom_hash IS NULL;
"""

ADD_COLUMN_SQL = """
ALTER TABLE nvms_detections
ADD COLUMN IF NOT EXISTS geom_hash text;
"""

CREATE_INDEX_SQL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {DEF_INDEX}
ON nvms_detections(geom_hash);
"""

CHECK_NULLS_SQL = "SELECT COUNT(*) FROM nvms_detections WHERE geom_hash IS NULL;"

def main():
    cfg = load_config()
    db = DatabaseManager(cfg.database.connection_url)
    with db.engine.connect() as conn:
        print("Ensuring geom_hash column exists...")
        conn.execute(text(ADD_COLUMN_SQL))
        conn.commit()
        print("Populating missing hashes...")
        conn.execute(text(UPDATE_BATCH_SQL))
        conn.commit()
        missing = conn.execute(text(CHECK_NULLS_SQL)).scalar()
        print(f"Missing geom_hash rows after update: {missing}")
        print("Creating unique index (if absent)...")
        conn.execute(text(CREATE_INDEX_SQL))
        conn.commit()
        print("Done.")

if __name__ == '__main__':
    main()

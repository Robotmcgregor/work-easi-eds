#!/usr/bin/env python
import sys
from pathlib import Path
import json
import traceback
from datetime import datetime

print("peek_detection: starting...")
try:
    # Ensure src is on path
    project_root = Path(__file__).resolve().parents[1]
    # Insert the project root so that the top-level package 'src' is importable
    sys.path.insert(0, str(project_root))
    print(f"project_root={project_root}; sys.path[0]={sys.path[0]}")

    from src.database.connection import DatabaseManager
    from src.config.settings import get_config
    from src.database.nvms_models import NVMSDetection

    print("imports ok")
except Exception as e:
    print("import error:\n" + traceback.format_exc())
    sys.exit(2)


def summarize_geom(val):
    t = type(val).__name__
    preview = None
    if isinstance(val, (str, bytes, bytearray)):
        s = val.decode() if isinstance(val, (bytes, bytearray)) else val
        preview = s[:200]
        kind = "string"
    elif isinstance(val, dict):
        preview = json.dumps(val)[:200]
        kind = "dict"
    else:
        try:
            preview = str(val)[:200]
        except Exception:
            preview = "<unrepr>"
        kind = t
    return kind, preview


def main(ids):
    try:
        cfg = get_config()
        db_url = cfg.database.connection_url
    except Exception:
        # fallback: environment or default
        print("get_config() failed, please ensure settings are configured")
        print(traceback.format_exc())
        sys.exit(3)
    db = DatabaseManager(db_url)
    print(f"DB: {db_url}")
    with db.get_session() as session:
        for sid in ids:
            try:
                nid = int(sid)
            except ValueError:
                print(f"Skipping non-int id: {sid}")
                continue
            det = session.query(NVMSDetection).get(nid)
            if not det:
                print(f"NVMS #{nid}: NOT FOUND")
                continue
            kind, prev = summarize_geom(det.geom_geojson)
            print(f"NVMS #{nid} tile={det.tile_id} imported_at={det.imported_at}")
            print(f"  geom_geojson type={kind}")
            print(f"  geom preview: {prev}")
            print("-")


if __name__ == "__main__":
    if len(sys.argv) <= 1:
        print("Usage: py tools/peek_detection.py <id> [<id> ...]")
        sys.exit(1)
    main(sys.argv[1:])

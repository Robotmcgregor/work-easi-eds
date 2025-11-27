"""Quick database counts for detection tables.
Run: python scripts/db_counts.py
"""

from src.config import load_config
from src.database.connection import DatabaseManager
from sqlalchemy import text


def main():
    cfg = load_config()
    db = DatabaseManager(cfg.database.connection_url)
    print(f"DB URL: {db.database_url}")
    with db.get_session() as s:
        def safe(query):
            try:
                return s.execute(text(query)).scalar()
            except Exception as e:
                print(f"Query failed: {query}\n  -> {e}")
                return None
        detection_alerts = safe("SELECT COUNT(*) FROM detection_alerts")
        nvms_total = safe("SELECT COUNT(*) FROM nvms_detections")
        nvms_clearing = safe("SELECT COUNT(*) FROM nvms_detections WHERE (properties->>'IsClearing')='y'")
        print(f"detection_alerts total: {detection_alerts}")
        print(f"nvms_detections total: {nvms_total}")
        print(f"nvms_detections IsClearing='y': {nvms_clearing}")
        # Example: recent clearing detections
        recent = safe("SELECT COUNT(*) FROM nvms_detections WHERE (properties->>'IsClearing')='y' AND imported_at > now() - interval '30 days'")
        print(f"nvms_detections IsClearing='y' last 30d: {recent}")

if __name__ == "__main__":
    main()

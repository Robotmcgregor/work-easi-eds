"""Check for duplicate NVMS detections by identical geometry WKT per run/tile.
Run: python scripts\check_nvms_duplicates.py
"""

from src.config import load_config
from src.database.connection import DatabaseManager
from sqlalchemy import text


def main():
    cfg = load_config()
    db = DatabaseManager(cfg.database.connection_url)
    with db.engine.connect() as conn:
        dup_summary_sql = text(
            """
        SELECT run_id, COUNT(*) AS dup_groups, SUM(cnt - 1) AS extra_rows
        FROM (
          SELECT run_id, geom_wkt, COUNT(*) AS cnt
          FROM nvms_detections
          GROUP BY run_id, geom_wkt
          HAVING COUNT(*) > 1
        ) d
        GROUP BY run_id
        ORDER BY extra_rows DESC NULLS LAST
        """
        )
        rows = conn.execute(dup_summary_sql).fetchall()
        print("Duplicate geometry groups per run (geom_wkt):")
        if not rows:
            print("  None found")
        else:
            for r in rows:
                print(f"  {r.run_id}: groups={r.dup_groups} extra_rows={r.extra_rows}")

        examples_sql = text(
            """
        SELECT run_id, tile_id, LEFT(geom_wkt,120) AS wkt_snip, COUNT(*) AS cnt
        FROM nvms_detections
        GROUP BY run_id, tile_id, geom_wkt
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 10
        """
        )
        ex = conn.execute(examples_sql).fetchall()
        if ex:
            print("\nExamples (top 10):")
            for r in ex:
                print(
                    f"  run={r.run_id} tile={r.tile_id} cnt={r.cnt} wkt_snip={r.wkt_snip}"
                )


if __name__ == "__main__":
    main()

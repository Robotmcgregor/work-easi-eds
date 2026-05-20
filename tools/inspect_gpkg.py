from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def _print_table(conn: sqlite3.Connection, table: str, limit: int = 50) -> None:
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table} LIMIT ?", (int(limit),))
    except sqlite3.Error as e:
        print(f"[WARN] Could not read table '{table}': {e}")
        return

    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchall()

    print(f"\n== {table} (showing up to {limit} rows) ==")
    if not cols:
        print("(no columns)")
        return

    print(" | ".join(cols))
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))


def inspect_gpkg(path: Path, *, limit: int = 50) -> int:
    path = Path(path)
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return 2

    print(f"[INFO] GeoPackage: {path}")
    print(f"[INFO] Size: {path.stat().st_size / (1024 * 1024):.2f} MB")

    try:
        conn = sqlite3.connect(str(path))
    except Exception as e:
        print(f"[ERROR] Could not open as SQLite: {e}")
        return 3

    with conn:
        # Quick integrity check
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            integrity = cur.fetchone()
            print(f"[INFO] SQLite integrity_check: {integrity[0] if integrity else 'unknown'}")
        except Exception as e:
            print(f"[WARN] integrity_check failed: {e}")

        # Standard GPKG metadata tables
        _print_table(conn, "gpkg_contents", limit=limit)
        _print_table(conn, "gpkg_geometry_columns", limit=limit)
        _print_table(conn, "gpkg_spatial_ref_sys", limit=min(limit, 20))

        # Feature counts per layer (best-effort)
        try:
            cur = conn.cursor()
            cur.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")
            layer_tables = [r[0] for r in cur.fetchall()]
        except Exception:
            layer_tables = []

        if layer_tables:
            print("\n== feature counts ==")
            for t in layer_tables:
                try:
                    cur = conn.cursor()
                    cur.execute(f"SELECT COUNT(*) FROM '{t}'")
                    n = cur.fetchone()[0]
                    print(f"{t}: {n}")
                except Exception as e:
                    print(f"{t}: [WARN] count failed: {e}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect a GeoPackage (.gpkg) via SQLite metadata tables")
    ap.add_argument("gpkg", type=Path, help="Path to .gpkg")
    ap.add_argument("--limit", type=int, default=50, help="Max rows to print per metadata table")
    args = ap.parse_args()
    return inspect_gpkg(args.gpkg, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())

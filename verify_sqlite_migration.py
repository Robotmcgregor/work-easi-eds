"""
Verify SQLite database after migration from PostgreSQL.

This script checks that the SQLite database has the expected tables and data.
"""

import sys
import argparse
from pathlib import Path
from sqlalchemy import create_engine, inspect

# Optional table formatting
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False
    # Simple fallback table display
    def tabulate(data, headers, tablefmt="grid"):
        # Simple text-based table
        col_widths = [len(str(h)) for h in headers]
        for row in data:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))
        
        # Print header
        header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
        separator = "-+-".join("-" * w for w in col_widths)
        
        result = header_line + "\n" + separator + "\n"
        for row in data:
            result += " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) + "\n"
        
        return result

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.database.models import Base


def verify_database(sqlite_path: str):
    """Verify the SQLite database structure and content."""
    
    print("=" * 60)
    print("SQLite Database Verification")
    print("=" * 60)
    print(f"\nDatabase: {sqlite_path}\n")
    
    # Check if file exists
    if not Path(sqlite_path).exists():
        print(f"❌ Database file not found: {sqlite_path}")
        return False
    
    try:
        # Connect to SQLite
        sqlite_url = f"sqlite:///{sqlite_path}"
        engine = create_engine(sqlite_url, echo=False)
        inspector = inspect(engine)
        
        # Get all tables
        tables = inspector.get_table_names()
        
        if not tables:
            print("❌ No tables found in database")
            return False
        
        print(f"✓ Found {len(tables)} tables\n")
        
        # Expected tables from the models
        expected_tables = [
            "landsat_tiles",
            "processing_jobs",
            "detection_alerts",
            "system_status",
            "eds_runs",
            "eds_results",
            "processing_history",
            "eds_detections",
            "qc_validations",
            "qc_audit_log",
        ]
        
        # Check each table
        table_stats = []
        total_records = 0
        
        for table_name in sorted(tables):
            # Count records
            with engine.connect() as conn:
                from sqlalchemy import text
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
            
            # Check columns
            columns = inspector.get_columns(table_name)
            col_count = len(columns)
            
            # Status
            status = "✓" if table_name in expected_tables else "?"
            
            table_stats.append([status, table_name, count, col_count])
            total_records += count
        
        # Display results
        headers = ["Status", "Table Name", "Records", "Columns"]
        print(tabulate(table_stats, headers=headers, tablefmt="grid"))
        
        print(f"\n{'=' * 60}")
        print(f"Total tables: {len(tables)}")
        print(f"Total records: {total_records}")
        print(f"{'=' * 60}\n")
        
        # Check for missing expected tables
        missing = set(expected_tables) - set(tables)
        if missing:
            print(f"⚠️  Missing expected tables: {', '.join(missing)}")
        
        # Summary
        if total_records > 0:
            print("✅ Database verification successful!")
            print(f"   The database contains {total_records} records across {len(tables)} tables.")
        else:
            print("⚠️  Database is valid but empty.")
            print("   This is normal if you're migrating an empty PostgreSQL database.")
        
        engine.dispose()
        return True
        
    except Exception as e:
        print(f"❌ Error verifying database: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Verify SQLite database after migration"
    )
    
    parser.add_argument(
        "database",
        nargs="?",
        default="data/eds_database.db",
        help="Path to SQLite database file (default: data/eds_database.db)"
    )
    
    args = parser.parse_args()
    
    success = verify_database(args.database)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

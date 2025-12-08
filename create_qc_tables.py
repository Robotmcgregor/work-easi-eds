#!/usr/bin/env python
"""
Create QC validation tables for EDS system
"""

import sys
from pathlib import Path

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.qc_models import Base
from src.config.settings import get_config


def create_qc_tables():
    """Create QC validation tables"""
    try:
        config = get_config()
        db = DatabaseManager(config.database.connection_url)

        # Create tables
        Base.metadata.create_all(db.engine)
        print("✅ QC validation tables created successfully!")

        # Show created tables
        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        qc_tables = [t for t in tables if "qc_" in t]

        print(f"📊 QC tables created: {qc_tables}")

    except Exception as e:
        print(f"❌ Error creating QC tables: {e}")


if __name__ == "__main__":
    create_qc_tables()

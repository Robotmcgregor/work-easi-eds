"""
Migrate data from PostgreSQL database to SQLite database.

This script connects to your existing PostgreSQL database and migrates all data
to a new SQLite database file, maintaining the same schema structure.

Usage:
    python migrate_postgres_to_sqlite.py [--output sqlite_database.db]
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from sqlalchemy import create_engine, inspect, MetaData, Table
from sqlalchemy.orm import sessionmaker

# Optional progress bar
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    # Simple fallback progress indicator
    class tqdm:
        def __init__(self, total=None, desc="", unit=""):
            self.total = total
            self.desc = desc
            self.n = 0
        
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            pass
        
        def update(self, n):
            self.n += n
            if self.total:
                percent = (self.n / self.total) * 100
                print(f"\r{self.desc}: {self.n}/{self.total} ({percent:.1f}%)", end="", flush=True)
            else:
                print(f"\r{self.desc}: {self.n}", end="", flush=True)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.database.models import Base, LandsatTile, ProcessingJob, DetectionAlert, SystemStatus
from src.database.nvms_models import EDSRun, EDSResult, ProcessingHistory, EDSDetection
from src.database.qc_models import QCValidation, QCAuditLog

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_postgres_url():
    """Get PostgreSQL connection URL from environment or default."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://eds_user:eds_password@localhost:5432/eds_database"
    )


def create_sqlite_engine(sqlite_path: str):
    """Create SQLite engine with appropriate settings."""
    # Ensure the directory exists
    sqlite_file = Path(sqlite_path)
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Create SQLite URL
    sqlite_url = f"sqlite:///{sqlite_path}"
    
    # Create engine
    engine = create_engine(
        sqlite_url,
        echo=False,
        connect_args={'check_same_thread': False}
    )
    
    return engine


def get_table_models():
    """Get list of all table models to migrate."""
    return [
        # Core EDS models
        LandsatTile,
        ProcessingJob,
        DetectionAlert,
        SystemStatus,
        # EDS models
        EDSRun,
        EDSResult,
        ProcessingHistory,
        EDSDetection,
        # QC models
        QCValidation,
        QCAuditLog,
    ]


def count_records(session, model):
    """Count records in a table."""
    try:
        return session.query(model).count()
    except Exception as e:
        logger.warning(f"Could not count records for {model.__tablename__}: {e}")
        return 0


def migrate_table(source_session, target_session, model, source_table_name=None):
    """
    Migrate all records from one table to another.
    
    Args:
        source_session: Source database session (PostgreSQL)
        target_session: Target database session (SQLite)
        model: SQLAlchemy model class
        source_table_name: Optional different table name in source database
    """
    table_name = model.__tablename__
    
    try:
        # If source table name is different, we need to query differently
        if source_table_name:
            # Use raw SQL to query from old table name
            from sqlalchemy import text
            try:
                result = source_session.execute(text(f"SELECT COUNT(*) FROM {source_table_name}"))
                total = result.scalar()
            except Exception:
                logger.warning(f"  {table_name}: Source table '{source_table_name}' not found in PostgreSQL")
                return 0
        else:
            # Count records using model
            total = count_records(source_session, model)
        
        if total == 0:
            logger.info(f"  {table_name}: No records to migrate")
            return 0
        
        logger.info(f"  {table_name}: Migrating {total} records...")
        
        # Fetch all records in batches
        batch_size = 1000
        migrated = 0
        
        with tqdm(total=total, desc=f"  {table_name}", unit="rows") as pbar:
            offset = 0
            while True:
                # Fetch batch from source
                if source_table_name:
                    # Query from different table name using raw SQL
                    from sqlalchemy import text
                    columns = [col.name for col in model.__table__.columns]
                    cols_str = ', '.join(columns)
                    query = text(f"SELECT {cols_str} FROM {source_table_name} LIMIT {batch_size} OFFSET {offset}")
                    result = source_session.execute(query)
                    records = result.fetchall()
                    
                    if not records:
                        break
                    
                    # Convert to model instances
                    for row in records:
                        data = dict(zip(columns, row))
                        new_record = model(**data)
                        target_session.add(new_record)
                else:
                    # Use model query
                    records = source_session.query(model).limit(batch_size).offset(offset).all()
                    
                    if not records:
                        break
                    
                    # Convert to dictionaries and create new objects
                    for record in records:
                        # Get dictionary of attributes
                        data = {}
                        for column in model.__table__.columns:
                            value = getattr(record, column.name)
                            data[column.name] = value
                        
                        # Create new object for target database
                        new_record = model(**data)
                        target_session.add(new_record)
                
                # Commit batch
                target_session.commit()
                migrated += len(records)
                pbar.update(len(records))
                offset += batch_size
        
        logger.info(f"  {table_name}: ✓ Migrated {migrated} records")
        return migrated
        
    except Exception as e:
        logger.error(f"  {table_name}: ✗ Error: {e}")
        target_session.rollback()
        return 0


def migrate_database(postgres_url: str, sqlite_path: str, skip_confirmation: bool = False):
    """
    Main migration function.
    
    Args:
        postgres_url: PostgreSQL connection string
        sqlite_path: Path to SQLite database file
        skip_confirmation: Skip confirmation prompt
    """
    logger.info("=" * 60)
    logger.info("PostgreSQL to SQLite Migration Tool")
    logger.info("=" * 60)
    
    # Check if SQLite file exists
    sqlite_file = Path(sqlite_path)
    if sqlite_file.exists():
        if not skip_confirmation:
            response = input(f"\n⚠️  SQLite database '{sqlite_path}' already exists. Overwrite? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                logger.info("Migration cancelled.")
                return
        
        # Backup existing file
        backup_path = sqlite_file.with_suffix('.db.backup')
        if backup_path.exists():
            backup_path.unlink()
        sqlite_file.rename(backup_path)
        logger.info(f"Backed up existing database to: {backup_path}")
    
    try:
        # Connect to PostgreSQL
        logger.info(f"\n1. Connecting to PostgreSQL...")
        logger.info(f"   URL: {postgres_url.split('@')[1] if '@' in postgres_url else postgres_url}")
        pg_engine = create_engine(postgres_url, echo=False)
        pg_session = sessionmaker(bind=pg_engine)()
        logger.info("   ✓ Connected to PostgreSQL")
        
        # Create SQLite database
        logger.info(f"\n2. Creating SQLite database...")
        logger.info(f"   Path: {sqlite_path}")
        sqlite_engine = create_sqlite_engine(sqlite_path)
        logger.info("   ✓ Created SQLite engine")
        
        # Create all tables in SQLite
        logger.info("\n3. Creating tables in SQLite...")
        Base.metadata.create_all(sqlite_engine)
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        logger.info("   ✓ Tables created")
        
        # Migrate data
        logger.info("\n4. Migrating data...")
        models = get_table_models()
        total_migrated = 0
        
        # Table name mapping from PostgreSQL to SQLite
        # Maps new class names to old table names in PostgreSQL
        table_name_mapping = {
            'EDSRun': 'nvms_runs',
            'EDSResult': 'nvms_results',
            'EDSDetection': 'nvms_detections',
        }
        
        for model in models:
            # Check if this model has a different source table name
            source_table = table_name_mapping.get(model.__name__)
            migrated = migrate_table(pg_session, sqlite_session, model, source_table)
            total_migrated += migrated
        
        # Close connections
        pg_session.close()
        sqlite_session.close()
        pg_engine.dispose()
        sqlite_engine.dispose()
        
        logger.info("\n" + "=" * 60)
        logger.info(f"✓ Migration complete!")
        logger.info(f"  Total records migrated: {total_migrated}")
        logger.info(f"  SQLite database: {sqlite_path}")
        logger.info("=" * 60)
        
        # Show how to use the new database
        logger.info("\n📝 To use the SQLite database, update your .env file:")
        logger.info(f"   DATABASE_URL=sqlite:///{sqlite_path}")
        
    except Exception as e:
        logger.error(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate PostgreSQL database to SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate to default location (data/eds_database.db)
  python migrate_postgres_to_sqlite.py
  
  # Migrate to custom location
  python migrate_postgres_to_sqlite.py --output my_database.db
  
  # Use custom PostgreSQL URL
  python migrate_postgres_to_sqlite.py --postgres postgresql://user:pass@host:5432/db
  
  # Skip confirmation prompt
  python migrate_postgres_to_sqlite.py --yes
        """
    )
    
    parser.add_argument(
        "--output", "-o",
        default="data/eds_database.db",
        help="Output SQLite database file path (default: data/eds_database.db)"
    )
    
    parser.add_argument(
        "--postgres", "-p",
        default=None,
        help="PostgreSQL connection URL (default: from DATABASE_URL env or default)"
    )
    
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts"
    )
    
    args = parser.parse_args()
    
    # Get PostgreSQL URL
    postgres_url = args.postgres or get_postgres_url()
    
    # Run migration
    migrate_database(postgres_url, args.output, skip_confirmation=args.yes)


if __name__ == "__main__":
    main()

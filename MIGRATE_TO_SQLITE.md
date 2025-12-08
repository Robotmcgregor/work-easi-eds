# Migrating from PostgreSQL to SQLite

This guide explains how to migrate your existing PostgreSQL database to SQLite for this project.

## Why Migrate to SQLite?

SQLite offers several advantages for local development and smaller deployments:
- **No separate database server** - Everything is in a single file
- **Portable** - Easy to backup, move, or share the database
- **Simpler setup** - No need to install and configure PostgreSQL
- **Lower resource usage** - Ideal for single-user or development scenarios

## Prerequisites

Ensure you have:
1. Access to your existing PostgreSQL database
2. Python environment set up (see `SETUP_GUIDE.md`)
3. All required Python packages installed

## Migration Steps

### Step 1: Install Required Package (Optional)

For a nicer progress display during migration, install `tqdm`:

```powershell
pip install tqdm
```

Note: The migration script works without `tqdm`, but you'll get a better progress display with it.

### Step 2: Verify PostgreSQL Connection

Make sure your current `.env` file or environment variables have the correct PostgreSQL credentials:

```
DATABASE_URL=postgresql://eds_user:eds_password@localhost:5432/eds_database
```

Or if using individual variables:
```
DB_HOST=localhost
DB_PORT=5432
DB_USER=eds_user
DB_PASSWORD=your_password
DB_NAME=eds_database
```

### Step 3: Run the Migration Script

**Default migration** (creates `data/eds_database.db`):
```powershell
python migrate_postgres_to_sqlite.py
```

**Custom output location**:
```powershell
python migrate_postgres_to_sqlite.py --output path/to/my_database.db
```

**Skip confirmation prompts** (useful for scripts):
```powershell
python migrate_postgres_to_sqlite.py --yes
```

**Use custom PostgreSQL URL**:
```powershell
python migrate_postgres_to_sqlite.py --postgres "postgresql://user:pass@host:5432/dbname"
```

### Step 4: Update Configuration

After successful migration, update your `.env` file to use the SQLite database:

```
DATABASE_URL=sqlite:///data/eds_database.db
```

Or for an absolute path:
```
DATABASE_URL=sqlite:///C:/Users/DCCEEW/code/work-easi-eds/data/eds_database.db
```

### Step 5: Verify Migration

Test the new database connection:

```powershell
python -c "from src.database import db_manager; db_manager.health_check() and print('✅ SQLite connection successful!')"
```

Or run one of your dashboard scripts to verify everything works:

```powershell
python start_dashboard.py
```

## What Gets Migrated?

The migration script transfers all data from these tables:

### Core EDS Tables
- `landsat_tiles` - Tile definitions and boundaries
- `processing_jobs` - Job history and status
- `detection_alerts` - Detection results
- `system_status` - System health metrics

### NVMS Tables
- `nvms_runs` - NVMS processing runs
- `nvms_results` - NVMS detection results
- `processing_history` - Processing history records
- `nvms_detections` - Individual detections

### QC Tables
- `qc_validations` - Quality control validation records
- `qc_audit_log` - Audit trail for QC operations

## Migration Details

The script:
1. ✓ Connects to your PostgreSQL database
2. ✓ Creates a new SQLite database file
3. ✓ Creates all table schemas in SQLite
4. ✓ Copies all records from PostgreSQL to SQLite
5. ✓ Shows progress for each table
6. ✓ Backs up any existing SQLite database

## Troubleshooting

### "Connection refused" Error

PostgreSQL might not be running:
```powershell
# Check if PostgreSQL is running
Get-Service postgresql*
```

### "Authentication failed" Error

Check your credentials in `.env` file match your PostgreSQL setup.

### "Table does not exist" in PostgreSQL

This is normal if you haven't used all features yet. The script will skip empty tables.

### SQLite Database Already Exists

The script automatically backs up the existing database to `.db.backup` before overwriting.

## Performance Notes

- Migration speed depends on data volume
- Typical migration takes 1-10 seconds for small databases
- Large databases (100k+ records) may take a few minutes

## Reverting to PostgreSQL

To switch back to PostgreSQL, simply update your `.env` file:

```
DATABASE_URL=postgresql://eds_user:eds_password@localhost:5432/eds_database
```

Your PostgreSQL data remains unchanged by this migration.

## Database Backup

### Backup SQLite Database
```powershell
# Simple file copy
Copy-Item data/eds_database.db data/eds_database_backup_$(Get-Date -Format 'yyyyMMdd').db
```

### Backup PostgreSQL Database
```powershell
# Using pg_dump
pg_dump -U eds_user -d eds_database -F c -f backup.dump
```

## Differences Between PostgreSQL and SQLite

The application is designed to work with both databases, but be aware:

| Feature | PostgreSQL | SQLite |
|---------|-----------|--------|
| Concurrent writes | Full support | Limited (single writer) |
| Max database size | Unlimited | ~281 TB (practical: depends on disk) |
| Data types | Rich type system | Limited types (but sufficient) |
| Performance | Better for complex queries | Faster for simple queries |
| Setup complexity | Requires server | Single file |

For this project's use case (local development, single user), SQLite is perfectly adequate.

## Next Steps

After migration:
1. Test your dashboards and scripts with the SQLite database
2. Verify all features work as expected
3. Update any documentation or scripts that reference PostgreSQL
4. Consider committing the SQLite database to version control (if appropriate)

## Questions?

See the main project documentation:
- `README.md` - Project overview
- `SETUP_GUIDE.md` - Full setup instructions
- `POSTGRES_SETUP.md` - PostgreSQL-specific setup (if you want to keep using it)

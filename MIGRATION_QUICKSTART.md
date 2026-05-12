# PostgreSQL to SQLite Migration - Quick Start

## TL;DR - Quick Migration

```powershell
# 1. Run the migration
python migrate_postgres_to_sqlite.py

# 2. Update .env file
# Change: DATABASE_URL=postgresql://...
# To:     DATABASE_URL=sqlite:///data/eds_database.db

# 3. Verify it works
python verify_sqlite_migration.py

# 4. Test your application
python start_dashboard.py
```

## What This Does

✅ Copies ALL data from your PostgreSQL database to SQLite  
✅ Maintains the same schema structure  
✅ Backs up existing SQLite database automatically  
✅ Shows progress for each table  
✅ Leaves your PostgreSQL database unchanged  

## Files Created

- **`migrate_postgres_to_sqlite.py`** - Main migration script
- **`verify_sqlite_migration.py`** - Verification tool
- **`MIGRATE_TO_SQLITE.md`** - Detailed documentation
- **`data/eds_database.db`** - Your new SQLite database (after migration)

## Common Use Cases

### Basic Migration
```powershell
python migrate_postgres_to_sqlite.py
```

### Custom Output Location
```powershell
python migrate_postgres_to_sqlite.py --output my_data.db
```

### Verify Migration
```powershell
python verify_sqlite_migration.py data/eds_database.db
```

### Switch Back to PostgreSQL
Just change `.env` back to:
```
DATABASE_URL=postgresql://eds_user:eds_password@localhost:5432/eds_database
```

## Why SQLite?

| Feature | PostgreSQL | SQLite |
|---------|-----------|--------|
| Setup | Install server, create users | Single file |
| Portability | Requires server | Copy the .db file |
| Backups | pg_dump commands | Copy the file |
| Resources | Higher | Minimal |
| Best for | Multi-user, production | Single-user, dev |

For this project's typical use (single user, local processing), SQLite is simpler and works perfectly.

## Troubleshooting

**"Can't connect to PostgreSQL"**
- Check PostgreSQL is running: `Get-Service postgresql*`
- Verify credentials in `.env` file

**"Module not found: tqdm or tabulate"**
- These are optional for nicer output
- Scripts work without them
- Or install: `pip install tqdm tabulate`

**"Database already exists"**
- Script automatically backs up to `.db.backup`
- Use `--yes` flag to skip confirmation

## Next Steps

1. Read `MIGRATE_TO_SQLITE.md` for full details
2. Run the migration when ready
3. Update your `.env` file
4. Test your dashboards
5. Optionally uninstall PostgreSQL if no longer needed

## Need Help?

See the detailed guide: `MIGRATE_TO_SQLITE.md`

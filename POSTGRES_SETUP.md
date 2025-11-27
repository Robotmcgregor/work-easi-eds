# Manual PostgreSQL Setup for EDS

Since you already have the `eds_database` created, you just need to create the user and grant permissions.

## Option 1: Using pgAdmin (Graphical Interface)

If you installed PostgreSQL with pgAdmin:

1. **Open pgAdmin**
2. **Connect to your PostgreSQL server** (usually localhost)
3. **Create the user:**
   - Right-click "Login/Group Roles" → "Create" → "Login/Group Role"
   - Name: `eds_user`
   - Go to "Definition" tab → Password: `eds_password`
   - Go to "Privileges" tab → Check "Can login?" and "Create databases?"
   - Click "Save"

4. **Grant permissions to the database:**
   - Right-click `eds_database` → "Properties"
   - Go to "Security" tab → Click "+"
   - Grantee: `eds_user`
   - Privileges: Check "ALL"
   - Click "Save"

## Option 2: Using SQL Commands

If you can access PostgreSQL command line or pgAdmin SQL tool:

```sql
-- Connect as postgres user and run these commands:

-- Create the user
CREATE USER eds_user WITH PASSWORD 'eds_password';

-- Grant database creation privilege
ALTER USER eds_user CREATEDB;

-- Grant all privileges on the existing database
GRANT ALL PRIVILEGES ON DATABASE eds_database TO eds_user;

-- Connect to eds_database (important!)
\c eds_database;

-- Grant schema permissions
GRANT ALL ON SCHEMA public TO eds_user;
ALTER SCHEMA public OWNER TO eds_user;

-- Grant default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eds_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eds_user;
```

## Option 3: Using Windows Command Line

Find your PostgreSQL installation (usually in `C:\Program Files\PostgreSQL\[version]\bin\`):

```cmd
# Open Command Prompt and navigate to PostgreSQL bin directory, then:
psql -U postgres -d postgres

# Then run the SQL commands from Option 2 above
```

## Option 4: Update .env to use postgres user

If you prefer to keep using the postgres user, update your `.env` file:

```properties
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_NAME=eds_database
```

## Test Your Setup

After setting up the user, test the connection:

```powershell
py -c "
import sys
sys.path.insert(0, 'src')
from src.config import get_database_url
from src.database import db_manager, init_database
try:
    init_database()
    if db_manager.health_check():
        print('✅ Database connection successful!')
    else:
        print('❌ Database connection failed')
except Exception as e:
    print(f'❌ Error: {e}')
"
```

## Next Steps

Once the database is properly set up:

1. **Test connection**: Run the test above
2. **Initialize EDS**: `py scripts/setup_database.py`
3. **Load tiles**: `py scripts/initialize_tiles.py`
4. **Start dashboard**: `py scripts/run_eds.py dashboard`

Choose the option that works best for your setup!
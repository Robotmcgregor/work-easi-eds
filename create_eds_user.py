"""
Create EDS database user using PowerShell and Python.
This script will create the eds_user and set up proper permissions.
"""

import sys
import os
from pathlib import Path

# Add the src directory to the Python path
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

def create_eds_user():
    """Create the eds_user in PostgreSQL."""
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        
        # Get current postgres connection details from config
        from src.config import get_config
        config = get_config()
        
        print("🔐 Creating EDS database user...")
        print(f"Connecting to PostgreSQL as '{config.database.username}' user...")
        
        # Connect as the current user (postgres)
        conn = psycopg2.connect(
            host=config.database.host,
            port=config.database.port,
            database='postgres',  # Connect to default postgres database
            user=config.database.username,
            password=config.database.password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        cursor = conn.cursor()
        
        # Check if eds_user already exists
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='eds_user'")
        user_exists = cursor.fetchone()
        
        if user_exists:
            print("⚠️  User 'eds_user' already exists. Updating permissions...")
            # Update the user's password and permissions
            cursor.execute("ALTER USER eds_user WITH PASSWORD 'eds_password'")
            cursor.execute("ALTER USER eds_user CREATEDB")
        else:
            print("👤 Creating new user 'eds_user'...")
            # Create the new user
            cursor.execute("CREATE USER eds_user WITH PASSWORD 'eds_password'")
            cursor.execute("ALTER USER eds_user CREATEDB")
        
        # Grant permissions on the eds_database
        print("🔑 Granting permissions on eds_database...")
        cursor.execute("GRANT ALL PRIVILEGES ON DATABASE eds_database TO eds_user")
        
        # Connect to eds_database to set schema permissions
        cursor.close()
        conn.close()
        
        # Connect to the actual EDS database
        conn = psycopg2.connect(
            host=config.database.host,
            port=config.database.port,
            database='eds_database',
            user=config.database.username,
            password=config.database.password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Grant schema permissions
        print("📁 Setting up schema permissions...")
        cursor.execute("GRANT ALL ON SCHEMA public TO eds_user")
        cursor.execute("ALTER SCHEMA public OWNER TO eds_user")
        
        # Grant permissions on existing tables and sequences (if any)
        cursor.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO eds_user")
        cursor.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO eds_user")
        
        # Set default privileges for future objects
        cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eds_user")
        cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eds_user")
        
        cursor.close()
        conn.close()
        
        print("✅ EDS user created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create EDS user: {e}")
        return False

def test_eds_user_connection():
    """Test connection with the new eds_user."""
    try:
        import psycopg2
        
        print("🧪 Testing connection with eds_user...")
        
        conn = psycopg2.connect(
            host='localhost',
            port=5432,
            database='eds_database',
            user='eds_user',
            password='eds_password'
        )
        
        cursor = conn.cursor()
        cursor.execute("SELECT 'Connection successful!' as status")
        result = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        print(f"✅ {result[0]}")
        return True
        
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        return False

def update_env_file():
    """Update the .env file to use eds_user."""
    try:
        print("📝 Updating .env file to use eds_user...")
        
        # Read the current .env file
        env_file = Path('.env')
        content = env_file.read_text()
        
        # Replace the database user settings
        content = content.replace('DB_USER=postgres', 'DB_USER=eds_user')
        content = content.replace('DB_PASSWORD=postgres', 'DB_PASSWORD=eds_password')
        
        # Also update the commented DATABASE_URL if it exists
        content = content.replace(
            '# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/eds_database',
            '# DATABASE_URL=postgresql://eds_user:eds_password@localhost:5432/eds_database'
        )
        
        # Write the updated content back
        env_file.write_text(content)
        
        print("✅ .env file updated successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to update .env file: {e}")
        return False

def main():
    """Main function to create EDS user and update configuration."""
    print("🚀 EDS User Setup Script")
    print("=" * 40)
    
    # Step 1: Create the EDS user
    if not create_eds_user():
        print("\n❌ Failed to create EDS user. Please check your PostgreSQL connection and try again.")
        return False
    
    # Step 2: Test the new user connection
    if not test_eds_user_connection():
        print("\n⚠️  EDS user was created but connection test failed. Check permissions.")
        return False
    
    # Step 3: Update .env file
    if not update_env_file():
        print("\n⚠️  EDS user works but failed to update .env file. Please update manually.")
        return False
    
    print("\n" + "=" * 40)
    print("🎉 EDS User Setup Complete!")
    print("=" * 40)
    print("\nDatabase configuration:")
    print("- Host: localhost")
    print("- Port: 5432") 
    print("- Database: eds_database")
    print("- Username: eds_user")
    print("- Password: eds_password")
    
    print("\nNext steps:")
    print("1. Run: py scripts/setup_database.py")
    print("2. Run: py scripts/initialize_tiles.py")
    print("3. Run: py scripts/run_eds.py dashboard")
    
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        input("\nPress Enter to exit...")
        sys.exit(1)
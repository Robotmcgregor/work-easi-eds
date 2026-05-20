-- SQL script to create PostgreSQL database and user for EDS
-- Run this as a PostgreSQL superuser (e.g., postgres)

-- Create user first
CREATE USER eds_user WITH PASSWORD 'eds_password';

-- Grant user ability to create databases
ALTER USER eds_user CREATEDB;

-- Create database with eds_user as owner
CREATE DATABASE eds_database OWNER eds_user;

-- Grant all privileges on the database
GRANT ALL PRIVILEGES ON DATABASE eds_database TO eds_user;

-- Connect to the database and set up permissions
\c eds_database;

-- Grant all permissions on the public schema
GRANT ALL ON SCHEMA public TO eds_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO eds_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO eds_user;

-- Grant default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eds_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eds_user;

-- Make eds_user the owner of the public schema
ALTER SCHEMA public OWNER TO eds_user;

-- Optional: Create PostGIS extension if using spatial features
-- CREATE EXTENSION IF NOT EXISTS postgis;

-- Verify the setup
\l eds_database
\du eds_user

-- Show confirmation
SELECT 'Database and user created successfully!' as status;
@echo off
REM PostgreSQL Database Setup for EDS
REM This script helps set up the PostgreSQL database and user

echo ==============================================
echo EDS PostgreSQL Database Setup
echo ==============================================

echo.
echo This script will help you set up the PostgreSQL database for EDS.
echo You'll need the password for your PostgreSQL 'postgres' user.
echo.

REM Check if PostgreSQL is installed by looking for common installation paths
set PSQL_PATH=""
if exist "C:\Program Files\PostgreSQL\*\bin\psql.exe" (
    for /d %%i in ("C:\Program Files\PostgreSQL\*") do set PSQL_PATH="%%i\bin\psql.exe"
    goto found_psql
)

if exist "C:\Program Files (x86)\PostgreSQL\*\bin\psql.exe" (
    for /d %%i in ("C:\Program Files (x86)\PostgreSQL\*") do set PSQL_PATH="%%i\bin\psql.exe"
    goto found_psql
)

echo ERROR: PostgreSQL installation not found!
echo.
echo Please install PostgreSQL first:
echo 1. Download from: https://www.postgresql.org/download/windows/
echo 2. Install with default settings
echo 3. Remember the password you set for the 'postgres' user
echo 4. Restart this script after installation
echo.
pause
exit /b 1

:found_psql
echo Found PostgreSQL at: %PSQL_PATH%
echo.

echo Step 1: Create the EDS database and user
echo ----------------------------------------
echo.
echo You will be prompted for the PostgreSQL 'postgres' user password.
echo After entering the password, the script will:
echo - Create user 'eds_user' with password 'eds_password'  
echo - Create database 'eds_database'
echo - Grant all necessary permissions
echo.
pause

%PSQL_PATH% -U postgres -d postgres -f scripts\create_database.sql
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to create database and user!
    echo.
    echo Troubleshooting:
    echo 1. Make sure PostgreSQL service is running
    echo 2. Check that you entered the correct postgres password
    echo 3. Verify PostgreSQL is properly installed
    echo.
    pause
    exit /b 1
)

echo.
echo Step 2: Test the database connection
echo ------------------------------------
echo Testing connection with the new eds_user...

%PSQL_PATH% -U eds_user -d eds_database -c "SELECT 'Connection successful!' as status;"
if %errorlevel% neq 0 (
    echo.
    echo WARNING: Could not connect with eds_user
    echo This might be normal if you changed the default password.
    echo Make sure to update the password in your .env file.
    echo.
) else (
    echo.
    echo SUCCESS: Database connection test passed!
    echo.
)

echo ==============================================
echo Database Setup Complete!
echo ==============================================
echo.
echo Database Details:
echo - Host: localhost
echo - Port: 5432
echo - Database: eds_database
echo - Username: eds_user
echo - Password: eds_password
echo.
echo Next steps:
echo 1. If you changed the password, update it in the .env file
echo 2. Run: py scripts\setup_database.py
echo 3. Run: py scripts\initialize_tiles.py
echo 4. Run: py scripts\run_eds.py dashboard
echo.
pause
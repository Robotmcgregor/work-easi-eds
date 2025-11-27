@echo off
REM Windows batch script to set up the EDS system

echo ==============================================
echo EDS (Early Detection System) Setup Script
echo ==============================================

REM Check if Python is installed - try multiple commands
echo Checking for Python installation...
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto :python_found
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python3
    goto :python_found
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py
    goto :python_found
)

echo ERROR: Python is not installed or not in PATH
echo.
echo Please install Python 3.8 or later:
echo 1. Download from https://www.python.org/downloads/
echo 2. Or install from Microsoft Store
echo 3. Make sure to check "Add Python to PATH" during installation
echo.
echo After installation, close and reopen this terminal and try again.
pause
exit /b 1

:python_found

echo Python found. Checking version...
%PYTHON_CMD% -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"

REM Check Python version is 3.8+
%PYTHON_CMD% -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.8 or later is required
    %PYTHON_CMD% -c "import sys; print(f'Found Python {sys.version_info.major}.{sys.version_info.minor}, but need 3.8+')"
    pause
    exit /b 1
)

REM Check if pip is available - try multiple methods
echo Checking for pip...
%PYTHON_CMD% -m pip --version >nul 2>&1
if %errorlevel% equ 0 (
    set PIP_CMD=%PYTHON_CMD% -m pip
    goto :pip_found
)

pip --version >nul 2>&1
if %errorlevel% equ 0 (
    set PIP_CMD=pip
    goto :pip_found
)

echo ERROR: pip is not available
echo Please ensure pip is installed with Python
echo Try running: %PYTHON_CMD% -m ensurepip --upgrade
pause
exit /b 1

:pip_found

echo Installing Python dependencies...
%PIP_CMD% install -r requirements-py312.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    echo.
    echo Troubleshooting tips:
    echo 1. Try running as Administrator
    echo 2. Try: %PIP_CMD% install --user -r requirements-py312.txt
    echo 3. Check your internet connection
    pause
    exit /b 1
)

echo.
echo Dependencies installed successfully!

REM Create .env file if it doesn't exist
if not exist .env (
    echo Creating .env file from template...
    copy .env.example .env
    echo.
    echo IMPORTANT: Please edit the .env file to configure your database settings
    echo The default settings use PostgreSQL with:
    echo   - Host: localhost
    echo   - Port: 5432
    echo   - Database: eds_database
    echo   - Username: eds_user
    echo   - Password: eds_password
    echo.
) else (
    echo .env file already exists - skipping creation
)

REM Create necessary directories
if not exist "data" mkdir data
if not exist "data\processing_results" mkdir data\processing_results
if not exist "data\cache" mkdir data\cache
if not exist "logs" mkdir logs

echo.
echo ==============================================
echo Setup Complete!
echo ==============================================
echo.
echo Next steps:
echo 1. Edit the .env file to configure your database connection
echo 2. Set up your PostgreSQL database (create database and user)
echo 3. Run: %PYTHON_CMD% scripts\setup_database.py
echo 4. Run: %PYTHON_CMD% scripts\initialize_tiles.py
echo 5. Start the dashboard: %PYTHON_CMD% scripts\run_eds.py dashboard
echo.
echo For help with any step, see the README.md file
echo.
pause
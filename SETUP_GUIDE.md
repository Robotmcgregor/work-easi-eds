# EDS Setup Guide for Windows

## Prerequisites Installation

### Step 1: Install Python
Since Python is not currently installed on your system, you'll need to install it first:

**Option A: Install from Microsoft Store (Recommended)**
1. Open Microsoft Store
2. Search for "Python 3.11" or "Python 3.12"
3. Install the latest version

**Option B: Install from Python.org**
1. Go to https://www.python.org/downloads/
2. Download Python 3.11 or 3.12 for Windows
3. Run the installer
4. **IMPORTANT**: Check "Add Python to PATH" during installation

**Option C: Install using Windows Package Manager (if available)**
```powershell
winget install Python.Python.3.12
```

### Step 2: Verify Python Installation
After installation, close and reopen PowerShell, then test:

```powershell
# Try these commands in order:
python --version
# or
python3 --version
# or  
py --version
```

One of these should work and show Python 3.8+ version.

### Step 3: Verify pip Installation
```powershell
# Try these commands:
pip --version
# or
python -m pip --version
# or
py -m pip --version
```

## EDS System Setup

Once Python is installed, follow these steps:

### 1. Install Dependencies
```powershell
# For Python 3.12, use the compatible requirements file:
py -m pip install -r requirements-py312.txt
# or if you have an older Python version:
py -m pip install -r requirements.txt
```

**Note**: If you're using Python 3.12, use `requirements-py312.txt` as it contains packages compatible with the newer Python version.

### 2. Install PostgreSQL Database
You'll need PostgreSQL for the database:

**Option A: PostgreSQL Official Installer**
1. Download from https://www.postgresql.org/download/windows/
2. Install with default settings
3. Remember the password you set for the 'postgres' user

**Option B: Using chocolatey (if installed)**
```powershell
choco install postgresql
```

### 3. Set up Database
1. Copy the environment template:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit the `.env` file with your database settings:
   - Update `DB_PASSWORD` to match your PostgreSQL password
   - Adjust other database settings if needed

3. Create the database:
   ```sql
   # Connect to PostgreSQL as postgres user and run:
   # scripts/create_database.sql
   ```

### 4. Initialize the EDS System
```powershell
# Set up database tables
python scripts/setup_database.py

# Initialize Australian tile grid
python scripts/initialize_tiles.py

# Start the dashboard
python scripts/run_eds.py dashboard
```

## Troubleshooting Common Issues

### Python not found after installation
1. Close and reopen PowerShell
2. Try `py` instead of `python`
3. Check if Python is in your PATH:
   ```powershell
   $env:PATH -split ';' | Select-String -Pattern "Python"
   ```

### pip not working
1. Try `python -m pip` instead of just `pip`
2. Upgrade pip: `python -m pip install --upgrade pip`

### Permission errors during installation
1. Run PowerShell as Administrator
2. Or use `--user` flag: `pip install --user -r requirements.txt`

### PostgreSQL connection issues
1. Make sure PostgreSQL service is running
2. Check the connection details in your `.env` file
3. Test connection:
   ```powershell
   # Install psql client and test:
   psql -h localhost -U eds_user -d eds_database
   ```

## Quick Start (After Prerequisites)

```powershell
# 1. Install dependencies (for Python 3.12)
py -m pip install -r requirements-py312.txt

# 2. Set up environment
Copy-Item .env.example .env
# Edit .env file with your database password

# 3. Initialize system
py scripts/setup_database.py
py scripts/initialize_tiles.py

# 4. Start dashboard
py scripts/run_eds.py dashboard
```

The dashboard will be available at: http://localhost:8050

## System Architecture

```
EDS System Components:
├── Database (PostgreSQL)
│   ├── 300+ Landsat tiles covering Australia
│   ├── Processing job tracking
│   ├── Detection alerts storage
│   └── System status monitoring
├── Processing Pipeline
│   ├── Single tile processing
│   ├── Batch processing
│   ├── Time-based processing (since last run)
│   └── Automated scheduling
├── Web Dashboard
│   ├── Tile status visualization
│   ├── Processing controls
│   ├── Alert management
│   └── System monitoring
└── Configuration Management
    ├── Environment-based settings
    ├── Database configuration
    └── Processing parameters
```

## Next Steps

1. **Install Python and PostgreSQL** (see steps above)
2. **Integrate your EDS algorithms** in `src/processing/pipeline.py`
3. **Configure data sources** for Landsat imagery access
4. **Set up automated processing** schedule
5. **Deploy to production** environment

For detailed technical documentation, see the code comments and docstrings in each module.
#!/bin/bash
# Linux/macOS setup script for the EDS system

echo "=============================================="
echo "EDS (Early Detection System) Setup Script"
echo "=============================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8 or later and try again"
    exit 1
fi

echo "Python found. Checking version..."
python3 -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"

# Check Python version
python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"
if [ $? -ne 0 ]; then
    echo "ERROR: Python 3.8 or later is required"
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "ERROR: pip3 is not available"
    echo "Please ensure pip is installed with Python"
    exit 1
fi

echo "Installing Python dependencies..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

echo ""
echo "Dependencies installed successfully!"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Please edit the .env file to configure your database settings"
    echo "The default settings use PostgreSQL with:"
    echo "  - Host: localhost"
    echo "  - Port: 5432"
    echo "  - Database: eds_database"
    echo "  - Username: eds_user"
    echo "  - Password: eds_password"
    echo ""
else
    echo ".env file already exists - skipping creation"
fi

# Create necessary directories
mkdir -p data/processing_results
mkdir -p data/cache
mkdir -p logs

echo ""
echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Edit the .env file to configure your database connection"
echo "2. Set up your PostgreSQL database (create database and user)"
echo "3. Run: python3 scripts/setup_database.py"
echo "4. Run: python3 scripts/initialize_tiles.py"
echo "5. Start the dashboard: python3 scripts/run_eds.py dashboard"
echo ""
echo "For help with any step, see the README.md file"
echo ""
# EDS - Early Detection System for Land Clearing

A comprehensive pipeline system for monitoring and detecting land clearing activities across Australia using Landsat satellite data.

## Overview

This system provides:
- Automated processing of Landsat tiles across Australia
- PostgreSQL database for tracking processing status and results
- Web-based dashboard for monitoring and control
- Flexible processing pipeline for individual tiles or batch operations
- Early detection capabilities for land clearing activities

## Architecture

```
src/
├── config/          # Configuration files and settings
├── database/        # Database models and connection management
├── processing/      # Core EDS processing pipeline
├── dashboard/       # Web dashboard interface
└── utils/          # Utility functions and helpers

scripts/            # Setup and deployment scripts
data/              # Data storage and processing results
logs/              # Application logs
```

## Features

- **Tile Management**: Track all Landsat tiles across Australia
- **Processing Pipeline**: Run EDS algorithms on individual or multiple tiles
- **Status Tracking**: Monitor last processing time and current status
- **Time-based Processing**: Process only tiles that need updates since last run
- **Dashboard Interface**: Visual monitoring and control interface
- **Database Integration**: PostgreSQL for persistent data storage

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up the database:
   ```bash
   python scripts/setup_database.py
   ```

3. Initialize tile grid:
   ```bash
   python scripts/initialize_tiles.py
   ```

4. Start the dashboard:
   ```bash
   python src/dashboard/app.py
   ```

## Configuration

Copy `.env.example` to `.env` and configure your database and processing settings.

## License

Government of Australia - Department of Climate Change, Energy, the Environment and Water
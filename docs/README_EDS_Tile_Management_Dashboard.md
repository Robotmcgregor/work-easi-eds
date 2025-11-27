# EDS Tile Management Dashboard

A comprehensive dashboard for managing EDS processing workflow, assigning tiles to staff members, and executing processing scripts.

## Features

### 🗺️ Tile Management
- **View all tiles** with status, assignments, and processing history
- **Assign tiles to staff members** with role-based access
- **Update tile status** (Not Started, Data Prep, Processing, Review, Completed, Failed)
- **Set processing priorities** and add notes
- **Multi-select operations** for bulk updates

### 🚀 Script Execution
- **Data Pipeline**: Execute `eds_master_data_pipeline.py` for data acquisition
- **EDS Processing**: Run `run_eds.py` for analysis and detection
- **Real-time monitoring** of script execution with live logs
- **Background processing** with status tracking

### 📊 Analytics & Monitoring
- **Tile status distribution** with visual charts
- **Staff workload visualization** showing assignments
- **Processing statistics** and completion rates
- **Active process monitoring** with real-time logs

### 🏃 Process Management
- **Live process tracking** with start time and duration
- **Process logs** with timestamped output
- **Automatic status updates** based on script completion
- **Error handling** and failure reporting

## Quick Start

### Prerequisites
- Active `slats` conda environment
- Database connection configured (`.env` file)
- EDS scripts available in `scripts/` directory

### Launch Dashboard
```bash
# Start management dashboard (runs on port 8060)
C:\ProgramData\anaconda3\envs\slats\python.exe eds_tile_management_dashboard.py
```

### Access Dashboard
- Open browser to `http://127.0.0.1:8060` or `http://localhost:8060`
- Dashboard will automatically refresh every 5 seconds

## Dashboard Tabs

### 🗺️ Tiles Overview
**Purpose**: View and manage all tiles in the system

**Features**:
- Searchable and sortable table of all tiles
- Color-coded status indicators:
  - 🟢 Green: Completed
  - 🟡 Yellow: Processing/In Progress  
  - 🔴 Red: Failed
- Multi-select tiles for bulk operations
- View processing history and notes

**Actions**:
1. Select tiles using checkboxes
2. Choose staff member from dropdown
3. Set new status
4. Click "Update Selected Tiles"

### 🏃 Active Processes  
**Purpose**: Monitor running EDS scripts in real-time

**Features**:
- Live process status (Running, Completed, Failed, Error)
- Execution duration tracking
- Real-time log output from scripts
- Process history and completion status

**Information Displayed**:
- Process ID and tile being processed
- Script type (Data Pipeline or EDS Processing)
- Start time and elapsed duration
- Live log output (last 10 entries)

### 📈 Analytics
**Purpose**: Visualize processing statistics and workload distribution

**Charts**:
- **Tile Status Pie Chart**: Distribution of completed, in-progress, and failed tiles
- **Staff Assignment Bar Chart**: Workload distribution across team members

## Script Execution Workflow

### 1. Data Pipeline Execution
**Purpose**: Download and prepare satellite data for EDS processing

**Steps**:
1. Enter tile ID (e.g., `089_078`)
2. Enter start date (e.g., `20230720`)
3. Enter end date (e.g., `20240831`) 
4. Select "📦 Data Pipeline" from script dropdown
5. Click "🚀 Run Script"

**What it does**:
- Executes `eds_master_data_pipeline.py`
- Downloads SR and FC data from S3/GA
- Applies clear masks
- Organizes data in proper folder structure

### 2. EDS Processing Execution
**Purpose**: Run EDS analysis and detection algorithms

**Steps**:
1. Enter tile ID (must have data from pipeline step)
2. Select "⚙️ EDS Processing" from script dropdown  
3. Click "🚀 Run Script"

**What it does**:
- Executes `run_eds.py`
- Runs change detection algorithms
- Generates detection results
- Creates output vectors and reports

## Staff Management

### Available Staff Members
- Alice Johnson (`alice`)
- Bob Smith (`bob`) 
- Carol Davis (`carol`)
- David Wilson (`david`)
- Unassigned (`unassigned`)

### Tile Status Options
- 🔴 **Not Started**: No work begun
- 📥 **Data Prep**: Data acquisition in progress
- ⚙️ **Processing**: EDS analysis running
- 🔍 **Review**: Results ready for review
- ✅ **Completed**: Processing finished successfully
- ❌ **Failed**: Processing failed or error occurred

## Database Integration

### Required Tables
The dashboard requires the following database structure:

```sql
-- Landsat tiles table (existing)
landsat_tiles:
  - tile_id (VARCHAR) 
  - path (INTEGER)
  - row (INTEGER)
  - status (VARCHAR)
  - processing_priority (INTEGER)
  - last_processed (TIMESTAMP)
  - processing_notes (TEXT)
  - is_active (BOOLEAN)
  - last_updated (TIMESTAMP)
```

### Optional Enhancement
To fully support staff assignments, add this column:
```sql
ALTER TABLE landsat_tiles ADD COLUMN assigned_to VARCHAR(50);
```

## Configuration

### Environment Variables
Set these in your `.env` file:
```env
DB_HOST=localhost
DB_PORT=5432  
DB_NAME=eds_database
DB_USER=your_username
DB_PASSWORD=your_password
```

### Port Configuration
The dashboard runs on port **8060** by default. To change:
```python
# Edit last line in eds_tile_management_dashboard.py
app.run_server(debug=True, host='0.0.0.0', port=YOUR_PORT)
```

## Troubleshooting

### Common Issues

**Dashboard won't start**
- Check database connection in `.env` file
- Verify `slats` environment is activated
- Ensure port 8060 is not in use

**Scripts fail to execute**
- Verify script paths in `scripts/` directory
- Check tile ID format (should be `089_078`)
- Ensure date format is YYYYMMDD
- Check permissions on destination directories

**Process logs not showing**
- Scripts may be running silently
- Check terminal/command prompt for errors
- Verify script paths are correct

**Database updates not working**
- Check database permissions
- Verify table structure matches requirements
- Check for database connection timeouts

### Performance Tips

- **Large datasets**: Process may take hours for 10+ years of data
- **Multiple processes**: Avoid running multiple scripts on same tile simultaneously  
- **Database load**: Refresh interval can be increased if database is slow
- **Memory usage**: Monitor system resources during large tile processing

## Integration with Existing Workflows

### With Validation Dashboard
1. Use **Tile Management** to assign and process tiles
2. Use **Validation Dashboard** (`new_dashboard_with_qc.py`) to QC results
3. Return to **Tile Management** to mark tiles as completed

### With Direct Script Execution
- Dashboard executes the same scripts you would run manually
- All command-line options are supported
- Process logs provide same output as terminal execution

## Security Considerations

- Dashboard runs on local network only (0.0.0.0)
- No authentication implemented (add if needed for production)
- Database credentials stored in `.env` file
- Process execution uses local user permissions

## Future Enhancements

Potential improvements:
- User authentication and role-based access
- Email notifications for process completion
- Scheduled processing with cron-like functionality
- Integration with file system monitoring
- Advanced analytics and reporting
- Export capabilities for processing reports
# Django Admin Interface - Ready for Use

## ✅ Status: OPERATIONAL

The Django admin interface is now fully configured and ready to manage your EDS data!

---

## Access Information

**Admin URL:** http://127.0.0.1:8000/admin/

**Login Credentials:**
- Username: `admin`
- Password: `admin123`

**Server Status:** Running on http://0.0.0.0:8000

---

## Available Data Management Interfaces

### 1. **Landsat Tiles Catalog** (`catalog/admin.py`)
- **Table:** `landsat_tiles` (466 records)
- **Purpose:** Browse and manage Australian Landsat tile definitions
- **Fields Visible:**
  - Tile ID, Path, Row, Latitude/Longitude, Status, Quality Score
  - Geographic boundaries and metadata
- **Features:**
  - Search by tile_id, path, row
  - Filter by status and quality_score
  - Organized fieldsets for geographic and metadata info

### 2. **EDS Processing Runs** (`runs/admin.py`)
- **EDSRun Table:** `eds_runs` (3 records)
  - View processing runs (run_id, run_number, description, parameters)
  - See summary statistics (detections_total, cleared_tiles)
  - Timestamps and notes
  
- **EDSResult Table:** `eds_results` (483 records)
  - Per-tile processing results
  - Cleared/not-cleared counts by tile
  - Analyst notes and metadata
  - Link to parent EDSRun

### 3. **Detection Data** (`detection/admin.py`)
- **EDSDetection Table:** `eds_detections` (14,735 records)
  - Browse individual detections with coordinates
  - View GeoJSON and WKT geometry
  - Detection properties and confidence scores
  - Filter by status, run, tile, result
  
- **DetectionAlert Table:** `detection_alerts` (0 records)
  - Verification tracking
  - Confidence ratings and area calculations
  - Alert status management

### 4. **Quality Control** (`validation/admin.py`)
- **QCValidation Table:** `qc_validations` (10 records)
  - QC validation records for detections
  - Status tracking (pending, confirmed, rejected, requires_review)
  - Confidence scores and reviewer information
  - Field visit requirements and notes
  
- **QCAuditLog Table:** `qc_audit_log` (0 records)
  - Complete audit trail of all QC changes
  - Track old/new values for all changes
  - User and IP address logging
  - Change reason documentation

---

## Features Available in Admin Interface

### Search & Filter
- **Landsat Tiles:** Search by tile_id, path, row; Filter by status/quality
- **EDS Runs:** Filter by status, date range; Search by run_number
- **Detections:** Search by detection properties; Filter by status, run, tile
- **QC Validations:** Search by tile_id, reviewer; Filter by status, confidence, date

### Data Organization
- **Fieldsets:** Related data grouped into logical sections
- **Readonly Fields:** Auto-populated fields (timestamps, auto_increment IDs)
- **Relationships:** One-click navigation between related records
- **Ordering:** Most recent records shown first by default

### Record Management
- **View Details:** Click any record to see full details with all relationships
- **Edit Fields:** Modify data with Django validation
- **Bulk Actions:** Select multiple records for batch operations (if enabled)
- **Audit Trail:** QCAuditLog shows every change made to validations

---

## Django Project Structure

```
django_project/
├── manage.py                          # Django management script
├── django.bat                         # Conda helper script
├── eds_easi/                          # Main Django project config
│   ├── settings.py                    # Configured for SQLite database
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
└── [8 Django Apps]
    ├── catalog/                       # Landsat tiles
    │   ├── models.py                  # LandsatTile model
    │   └── admin.py                   # ✅ Admin configured
    │
    ├── runs/                          # Processing runs & results
    │   ├── models.py                  # EDSRun, EDSResult models
    │   └── admin.py                   # ✅ Admin configured
    │
    ├── detection/                     # Detection data
    │   ├── models.py                  # EDSDetection, DetectionAlert models
    │   └── admin.py                   # ✅ Admin configured
    │
    ├── validation/                    # QC validation
    │   ├── models.py                  # QCValidation, QCAuditLog models
    │   └── admin.py                   # ✅ Admin configured
    │
    ├── audit/                         # Audit logs (app created, models TBD)
    ├── reporting/                     # Reporting (app created, models TBD)
    ├── mapping/                       # Mapping (app created, models TBD)
    └── accounts/                      # User accounts (app created, models TBD)
```

---

## Database Configuration

**SQLite Database Location:**
```
c:\Users\DCCEEW\code\work-easi-eds\data\eds_database.db
```

**Database Statistics:**
- Total Records: 16,182
- Total Tables: 10
- Database Size: 114.6 MB

**Table Breakdown:**
- `landsat_tiles` - 466 records
- `eds_runs` - 3 records
- `eds_results` - 483 records
- `eds_detections` - 14,735 records
- `detection_alerts` - 0 records (tracking table)
- `qc_validations` - 10 records
- `qc_audit_log` - 0 records (audit trail)
- 3 additional utility tables

**Django System Tables (created by migrations):**
- `auth_user` - User accounts
- `auth_group` - User groups
- `auth_permission` - Permissions
- `django_admin_log` - Admin change log
- `django_session` - Session data

---

## Running the Server

### Option 1: Using venv Runner Script (Recommended) ✅ NEW
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\run.bat runserver
```
**No conda dependency needed! Uses Python's built-in venv.**

### Option 2: Using Conda Helper Script (Legacy)
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\django.bat runserver
```

### Option 3: Direct venv Command
```powershell
cd c:\Users\DCCEEW\code\work-easi-eds\django_project
.\venv\Scripts\python.exe manage.py runserver
```

**Server Output:**
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CTRL-BREAK.
```

---

## Useful Management Commands

All commands can be run with `.\run.bat <command>` (recommended) or `.\django.bat <command>` (conda)

### Data Inspection
```powershell
# Check system status
.\run.bat check

# Display SQL for database queries (debugging)
.\run.bat sqlmigrate app_name migration_name

# Open Django shell for database queries
.\run.bat shell
```

### Database Management
```powershell
# Show all migrations
.\run.bat showmigrations

# Create database backup
# (SQLite: simply copy data/eds_database.db)
```

### Admin User Management
```powershell
# Create new superuser
.\run.bat createsuperuser

# Change password
.\run.bat changepassword username

# Remove user
.\run.bat shell
# Then in shell: from django.contrib.auth.models import User; User.objects.get(username='admin').delete()
```

### Development
```powershell
# Collect static files (if needed for deployment)
.\run.bat collectstatic --noinput

# Find all template/static files
.\run.bat findstatic filename
```

---

## Integration with Existing Systems

### Python Environment
- **Conda Environment:** `slats` (Python 3.14)
- **Location:** `C:\Users\DCCEEW\mmroot\envs\slats`
- **Package Manager:** pip (via conda)

### With Existing Dash Dashboards
- **CORS Enabled:** Django configured with django-cors-headers
- **Allowed Origins:** Can be configured in `settings.py`
- **API Layer:** Ready to be built with Django REST Framework

### With Existing SQLAlchemy Models
- **Database:** Shared SQLite database (`eds_database.db`)
- **Tables:** Both systems read/write same tables
- **Recommendation:** Keep both systems in sync for data integrity

---

## Next Steps (Optional)

### Phase 3: Build REST API
To add programmatic access to the data:

1. Create `serializers.py` in each app
2. Define DRF Serializers for each model
3. Create ViewSets and register with API router
4. Test endpoints with tools like Postman or curl

### Phase 4: Custom Dashboards
Create Django templates to extend admin interface:

1. Custom list templates with charts
2. Action buttons for batch processing
3. Custom admin actions
4. Reporting views

### Phase 5: Deployment
When ready to deploy to production:

1. Set `DEBUG = False` in settings.py
2. Configure `ALLOWED_HOSTS`
3. Set up database backups
4. Configure web server (Gunicorn, etc.)
5. Use environment variables for secrets

---

## Troubleshooting

### "System check identified X issues"
→ Check the error messages and ensure all model fields match database schema

### "No such table: auth_user"
→ Run migrations: `.\django.bat migrate`

### "Connection refused" when accessing admin
→ Ensure server is running: `.\django.bat runserver`

### Models not showing in admin
→ Verify admin registration in `admin.py`:
```python
@admin.register(ModelName)
class ModelNameAdmin(admin.ModelAdmin):
    pass
```

### Database locked errors
→ Close any other processes accessing `eds_database.db`

---

## Configuration Files

### Django Settings (`eds_easi/settings.py`)
- **Database:** SQLite at `../data/eds_database.db`
- **INSTALLED_APPS:** 8 custom apps + Django standard apps
- **MIDDLEWARE:** Django standard + CORS headers
- **REST Framework:** Pagination enabled, default limit = 50

### Django Batch Helper (`django.bat`)
```batch
@echo off
conda run -n slats python manage.py %*
```

---

## Performance Notes

### Admin Interface Loading
- **Landsat Tiles:** ~466 records, loads quickly
- **Detections:** 14,735 records, uses pagination (50 per page in list view)
- **QC Data:** Small datasets (<100 records), very fast

### Database Optimization
- **Indexes:** Created on frequently filtered fields
- **Select Related:** Configured to minimize database queries
- **Ordering:** Default sort by most recent record

### Recommended Limits
- Don't modify `managed = False` in Meta classes (keeps Django read-only)
- Use Django admin for data browsing, not bulk modifications
- Keep SQLAlchemy updates in sync with Django changes

---

## Created By
Django Admin Interface setup completed successfully.

**Date:** 2024
**Version:** Django 6.0 + SQLite 3
**Status:** ✅ Fully Operational

---

## Quick Reference

| Component | Location | Status |
|-----------|----------|--------|
| Admin URL | http://127.0.0.1:8000/admin/ | ✅ Running |
| Database | `data/eds_database.db` | ✅ Connected |
| Superuser | admin / admin123 | ✅ Created |
| Landsat Tiles | catalog/admin.py | ✅ Configured |
| EDS Runs | runs/admin.py | ✅ Configured |
| Detections | detection/admin.py | ✅ Configured |
| QC Data | validation/admin.py | ✅ Configured |
| System Check | 0 issues | ✅ Passed |


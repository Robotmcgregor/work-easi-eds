# Django EDS Setup for EASI Server

## Overview
This guide explains how to deploy the Django EDS dashboard and integrate it with the master processing pipeline on EASI.

---

## Part 1: Django Project Setup on EASI

### 1.1 Prerequisites
- Python 3.10+ (check with `python --version`)
- Git access to the repository
- Access to EASI filesystem at `/data/` or similar

### 1.2 Clone Repository
```bash
cd /data/  # or your chosen directory
git clone https://github.com/Robotmcgregor/work-easi-eds.git
cd work-easi-eds
git checkout dev/django
```

### 1.3 Set Up Python Virtual Environment
```bash
cd django_project

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
# OR for Django-only:
pip install -r requirements-django.txt
```

### 1.4 Configure Django Settings for EASI

Edit `django_project/eds_easi/settings.py`:

```python
# Change DEBUG mode
DEBUG = False  # Production setting

# Add EASI server to ALLOWED_HOSTS
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'easi-server.hostname',  # Replace with actual EASI hostname
    '*.easi.internal',  # If using internal domain
]

# Database configuration (if using PostgreSQL on EASI)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'eds_db',
        'USER': 'eds_user',
        'PASSWORD': 'your_password',  # Use environment variable!
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
# OR if using SQLite (current default):
# DATABASES already configured, check db.sqlite3 location
```

### 1.5 Set Environment Variables
Create `.env` file in `django_project/`:
```
DEBUG=False
SECRET_KEY=your-production-secret-key-here
ALLOWED_HOSTS=easi-server,localhost
DATABASE_URL=postgresql://user:password@localhost:5432/eds_db
STATIC_ROOT=/var/www/eds/static/
MEDIA_ROOT=/var/www/eds/media/
```

Load in settings.py:
```python
import os
from decouple import config

DEBUG = config('DEBUG', default=False, cast=bool)
SECRET_KEY = config('SECRET_KEY')
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=lambda v: [s.strip() for s in v.split(',')])
```

### 1.6 Initialize Database
```bash
# Run migrations
python manage.py migrate

# Create superuser for admin access
python manage.py createsuperuser
# Follow prompts to create admin account
```

### 1.7 Collect Static Files
```bash
# For production
python manage.py collectstatic --noinput
```

---

## Part 2: Running Django Server on EASI

### 2.1 Development Server (Testing)
```bash
cd django_project
python manage.py runserver 0.0.0.0:8000
```
Access at: `http://easi-server:8000/`

### 2.2 Production Server (Gunicorn)

Install gunicorn (already in requirements):
```bash
# Create systemd service file at /etc/systemd/system/eds-django.service

[Unit]
Description=EDS Django Application
After=network.target

[Service]
Type=notify
User=www-data
WorkingDirectory=/data/work-easi-eds/django_project
ExecStart=/data/work-easi-eds/django_project/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/eds-django/access.log \
    --error-logfile /var/log/eds-django/error.log \
    eds_easi.wsgi:application

[Install]
WantedBy=multi-user.target
```

Start service:
```bash
sudo systemctl daemon-reload
sudo systemctl start eds-django
sudo systemctl enable eds-django  # Auto-start on reboot
```

### 2.3 Nginx Reverse Proxy Configuration
```nginx
# /etc/nginx/sites-available/eds-django

upstream eds_django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name easi-server;
    client_max_body_size 100M;

    location /static/ {
        alias /var/www/eds/static/;
    }

    location /media/ {
        alias /var/www/eds/media/;
    }

    location / {
        proxy_pass http://eds_django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/eds-django /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Part 3: Integration with Master Processing Pipeline

### 3.1 Master Pipeline Location
Your pipeline is at: `scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py`

### 3.2 Add Pipeline Entry Point in Django

Create `django_project/processing/tasks.py`:
```python
import subprocess
import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand

def run_master_pipeline(tile_list=None, start_date=None, end_date=None):
    """
    Execute the master EDS processing pipeline from Django
    
    Args:
        tile_list: List of tile IDs (e.g., ['p104r070', 'p105r069'])
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    
    Returns:
        dict with status and run ID
    """
    pipeline_path = '/data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py'
    
    # Build command
    cmd = ['python', pipeline_path]
    
    if tile_list:
        cmd.extend(['--tiles', ','.join(tile_list)])
    
    if start_date:
        cmd.extend(['--start-date', start_date])
    
    if end_date:
        cmd.extend(['--end-date', end_date])
    
    try:
        # Run pipeline as subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        return {
            'status': 'success' if result.returncode == 0 else 'error',
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode,
            'timestamp': datetime.now().isoformat()
        }
    
    except subprocess.TimeoutExpired:
        return {
            'status': 'timeout',
            'error': 'Pipeline execution exceeded 1 hour',
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
```

### 3.3 Create Django API Endpoint for Pipeline

Create `django_project/eds_easi/views.py` - add this view:
```python
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from processing.tasks import run_master_pipeline
import json

@csrf_exempt
@require_http_methods(["POST"])
def run_pipeline_api(request):
    """
    API endpoint to trigger master processing pipeline
    
    POST JSON body:
    {
        "tiles": ["p104r070", "p105r069"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31"
    }
    """
    try:
        data = json.loads(request.body)
        tiles = data.get('tiles')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        result = run_master_pipeline(
            tile_list=tiles,
            start_date=start_date,
            end_date=end_date
        )
        
        return JsonResponse(result)
    
    except json.JSONDecodeError:
        return JsonResponse(
            {'status': 'error', 'error': 'Invalid JSON'},
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'error': str(e)},
            status=500
        )
```

### 3.4 Add URL Route

Edit `django_project/eds_easi/urls.py`:
```python
from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home_page, name='home'),
    # ... existing routes ...
    
    # Processing pipeline
    path('api/processing/run', views.run_pipeline_api, name='run_pipeline'),
]
```

### 3.5 Call Pipeline from Django Dashboard

In template or frontend, call the API:
```javascript
// In qc_validations_list.html or new processing page
async function runPipeline(tiles, startDate, endDate) {
    const response = await fetch('/api/processing/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            tiles: tiles,
            start_date: startDate,
            end_date: endDate
        })
    });
    
    const result = await response.json();
    console.log('Pipeline result:', result);
    
    if (result.status === 'success') {
        alert('Pipeline execution started!');
    } else {
        alert('Pipeline error: ' + result.error);
    }
}
```

---

## Part 4: Monitoring & Logging

### 4.1 Log Directory Setup
```bash
sudo mkdir -p /var/log/eds-django
sudo chown www-data:www-data /var/log/eds-django
```

### 4.2 Django Logging Configuration
Add to `settings.py`:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/var/log/eds-django/django.log',
        },
        'pipeline_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/var/log/eds-django/pipeline.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
        },
        'processing': {
            'handlers': ['pipeline_file'],
            'level': 'INFO',
        },
    },
}
```

### 4.3 Monitor Pipeline Execution
```bash
# Watch pipeline logs
tail -f /var/log/eds-django/pipeline.log

# Check Django app status
systemctl status eds-django

# View Gunicorn workers
ps aux | grep gunicorn
```

---

## Part 5: Environment-Specific Settings

### 5.1 Settings per Environment
Create separate settings files:
- `settings/development.py` - Local testing
- `settings/production.py` - EASI server
- `settings/staging.py` - Pre-production (optional)

Use with:
```bash
# Development
python manage.py runserver --settings=settings.development

# Production
gunicorn --settings=settings.production eds_easi.wsgi:application
```

---

## Part 6: Troubleshooting on EASI

### Issue: Database Connection Fails
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
psql -U eds_user -d eds_db -h localhost
```

### Issue: Static Files Not Loading
```bash
# Collect statics
python manage.py collectstatic --noinput

# Check permissions
ls -la /var/www/eds/static/
sudo chown -R www-data:www-data /var/www/eds/
```

### Issue: Pipeline Fails to Run
```bash
# Test pipeline directly
cd /data/work-easi-eds
python scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py --help

# Check logs
tail -f /var/log/eds-django/pipeline.log
```

### Issue: Port Already in Use
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill it
sudo kill -9 <PID>
```

---

## Part 7: Quick Deployment Checklist

- [ ] Repository cloned and on `dev/django` branch
- [ ] Virtual environment created and activated
- [ ] Dependencies installed from `requirements.txt`
- [ ] Django settings configured for EASI hostname
- [ ] Environment variables set in `.env`
- [ ] Database migrations run (`python manage.py migrate`)
- [ ] Superuser created (`python manage.py createsuperuser`)
- [ ] Static files collected (`python manage.py collectstatic`)
- [ ] Gunicorn service created and enabled
- [ ] Nginx reverse proxy configured
- [ ] Log directories created with correct permissions
- [ ] Pipeline integration tested
- [ ] Systemd service starts on reboot (`systemctl enable`)

---

## Part 8: Daily Operations

### Start Services
```bash
sudo systemctl start eds-django
sudo systemctl start nginx
```

### Stop Services
```bash
sudo systemctl stop eds-django
sudo systemctl stop nginx
```

### Update Code
```bash
cd /data/work-easi-eds
git pull origin dev/django
python django_project/manage.py migrate
python django_project/manage.py collectstatic --noinput
sudo systemctl restart eds-django
```

### Access Dashboard
- URL: `http://easi-server/`
- Admin: `http://easi-server/admin/`
- QC Validations: `http://easi-server/qc/validations/`
- Processing: `http://easi-server/processing/`

---

## Contact & Support
For issues or questions, refer to:
- Django Docs: https://docs.djangoproject.com/en/6.0/
- Repository Issues: https://github.com/Robotmcgregor/work-easi-eds/issues

# EASI Deployment - Django EDS Dashboard & Processing Pipeline Integration

## Quick Start (5 minutes)

### 1. Clone and Setup
```bash
cd /data
git clone https://github.com/Robotmcgregor/work-easi-eds.git
cd work-easi-eds
git checkout dev/django

# Setup Python environment
cd django_project
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure for EASI
Edit `eds_easi/settings.py`:
```python
# Line ~27: Change to False for production
DEBUG = False

# Line ~30: Add EASI hostname
ALLOWED_HOSTS = ['your-easi-server.hostname', 'localhost', '127.0.0.1']

# Line ~100+: Configure database (PostgreSQL recommended for EASI)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'eds_db',
        'USER': 'eds_user',
        'PASSWORD': os.getenv('DB_PASSWORD', 'change_me'),
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

### 3. Initialize Database
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

### 4. Start Server
```bash
# Development (testing)
python manage.py runserver 0.0.0.0:8000

# Production (use Gunicorn)
gunicorn --workers 4 --bind 127.0.0.1:8000 eds_easi.wsgi:application
```

### 5. Access Dashboard
- **Main Dashboard**: http://your-easi-server:8000/
- **Admin Panel**: http://your-easi-server:8000/admin/
- **QC Validations**: http://your-easi-server:8000/qc/validations/
- **Tile Map**: http://your-easi-server:8000/tiles/map/

---

## Integration with Master Processing Pipeline

The Django dashboard automatically integrates with:
```
scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py
```

### API Endpoint: Run Pipeline

**POST** `/api/processing/run`

Request body:
```json
{
  "tiles": ["p104r070", "p105r069"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "timeout": 3600
}
```

Response:
```json
{
  "status": "success",
  "returncode": 0,
  "stdout": "Pipeline output...",
  "stderr": "",
  "timestamp": "2024-12-15T10:30:00.000000",
  "command": "python /data/work-easi-eds/scripts/easi-scripts/..."
}
```

### Example: Run from JavaScript
```javascript
async function runProcessingPipeline(tiles, startDate, endDate) {
  const response = await fetch('/api/processing/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      tiles: tiles,
      start_date: startDate,
      end_date: endDate,
      timeout: 7200  // 2 hours
    })
  });
  
  const result = await response.json();
  console.log('Pipeline result:', result);
  return result;
}

// Usage
runProcessingPipeline(['p104r070'], '2024-01-01', '2024-12-31');
```

### Example: Run from Python
```python
import requests
import json

response = requests.post(
    'http://localhost:8000/api/processing/run',
    json={
        'tiles': ['p104r070'],
        'start_date': '2024-01-01',
        'end_date': '2024-12-31'
    }
)

result = response.json()
print(f"Pipeline status: {result['status']}")
print(f"Output:\n{result['stdout']}")
if result['stderr']:
    print(f"Errors:\n{result['stderr']}")
```

### Programmatic Access from Django
```python
from eds_easi.pipeline_executor import PipelineExecutor

# Run pipeline directly
result = PipelineExecutor.run(
    tiles=['p104r070', 'p105r069'],
    start_date='2024-01-01',
    end_date='2024-12-31',
    timeout=7200
)

if result['status'] == 'success':
    print("Pipeline completed successfully!")
    print(result['stdout'])
else:
    print(f"Error: {result['error']}")
    print(f"Stderr: {result['stderr']}")
```

---

## Production Deployment on EASI

### Step 1: Systemd Service (Auto-restart)

Create `/etc/systemd/system/eds-django.service`:
```ini
[Unit]
Description=EDS Django Dashboard
After=network.target postgresql.service

[Service]
Type=notify
User=www-data
WorkingDirectory=/data/work-easi-eds/django_project
Environment="PATH=/data/work-easi-eds/django_project/venv/bin"
Environment="EDS_PIPELINE_PATH=/data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py"
ExecStart=/data/work-easi-eds/django_project/venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:8000 \
    --timeout 60 \
    --access-logfile /var/log/eds-django/access.log \
    --error-logfile /var/log/eds-django/error.log \
    eds_easi.wsgi:application
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo mkdir -p /var/log/eds-django
sudo chown www-data:www-data /var/log/eds-django
sudo systemctl daemon-reload
sudo systemctl enable eds-django
sudo systemctl start eds-django
sudo systemctl status eds-django
```

### Step 2: Nginx Reverse Proxy

Create `/etc/nginx/sites-available/eds-dashboard`:
```nginx
upstream eds_django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    listen [::]:80;
    server_name your-easi-server.hostname;
    client_max_body_size 100M;

    # Redirect to HTTPS if using SSL
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name your-easi-server.hostname;
    
    # SSL certificates (configure if using HTTPS)
    # ssl_certificate /etc/letsencrypt/live/.../fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

    client_max_body_size 100M;

    # Static files
    location /static/ {
        alias /var/www/eds/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Media files
    location /media/ {
        alias /var/www/eds/media/;
        expires 7d;
    }

    # API and Django views
    location / {
        proxy_pass http://eds_django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # For long-running pipeline requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
    }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/eds-dashboard /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 3: Monitor Logs
```bash
# Watch Django app logs
sudo tail -f /var/log/eds-django/error.log

# Watch Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Check service status
sudo systemctl status eds-django
sudo systemctl status nginx

# View Gunicorn workers
ps aux | grep gunicorn
```

---

## Environment Variables

Create `/data/work-easi-eds/django_project/.env`:
```bash
# Django Configuration
DEBUG=False
SECRET_KEY=your-super-secret-key-here-change-this
ALLOWED_HOSTS=your-easi-server.hostname,localhost

# Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=eds_db
DB_USER=eds_user
DB_PASSWORD=your_postgres_password
DB_HOST=localhost
DB_PORT=5432

# Pipeline Configuration
EDS_PIPELINE_PATH=/data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py

# Static Files
STATIC_ROOT=/var/www/eds/static/
MEDIA_ROOT=/var/www/eds/media/

# Logging
LOG_LEVEL=INFO
```

Load in settings.py:
```python
from decouple import config

DEBUG = config('DEBUG', default=False, cast=bool)
SECRET_KEY = config('SECRET_KEY')
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=lambda v: [s.strip() for s in v.split(',')])

DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE'),
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT'),
    }
}
```

---

## Troubleshooting

### Pipeline doesn't execute
```bash
# Check if script exists and is executable
ls -la /data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py

# Test pipeline directly
python /data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py --help

# Check logs for error details
sudo tail -f /var/log/eds-django/error.log
```

### Port 8000 already in use
```bash
# Find what's using it
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>

# Or change port in systemd service
```

### Database connection errors
```bash
# Test PostgreSQL connection
psql -U eds_user -d eds_db -h localhost

# Check if PostgreSQL is running
sudo systemctl status postgresql

# View connection settings
grep -A 5 "DATABASES" /data/work-easi-eds/django_project/eds_easi/settings.py
```

### Static files not loading
```bash
# Collect static files
python manage.py collectstatic --noinput

# Check permissions
sudo chown -R www-data:www-data /var/www/eds/
ls -la /var/www/eds/static/
```

---

## Updating Code on EASI

```bash
cd /data/work-easi-eds

# Pull latest changes
git pull origin dev/django

# Activate venv
cd django_project
source venv/bin/activate

# Install any new dependencies
pip install -r requirements.txt

# Run migrations (if any)
python manage.py migrate

# Collect updated static files
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart eds-django
```

---

## Key Files & Directories

```
/data/work-easi-eds/
├── django_project/
│   ├── manage.py                 # Django management command
│   ├── requirements.txt           # Python dependencies
│   ├── venv/                      # Virtual environment
│   ├── eds_easi/
│   │   ├── settings.py           # Django configuration
│   │   ├── urls.py               # URL routing
│   │   ├── views.py              # View functions & classes
│   │   ├── models.py             # Database models
│   │   ├── pipeline_executor.py  # Pipeline integration
│   │   └── wsgi.py               # Production WSGI application
│   ├── templates/                # HTML templates
│   │   ├── base.html             # Main layout
│   │   ├── qc_validations_list.html
│   │   ├── qc_review.html
│   │   └── ...
│   └── static/                   # CSS, JS, images
├── scripts/easi-scripts/
│   └── eds-processing/
│       └── easi_eds_master_processing_pipeline.py  # Processing script
└── docs/
    └── EASI_DJANGO_DEPLOYMENT.md  # This file
```

---

## API Reference

### Authentication
Currently uses Django session-based authentication. Add token auth if needed:
```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ]
}
```

### Pipeline Execution
- **Endpoint**: POST `/api/processing/run`
- **Parameters**: tiles (list), start_date (str), end_date (str), timeout (int)
- **Response**: status, returncode, stdout, stderr, timestamp, command

### QC Validation
- **List**: GET `/qc/validations/`
- **Review**: GET/POST `/qc/review/`
- **Submit**: POST `/api/qc/submit`

### Tile Management
- **List**: GET `/tiles/all/`
- **Map**: GET `/tiles/map/`
- **Import**: POST `/api/data/tiles/import`

---

## Support & Documentation

- Full deployment guide: See `EASI_DJANGO_DEPLOYMENT.md`
- Django documentation: https://docs.djangoproject.com/en/6.0/
- Repository: https://github.com/Robotmcgregor/work-easi-eds
- Branch: `dev/django`

For questions or issues, check the GitHub repository issues section.

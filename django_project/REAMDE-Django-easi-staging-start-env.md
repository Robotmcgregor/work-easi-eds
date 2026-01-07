# Django on EASI — Staging Environment Startup Guide

This document describes how to **start the EDS Django application on EASI**
using the **staging settings** and a **Python virtual environment (`.venv`)**.

This is the **correct and supported way** to run the Django app on EASI.

---

## Confirmed Working Setup

- Platform: **EASI / Jupyter (Linux)**
- Python: **3.12**
- Django: **6.0.x**
- Environment: **Python venv (`.venv`)**
- Settings module: **`eds_easi.settings.staging`**
- Database: **SQLite**
  - `/home/jovyan/work-easi-eds/data/eds_database.db`

---

## Project Location

```bash
/home/jovyan/work-easi-eds/django_project
```

1) Activate the Python Virtual Environment

From inside the Django project directory:

```bash
cd /home/jovyan/work-easi-eds/django_project
source .venv/bin/activate

```

2) Verify

```bash
python -V
python -c "import django; print(django.get_version())"

```

Expected:

Python 3.12.x

Django 6.0.x

----

3) Use the Staging Settings Module

On EASI, always use staging settings.

This avoids:

 - missing DATABASES configuration

 - Windows-only paths

 - production-only settings

The staging module is:

```bash
eds_easi.settings.staging

```

4) Run Database Migrations (Required)

This creates Django’s internal tables
(auth, admin, sessions, django_migrations)
inside the existing SQLite database.

```bash
DJANGO_SETTINGS_MODULE=eds_easi.settings.staging \
python manage.py migrate --noinput

```

This is safe — application tables are marked managed = False.

----

5) Start the Django Development Server
```bash
DJANGO_SETTINGS_MODULE=eds_easi.settings.staging \
python manage.py runserver 0.0.0.0:8000
```

Access Django via Jupyter Proxy

Open in your browser:

App root:

```bash

/proxy/8000/
/proxy/8000/admin/
```
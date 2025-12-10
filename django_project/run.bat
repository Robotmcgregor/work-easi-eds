@echo off
REM Run Django management commands using the venv Python
cd /d "%~dp0"
venv\Scripts\python.exe manage.py %*

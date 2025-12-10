@echo off
REM Django Management Helper Script
REM This makes it easier to run Django commands with the correct Python environment

REM Set the conda environment path
set CONDA_PATH=C:/ProgramData/anaconda3/Scripts/conda.exe
set ENV_PATH=C:\Users\DCCEEW\mmroot\envs\slats

REM Run the Django command
%CONDA_PATH% run -p %ENV_PATH% python manage.py %*

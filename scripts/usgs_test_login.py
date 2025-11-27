#!/usr/bin/env python
"""
Simple USGS M2M login test using application token (preferred) or password.
Reads USGS_USERNAME, USGS_TOKEN, USGS_PASSWORD, USGS_M2M_ENDPOINT from environment or .env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import requests

# Ensure .env is loaded if present
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

BASE = (os.environ.get("USGS_M2M_ENDPOINT") or "https://m2m.cr.usgs.gov/api/api/json/stable/").rstrip('/') + '/'
USERNAME = os.environ.get("USGS_USERNAME", "")
TOKEN = os.environ.get("USGS_TOKEN", "")
PASSWORD = os.environ.get("USGS_PASSWORD", "")

if not USERNAME:
    print("USGS_USERNAME not set; set it in .env or environment.")
    sys.exit(2)

session_key = None

if TOKEN:
    r = requests.post(BASE + "login-token", json={"username": USERNAME, "token": TOKEN}, timeout=30)
    print("login-token:", r.status_code, (r.text or "")[:200])
    r.raise_for_status()
    session_key = r.json()["data"]
else:
    r = requests.post(BASE + "login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    print("login:", r.status_code, (r.text or "")[:200])
    r.raise_for_status()
    session_key = r.json()["data"]

# Test trivial endpoint
out = requests.post(BASE + "logout", headers={"X-Auth-Token": session_key}, json={}, timeout=30)
print("logout:", out.status_code, (out.text or "")[:120])

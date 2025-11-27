"""
USGS M2M Client (lightweight) for searching and downloading Landsat scenes.

Notes:
- Requires a USGS EarthExplorer/M2M account. Set USGS_USERNAME and USGS_PASSWORD.
- Dataset defaults to Collection 2 Level-1 for Landsat 8 (LANDSAT_8_C2_L1), tweak as needed.
- The M2M API returns an apiKey via /login which must be sent in 'X-Auth-Token' for subsequent calls.
- Endpoints are subject to change; adjust if your account/docs specify different paths.
"""
from __future__ import annotations

import os
import time
import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class USGSM2MClient:
    def __init__(self, username: str, password: Optional[str] = None, endpoint: str = "https://m2m.cr.usgs.gov/api/api/json/stable/", app_token: Optional[str] = None):
        self.username = username
        self.password = password or ""
        self.app_token = app_token or ""
        self.endpoint = endpoint.rstrip('/') + '/'
        self.api_key: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "eds-m2m-client/1.0 (+https://example.org)"
        }
        if self.api_key:
            h["X-Auth-Token"] = self.api_key
        return h

    def login(self) -> str:
        # Prefer application token if provided; otherwise fall back to password login
        if self.app_token:
            return self._login_with_token()
        payload = {"username": self.username, "password": self.password}
        # Try known base URL variants in case the stable path changes or is proxied
        base_candidates = [
            self.endpoint.rstrip('/') + '/login',
            'https://m2m.cr.usgs.gov/api/api/json/stable/login',
            'https://m2m.cr.usgs.gov/api/json/stable/login',
            'https://m2m.cr.usgs.gov/api/stable/json/login',
            'https://m2m.cr.usgs.gov/api/stable/login',
            'https://m2m.cr.usgs.gov/api/login',
        ]
        # Deduplicate while preserving order
        candidates: List[str] = []
        seen = set()
        for u in base_candidates:
            if u not in seen:
                candidates.append(u)
                seen.add(u)
        last_err: Optional[Exception] = None
        tried: List[str] = []
        for url in candidates:
            try:
                tried.append(url)
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=30, allow_redirects=False)
                # Surface redirects explicitly (corporate proxies or SSO sometimes redirect to HTML login)
                if 300 <= resp.status_code < 400:
                    loc = resp.headers.get('Location', '')
                    raise RuntimeError(f"Redirect ({resp.status_code}) from {url} -> {loc}")
                if resp.status_code == 404:
                    last_err = Exception(f"404 at {url}")
                    continue
                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception as je:
                    # Include first 200 chars of body for diagnostics
                    snippet = (resp.text or '')[:200]
                    raise RuntimeError(f"Non-JSON response at {url}: {je}; body starts with: {snippet!r}")
                if not data.get("data"):
                    last_err = Exception(f"Login response missing data: {data}")
                    continue
                self.api_key = data["data"]
                logger.info("USGS M2M login succeeded")
                return self.api_key
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"USGS login failed: {last_err}. Tried: {tried}")

    def _login_with_token(self) -> str:
        payload = {"username": self.username, "token": self.app_token}
        candidates = [
            self.endpoint.rstrip('/') + '/login-token',
            'https://m2m.cr.usgs.gov/api/api/json/stable/login-token',
            'https://m2m.cr.usgs.gov/api/json/stable/login-token',
            'https://m2m.cr.usgs.gov/api/api/stable/login-token',
        ]
        last_err: Optional[Exception] = None
        tried: List[str] = []
        for url in candidates:
            try:
                tried.append(url)
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=30, allow_redirects=False)
                if 300 <= resp.status_code < 400:
                    loc = resp.headers.get('Location', '')
                    raise RuntimeError(f"Redirect ({resp.status_code}) from {url} -> {loc}")
                if resp.status_code == 404:
                    last_err = Exception(f"404 at {url}")
                    continue
                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception as je:
                    snippet = (resp.text or '')[:200]
                    raise RuntimeError(f"Non-JSON response at {url}: {je}; body starts with: {snippet!r}")
                if not data.get("data"):
                    last_err = Exception(f"Login-token response missing data: {data}")
                    continue
                self.api_key = data["data"]
                logger.info("USGS M2M login via token succeeded")
                return self.api_key
            except Exception as e:
                last_err = e
                continue
        # Fallback: some deployments accept token in the normal /login route
        try:
            logger.info("Falling back to /login with token payload")
            self.app_token = self.app_token or ""
            payload_alt = {"username": self.username, "token": self.app_token}
            for url in [
                self.endpoint.rstrip('/') + '/login',
                'https://m2m.cr.usgs.gov/api/api/json/stable/login',
                'https://m2m.cr.usgs.gov/api/json/stable/login',
            ]:
                resp = requests.post(url, headers=self._headers(), json=payload_alt, timeout=30, allow_redirects=False)
                if 300 <= resp.status_code < 400:
                    loc = resp.headers.get('Location', '')
                    continue
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get('data'):
                    self.api_key = data['data']
                    return self.api_key
        except Exception:
            pass
        raise RuntimeError(f"USGS login-token failed: {last_err}. Tried: {tried}")

    def logout(self) -> None:
        if not self.api_key:
            return
        url = self.endpoint + "logout"
        try:
            requests.post(url, headers=self._headers()).raise_for_status()
        finally:
            self.api_key = None

    def search_scenes_wrs2(self, dataset: str, path: int, row: int, start: date, end: date, node: str = "EE", max_results: int = 100) -> List[Dict[str, Any]]:
        """Search scenes by WRS-2 path/row and date range.
        Returns a list of scenes (dicts as returned by M2M).
        """
        if not self.api_key:
            self.login()
        # Try multiple spatial filter variants to maximize compatibility with API
        filter_types = ["WRS2", "Wrs2", "Wrs2PathRow"]
        # Build common base payload
        base = {
            "node": node,
            # Some deployments honor these only under resultOptions
            "maxResults": max_results,
            "startingNumber": 1,
            "sortOrder": "DESC",
            "resultOptions": {"maxResults": max_results, "startingNumber": 1, "sortOrder": "DESC"},
        }
        # Try with datasetName first, then fall back to datasetId (using provided dataset string as the id)
        for ft in filter_types:
            # Variants for spatial input: single fields and arrays
            spatial_variants = [
                {"filterType": ft, "path": str(path), "row": str(row)},
                {"filterType": ft, "path": int(path), "row": int(row)},
                {"filterType": ft, "paths": [int(path)], "rows": [int(row)]},
            ]
            scene_filters = []
            for spatial in spatial_variants:
                scene_filters.append({
                    "spatialFilter": spatial,
                    # Acquisition dates belong in sceneFilter in many deployments
                    "acquisitionFilter": {"start": start.strftime('%Y-%m-%d'), "end": end.strftime('%Y-%m-%d')},
                    # Cloud cover filter; include unknown values
                    "cloudCoverFilter": {"min": 0, "max": 100, "includeUnknown": True},
                })
            payloads = []
            for sf in scene_filters:
                # Variant A: datasetName
                p_name = dict(base)
                p_name["datasetName"] = dataset
                p_name["sceneFilter"] = sf
                payloads.append(p_name)
                # Variant B: datasetId (some deployments require the id instead of name)
                p_id = dict(base)
                p_id["datasetId"] = dataset
                p_id["sceneFilter"] = sf
                payloads.append(p_id)
                # Variant C: temporalFilter at top-level (legacy), keep sceneFilter for spatial/cloud
                p_name_top = dict(p_name)
                p_name_top["temporalFilter"] = {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')}
                payloads.append(p_name_top)
                p_id_top = dict(p_id)
                p_id_top["temporalFilter"] = {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')}
                payloads.append(p_id_top)

            for payload in payloads:
                for ep in ("search", "scene-search"):
                    url = self.endpoint + ep
                    resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
                    if resp.status_code == 404:
                        continue
                    # Some payload variants may 400; skip to next variant
                    if resp.status_code >= 400:
                        continue
                    try:
                        data = resp.json()
                    except Exception:
                        continue
                    results = (data.get("data", {}) or {}).get("results", [])
                    if results:
                        return results or []
        return []
        raise RuntimeError("USGS M2M search endpoints not available (search/scene-search).")

    def get_download_options(self, dataset: str, entity_ids: List[str], node: str = "EE") -> List[Dict[str, Any]]:
        if not self.api_key:
            self.login()
        url = self.endpoint + "download-options"
        payload = {"datasetName": dataset, "entityIds": entity_ids, "node": node}
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", []) or []

    def request_download(self, dataset: str, products: List[Dict[str, Any]], node: str = "EE") -> Dict[str, Any]:
        if not self.api_key:
            self.login()
        url = self.endpoint + "download"
        payload = {"downloads": products, "label": "eds-download", "returnAvailable": True}
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("data", {}) or {}

    def download_files(self, downloads: Dict[str, Any], dest_dir: str) -> List[str]:
        os.makedirs(dest_dir, exist_ok=True)
        files: List[str] = []
        # 'availableDownloads' may include direct URLs; stagedDownloads need polling (omitted here)
        for item in downloads.get("availableDownloads", []) or []:
            url = item.get("url")
            if not url:
                continue
            filename = os.path.join(dest_dir, os.path.basename(url.split('?')[0]))
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            files.append(filename)
        return files

    def search_scenes_bbox(
        self,
        dataset: str,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        start: date,
        end: date,
        node: str = "EE",
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Search scenes using an MBR (bounding box) and date range.
        Tries multiple payload variants for compatibility across deployments.
        """
        if not self.api_key:
            self.login()
        base = {
            "node": node,
            "maxResults": max_results,
            "startingNumber": 1,
            "sortOrder": "DESC",
            "resultOptions": {"maxResults": max_results, "startingNumber": 1, "sortOrder": "DESC"},
        }
        # Spatial variants: mbr/Mbr keys
        mbr_variants = [
            {
                "filterType": "mbr",
                "lowerLeft": {"latitude": float(min_lat), "longitude": float(min_lon)},
                "upperRight": {"latitude": float(max_lat), "longitude": float(max_lon)},
            },
            {
                "filterType": "Mbr",
                "lowerLeft": {"latitude": float(min_lat), "longitude": float(min_lon)},
                "upperRight": {"latitude": float(max_lat), "longitude": float(max_lon)},
            },
        ]
        payloads: List[Dict[str, Any]] = []
        for mbr in mbr_variants:
            scene_filter = {
                "spatialFilter": mbr,
                "acquisitionFilter": {"start": start.strftime('%Y-%m-%d'), "end": end.strftime('%Y-%m-%d')},
                "cloudCoverFilter": {"min": 0, "max": 100, "includeUnknown": True},
            }
            p_name = dict(base); p_name["datasetName"] = dataset; p_name["sceneFilter"] = scene_filter
            payloads.append(p_name)
            p_id = dict(base); p_id["datasetId"] = dataset; p_id["sceneFilter"] = scene_filter
            payloads.append(p_id)
            # Also try temporalFilter at top-level
            for pl in (p_name, p_id):
                p_top = dict(pl)
                p_top["temporalFilter"] = {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')}
                payloads.append(p_top)

        for payload in payloads:
            for ep in ("search", "scene-search"):
                url = self.endpoint + ep
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
                if resp.status_code == 404:
                    continue
                if resp.status_code >= 400:
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
                results = (data.get("data", {}) or {}).get("results", [])
                if results:
                    return results or []
        return []

    def search_recent(self, dataset: str, days: int = 14, node: str = "EE", max_results: int = 50) -> List[Dict[str, Any]]:
        """List recent scenes globally for a dataset without spatial constraints (best-effort).
        Uses the last N days as a temporal filter to reduce result size.
        """
        from datetime import timedelta, datetime as dt
        if not self.api_key:
            self.login()
        end = dt.utcnow().date()
        start = end - timedelta(days=max(1, days))
        base = {
            "node": node,
            "maxResults": max_results,
            "startingNumber": 1,
            "sortOrder": "DESC",
            "resultOptions": {"maxResults": max_results, "startingNumber": 1, "sortOrder": "DESC"},
        }
        payloads: List[Dict[str, Any]] = []
        # datasetName and datasetId variants
        p_name = dict(base); p_name["datasetName"] = dataset; p_name["temporalFilter"] = {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')}
        payloads.append(p_name)
        p_id = dict(base); p_id["datasetId"] = dataset; p_id["temporalFilter"] = {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')}
        payloads.append(p_id)
        for payload in payloads:
            for ep in ("search", "scene-search"):
                url = self.endpoint + ep
                resp = requests.post(url, headers=self._headers(), json=payload, timeout=60)
                if resp.status_code == 404:
                    continue
                if resp.status_code >= 400:
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
                results = (data.get("data", {}) or {}).get("results", [])
                if results:
                    return results or []
        return []

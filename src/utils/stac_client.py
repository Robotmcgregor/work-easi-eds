"""
Minimal STAC client helpers for Landsat discovery via LandsatLook STAC.
"""

from __future__ import annotations

import requests
from typing import Any, Dict, List, Optional


class STACClient:
    def __init__(self, base_url: str = "https://landsatlook.usgs.gov/stac-server"):
        self.base_url = base_url.rstrip("/")

    def search(
        self,
        collections: Optional[List[str]] = None,
        bbox: Optional[List[float]] = None,
        datetime_range: Optional[str] = None,
        limit: int = 10,
        query: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "limit": limit,
        }
        if collections:
            payload["collections"] = collections
        if bbox:
            payload["bbox"] = bbox
        if datetime_range:
            payload["datetime"] = datetime_range
        if query:
            payload["query"] = query

        url = f"{self.base_url}/search"
        headers = {
            "Content-Type": "application/geo+json",
            "Accept": "application/geo+json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def list_collections(self) -> Dict[str, Any]:
        url = f"{self.base_url}/collections"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def search_cql2(
        self,
        collections: Optional[List[str]] = None,
        filter_obj: Optional[Dict[str, Any]] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "limit": limit,
            "filter-lang": "cql2-json",
        }
        if collections:
            payload["collections"] = collections
        if filter_obj:
            payload["filter"] = filter_obj

        url = f"{self.base_url}/search"
        headers = {
            "Content-Type": "application/geo+json",
            "Accept": "application/geo+json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

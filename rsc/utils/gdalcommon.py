"""
Shim for rsc.utils.gdalcommon used by the QLD script.
Implements colour table helpers as no-ops.
"""
from __future__ import annotations

from typing import Any, Optional


def readColourTableFromFile(path: str) -> Optional[Any]:
    # Not required for core processing; return None
    return None


def setColourTable(clrTbl, filename: str, layernum: int = 1):
    # No-op in compatibility mode
    return

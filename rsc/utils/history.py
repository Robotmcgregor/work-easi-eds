"""
Shim for rsc.utils.history used by the QLD script.
No-op metadata insertion.
"""

from __future__ import annotations

from typing import List, Dict


def insertMetadataFilename(filename: str, parents: List[str], opt: Dict[str, str]):
    # No-op in compatibility mode
    return

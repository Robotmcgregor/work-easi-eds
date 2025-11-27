"""
Minimal shim for QLD qv helpers used by edsadhoc_timeserieschange_d.py.
We avoid any heavy data management; recallToHere is a no-op by default.
"""
from __future__ import annotations

from typing import Iterable, List


def recallToHere(files: Iterable[str]) -> None:
    """Placeholder for QLD's recallToHere. We assume files are already local via our compat builder.
    Implement S3 retrieval here if needed.
    """
    fs = list(files)
    if not fs:
        return
    # No-op: compatibility layer is responsible for creating files locally.
    print(f"[qv] recallToHere: assuming {len(fs)} file(s) already present locally")

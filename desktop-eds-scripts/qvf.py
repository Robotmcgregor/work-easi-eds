"""
Minimal shim for QLD qvf helpers used by edsadhoc_timeserieschange_d.py.
Provides filename parsing/assembly compatible enough for the script to run.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, date


def _basename(fn: str) -> str:
    return os.path.basename(fn)


def locationid(filename: str) -> str:
    """Return scene code like p090r084 parsed from filename or raise if not found."""
    m = re.search(r"_(p\d{3}r\d{3})_", _basename(filename).lower())
    if not m:
        raise ValueError(f"Cannot parse locationid from {filename}")
    return m.group(1)


def when(filename: str) -> str:
    """Return yyyymmdd parsed from filename."""
    m = re.search(r"_(\d{8})_", _basename(filename))
    if not m:
        raise ValueError(f"Cannot parse date from {filename}")
    return m.group(1)


def when_dateobj(filename: str) -> date:
    s = when(filename)
    return datetime.strptime(s, "%Y%m%d").date()


def stage(filename: str) -> str:
    m = re.search(r"_(d[a-z0-9]{2})mz\.img$", _basename(filename).lower())
    return m.group(1) if m else "db8"


def zonecode(filename: str) -> str:
    # Keep simple: return 'mz' as per filenames used by the script
    return "mz"


def satellite(filename: str) -> str:
    # Use 'lz' (generic Landsat) prefix expected by naming in the script
    return "lz"


def instrument(filename: str) -> str:
    # Use 'tm' as a generic instrument code for naming purposes only
    return "tm"


def utmzone(filename: str) -> str:
    # Return a reasonable default; not used unless clipqldstate enabled
    return "55"


def changestage(filename: str, newstage: str) -> str:
    """Replace the stage code part (e.g., _db8mz) with newstage + 'mz'."""
    base = _basename(filename)
    # Use subn to detect whether a replacement occurred
    out, n = re.subn(
        r"_(d[a-z0-9]{2})mz\.img$", f"_{newstage}mz.img", base, flags=re.IGNORECASE
    )
    if n == 0:
        # Pattern not found; append stage suffix once
        base2 = base if base.lower().endswith(".img") else base + ".img"
        out = re.sub(r"\.img$", f"_{newstage}mz.img", base2)
    return out


def changeoptionfield(filename: str, field: str, value: str) -> str:
    """Change an option field designated by 'z' to a value (masked, normed, indexes).
    We encode this by inserting '_z<value>' before extension.
    """
    base = _basename(filename)
    # remove any existing _z... token
    base = re.sub(r"_z[a-z]+", "", base, flags=re.IGNORECASE)
    out = re.sub(r"\.img$", f"_z{value}.img", base, flags=re.IGNORECASE)
    if out == base:
        out = base + f"_z{value}"
    return out


def assemble(parts) -> str:
    return "_".join([str(p) for p in parts])

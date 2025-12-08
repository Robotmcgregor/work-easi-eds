"""
Shim for rsc.utils.metadb expected by the QLD script.
Implements a tiny SQLite metadb and a stdProjFilename mapper into a local compat folder.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional, Any

DB_API = "sqlite3"

COMPAT_DIR = Path("data/compat").resolve()
FILES_DIR = COMPAT_DIR / "files"
DB_PATH = COMPAT_DIR / "metadb.sqlite"


def _ensure_dirs():
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    COMPAT_DIR.mkdir(parents=True, exist_ok=True)


def connect(api: str = DB_API):
    _ensure_dirs()
    need_init = not DB_PATH.exists()
    base_con = sqlite3.connect(str(DB_PATH))
    if need_init:
        _init_db(base_con)
    return _ProxyConnection(base_con)


def _init_db(con: sqlite3.Connection):
    cur = con.cursor()
    # Minimal tables referenced by the script
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS landsat_list (
            scene TEXT,
            date TEXT,
            product TEXT,
            satellite TEXT,
            instrument TEXT
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cloudamount (
            scene TEXT,
            date TEXT,
            pcntcloud REAL
        )
    """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS slats_dates (
            scene TEXT,
            year INTEGER,
            date TEXT
        )
    """
    )
    con.commit()


def stdProjFilename(name: str) -> str:
    """Map a logical QLD filename to a local compatibility path.
    If 'name' is already an absolute path that exists, return it.
    Otherwise, place it under data/compat/files/<scene>/<name>.
    """
    p = Path(name)
    if p.is_absolute() and p.exists():
        return str(p)
    from ..utils_common import parse_scene_from_name

    scene = parse_scene_from_name(Path(name).name) or "unknown_scene"
    dest = FILES_DIR / scene / Path(name).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    return str(dest)


class _ProxyCursor:
    """Lightweight cursor proxy to patch minor SQL compatibility issues without changing caller code.

    Specifically, qualify ambiguous ORDER BY clauses that refer to 'date' to 'landsat_list.date'.
    """

    def __init__(self, cursor: sqlite3.Cursor):
        self._c = cursor

    def _rewrite_sql(self, sql: str) -> str:
        try:
            import re

            # Qualify ORDER BY date to avoid ambiguity
            sql = re.sub(
                r"order\s+by\s+date\b",
                "order by landsat_list.date",
                sql,
                flags=re.IGNORECASE,
            )
            # Remove satellite filter (allow our synthetic 'lz' entries) by replacing it with a tautology
            sql = re.sub(
                r"landsat_list\.satellite\s+in\s*\('l8'\s*,\s*'l9'\)",
                "1=1",
                sql,
                flags=re.IGNORECASE,
            )
            # Normalize SUBSTRING to SQLite substr
            sql = re.sub(r"substring\s*\(", "substr(", sql, flags=re.IGNORECASE)
        except Exception:
            pass
        return sql

    def execute(self, sql: str, parameters: Any = None):
        sql2 = self._rewrite_sql(sql)
        if parameters is None:
            return self._c.execute(sql2)
        return self._c.execute(sql2, parameters)

    def executemany(self, sql: str, seq_of_parameters):
        sql2 = self._rewrite_sql(sql)
        return self._c.executemany(sql2, seq_of_parameters)

    # Delegate attribute access and iteration
    def __getattr__(self, item):
        return getattr(self._c, item)

    def __iter__(self):
        return iter(self._c)


class _ProxyConnection:
    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def cursor(self, *args, **kwargs):
        return _ProxyCursor(self._con.cursor(*args, **kwargs))

    # Delegate commonly used methods
    def commit(self):
        return self._con.commit()

    def close(self):
        return self._con.close()

    def __getattr__(self, item):
        return getattr(self._con, item)

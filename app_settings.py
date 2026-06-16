"""
app_settings.py — tiny persisted key/value store for runtime app settings.

Used for admin-toggleable flags (e.g. the v1/v2 form-fetcher switch) that must
survive restarts and apply live without editing .env. SQLite, one row per key.
"""

import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "app_settings.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    try:
        with _conn() as con:
            con.execute(_CREATE)
        logger.info("app_settings: DB ready at %s", DB_PATH)
    except Exception as exc:
        logger.error("app_settings: init failed: %s", exc)


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with _conn() as con:
            row = con.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    except Exception as exc:
        logger.warning("app_settings.get(%s) failed: %s", key, exc)
        return default


def set(key: str, value: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_bool(key: str, default: bool = False) -> bool:
    v = get(key, None)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def set_bool(key: str, value: bool) -> None:
    set(key, "1" if value else "0")

"""
tag_registry.py — Local SQLite store for client/sendout include & exclude tags.

Replaces the Google-Sheets dependency for tag data: ops enter tags once here and
the validator reads from this registry (falling back to GSheet only when no
registry entry exists for the matched sendout).

Schema
------
  id           auto-increment PK
  client       TEXT  — must match a key in CLIENT_CONFIGS
  sendout_id   TEXT  — DMA task/sendout ID
  sendout_name TEXT  — human-readable label (display only)
  sendout_date TEXT  — YYYY-MM-DD
  sendout_time TEXT  — HH:MM (24-hour)
  tz           TEXT  — IANA timezone name, e.g. "Europe/Berlin"
  include_tags TEXT  — comma-separated tag tokens
  exclude_tags TEXT  — comma-separated tag tokens
  notes        TEXT  — free-form comment
  created_at   TEXT  — ISO-8601 UTC
  updated_at   TEXT  — ISO-8601 UTC
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone as _utc
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "tag_registry.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tag_registry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client       TEXT    NOT NULL,
    ticket_key   TEXT    NOT NULL DEFAULT '',
    sendout_id   TEXT    NOT NULL DEFAULT '',
    sendout_name TEXT    NOT NULL DEFAULT '',
    sendout_date TEXT    NOT NULL DEFAULT '',
    sendout_time TEXT    NOT NULL DEFAULT '',
    tz           TEXT    NOT NULL DEFAULT 'Europe/Berlin',
    platform      TEXT    NOT NULL DEFAULT '',
    template_type TEXT    NOT NULL DEFAULT '',
    include_tags  TEXT    NOT NULL DEFAULT '',
    exclude_tags  TEXT    NOT NULL DEFAULT '',
    notes         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
"""

_MIGRATIONS = [
    # v2 — ticket_key column
    "ALTER TABLE tag_registry ADD COLUMN ticket_key TEXT NOT NULL DEFAULT ''",
    # v3 — platform and template_type columns
    "ALTER TABLE tag_registry ADD COLUMN platform TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE tag_registry ADD COLUMN template_type TEXT NOT NULL DEFAULT ''",
]

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_reg_client_sendout ON tag_registry (client, sendout_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_client_ticket  ON tag_registry (client, ticket_key)",
]


# ── connection helper ─────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(_utc.utc).isoformat()


# ── init ──────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create table + indexes, run pending migrations. Safe to call on every startup."""
    try:
        with _conn() as con:
            con.execute(_CREATE_TABLE)
            for idx in _CREATE_INDEXES:
                con.execute(idx)
            # Run migrations — each is a no-op if the column already exists
            for stmt in _MIGRATIONS:
                try:
                    con.execute(stmt)
                except Exception:
                    pass  # column already exists
        logger.info("tag_registry: DB ready at %s", DB_PATH)
    except Exception as exc:
        logger.error("tag_registry: init failed: %s", exc)


# ── read ──────────────────────────────────────────────────────────────────────

def list_entries(client: Optional[str] = None) -> list[dict]:
    """Return all entries, optionally filtered by client, newest-first."""
    with _conn() as con:
        if client:
            rows = con.execute(
                "SELECT * FROM tag_registry WHERE client = ? ORDER BY updated_at DESC",
                (client,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM tag_registry ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_id: int) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM tag_registry WHERE id = ?", (entry_id,)
        ).fetchone()
    return dict(row) if row else None


def match_by_ticket(client: str, ticket_key: str) -> Optional[dict]:
    """
    Strongest match: client + Jira ticket key.
    Skips entries whose sendout_date is strictly in the past (expired).
    """
    if not ticket_key:
        return None
    with _conn() as con:
        row = con.execute(
            """SELECT * FROM tag_registry
               WHERE client = ? AND ticket_key = ?
                 AND (sendout_date = '' OR sendout_date >= date('now'))
               ORDER BY updated_at DESC LIMIT 1""",
            (client, ticket_key),
        ).fetchone()
    return dict(row) if row else None


def match_entry(client: str, sendout_id: str) -> Optional[dict]:
    """
    Match by client + sendout_id (second priority after ticket_key match).
    Skips entries whose sendout_date is strictly in the past (expired).
    """
    with _conn() as con:
        row = con.execute(
            """SELECT * FROM tag_registry
               WHERE client = ? AND sendout_id = ?
                 AND (sendout_date = '' OR sendout_date >= date('now'))
               ORDER BY updated_at DESC LIMIT 1""",
            (client, str(sendout_id)),
        ).fetchone()
        if row:
            return dict(row)
    return None


def match_by_date(client: str, sendout_date: str) -> Optional[dict]:
    """Secondary fallback: match by client + sendout date (YYYY-MM-DD).
    Since we're matching on the sendout date itself, expiry does not apply here —
    the entry is valid on its own sendout day."""
    with _conn() as con:
        row = con.execute(
            """SELECT * FROM tag_registry
               WHERE client = ? AND sendout_date = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (client, sendout_date),
        ).fetchone()
    return dict(row) if row else None


# ── write ─────────────────────────────────────────────────────────────────────

def create_entry(
    client: str,
    ticket_key: str = "",
    sendout_id: str = "",
    sendout_name: str = "",
    sendout_date: str = "",
    sendout_time: str = "",
    tz: str = "Europe/Berlin",
    platform: str = "",
    template_type: str = "",
    include_tags: str = "",
    exclude_tags: str = "",
    notes: str = "",
) -> dict:
    now = _now()
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO tag_registry
               (client, ticket_key, sendout_id, sendout_name, sendout_date, sendout_time,
                tz, platform, template_type, include_tags, exclude_tags, notes,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (client, ticket_key, sendout_id, sendout_name, sendout_date, sendout_time,
             tz, platform, template_type, include_tags, exclude_tags, notes, now, now),
        )
        return get_entry(cur.lastrowid)


def update_entry(entry_id: int, **fields) -> Optional[dict]:
    _allowed = {
        "ticket_key", "sendout_id", "sendout_name", "sendout_date", "sendout_time",
        "tz", "platform", "template_type", "include_tags", "exclude_tags", "notes",
    }
    updates = {k: v for k, v in fields.items() if k in _allowed}
    if not updates:
        return get_entry(entry_id)
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as con:
        con.execute(
            f"UPDATE tag_registry SET {set_clause} WHERE id = ?",
            (*updates.values(), entry_id),
        )
    return get_entry(entry_id)


def delete_entry(entry_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM tag_registry WHERE id = ?", (entry_id,))
    return cur.rowcount > 0

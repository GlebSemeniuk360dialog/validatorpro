"""
client_config.py — SQLite-backed editable client configuration.

Overrides config.py defaults without touching the static file.
Seeded from config.py on first startup; every subsequent start
reads from DB so UI changes survive restarts.

Schema
------
  name          TEXT PK  — client name (key in CLIENT_CONFIGS)
  account_id    INTEGER  — DMA account ID (required for new clients)
  timezone_name TEXT
  requires_jira INTEGER  (1=True / 0=False)
  filters_json  TEXT     — JSON: {set_name: [filter_obj, …]}
  aliases_json  TEXT     — JSON: [alias_str, …]
  mappings_json TEXT     — JSON: {segment_key: {label: tag}}
  is_custom     INTEGER  — 1 = created from UI (not seeded from config.py)
  updated_at    TEXT     — ISO-8601 UTC
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone as _utc
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "client_config.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS client_config (
    name          TEXT PRIMARY KEY,
    account_id    INTEGER NOT NULL DEFAULT 0,
    timezone_name TEXT    NOT NULL DEFAULT 'Europe/Berlin',
    requires_jira INTEGER NOT NULL DEFAULT 1,
    filters_json  TEXT    NOT NULL DEFAULT '{}',
    aliases_json  TEXT    NOT NULL DEFAULT '[]',
    mappings_json TEXT    NOT NULL DEFAULT '{}',
    is_custom     INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT    NOT NULL
);
"""

# Migrations applied to existing DBs that predate new columns
_MIGRATIONS = [
    "ALTER TABLE client_config ADD COLUMN account_id INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE client_config ADD COLUMN is_custom  INTEGER NOT NULL DEFAULT 0",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(_utc.utc).isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["filters"]      = json.loads(d.pop("filters_json",  "{}") or "{}")
    d["aliases"]      = json.loads(d.pop("aliases_json",  "[]") or "[]")
    d["mappings"]     = json.loads(d.pop("mappings_json", "{}") or "{}")
    d["requires_jira"] = bool(d["requires_jira"])
    d["is_custom"]    = bool(d.get("is_custom", 0))
    d.setdefault("account_id", 0)
    return d


# ── init ──────────────────────────────────────────────────────────────────────

def init_db(seed_configs: dict, seed_aliases: dict) -> None:
    """
    Create the table if needed.
    Seeds from config.py on first run (empty table); subsequent
    starts skip seeding so UI edits are preserved.
    Runs column migrations on existing DBs.
    """
    with _conn() as con:
        con.execute(_CREATE)
        # Run migrations silently (ignore "duplicate column" errors)
        for sql in _MIGRATIONS:
            try:
                con.execute(sql)
            except Exception:
                pass
        count = con.execute("SELECT COUNT(*) FROM client_config").fetchone()[0]
        if count == 0:
            logger.info("client_config: seeding from config.py (%d clients)", len(seed_configs))
            now = _now()
            for name, cfg in seed_configs.items():
                aliases = seed_aliases.get(name, [])
                con.execute(
                    """INSERT OR IGNORE INTO client_config
                       (name, account_id, timezone_name, requires_jira, filters_json,
                        aliases_json, mappings_json, is_custom, updated_at)
                       VALUES (?,?,?,?,?,?,?,0,?)""",
                    (
                        name,
                        cfg.get("account_id", 0),
                        cfg.get("timezone_name", "Europe/Berlin"),
                        1 if cfg.get("requires_jira", True) else 0,
                        json.dumps(cfg.get("filters", {})),
                        json.dumps(aliases),
                        json.dumps(cfg.get("mappings", {})),
                        now,
                    ),
                )
    logger.info("client_config: DB ready at %s", DB_PATH)


# ── read ──────────────────────────────────────────────────────────────────────

def list_clients() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM client_config ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_client(name: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM client_config WHERE name = ?", (name,)
        ).fetchone()
    return _row_to_dict(row) if row else None


# ── write ─────────────────────────────────────────────────────────────────────

def upsert_client(
    name: str,
    timezone_name: str,
    requires_jira: bool,
    filters: dict,
    aliases: list,
    mappings: Optional[dict] = None,
    account_id: int = 0,
    is_custom: bool = False,
) -> dict:
    """Insert or update a client config row. Returns the saved record."""
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO client_config
               (name, account_id, timezone_name, requires_jira, filters_json,
                aliases_json, mappings_json, is_custom, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 account_id    = CASE WHEN excluded.is_custom THEN excluded.account_id ELSE account_id END,
                 timezone_name = excluded.timezone_name,
                 requires_jira = excluded.requires_jira,
                 filters_json  = excluded.filters_json,
                 aliases_json  = excluded.aliases_json,
                 mappings_json = excluded.mappings_json,
                 updated_at    = excluded.updated_at""",
            (
                name,
                account_id,
                timezone_name,
                1 if requires_jira else 0,
                json.dumps(filters),
                json.dumps(aliases),
                json.dumps(mappings or {}),
                1 if is_custom else 0,
                now,
            ),
        )
    return get_client(name)


# ── apply to memory ───────────────────────────────────────────────────────────

def apply_to_memory(CLIENT_CONFIGS: dict, CLIENT_ALIASES: dict) -> None:
    """
    Load all rows from DB and update the in-memory CLIENT_CONFIGS and
    CLIENT_ALIASES dicts in place.  Called on startup and after /api/config/reload.
    Custom clients (is_custom=1) are created in CLIENT_CONFIGS if not present.
    """
    rows = list_clients()
    applied = 0
    for row in rows:
        name = row["name"]
        if name not in CLIENT_CONFIGS:
            if row.get("is_custom"):
                # New client created from UI — inject into in-memory config
                CLIENT_CONFIGS[name] = {
                    "account_id":    row["account_id"],
                    "timezone_name": row["timezone_name"],
                    "requires_jira": row["requires_jira"],
                    "filters":       row["filters"] or {},
                    "mappings":      row["mappings"] or {},
                }
                logger.info("client_config: registered custom client '%s' (account_id=%s)", name, row["account_id"])
            else:
                continue
        else:
            CLIENT_CONFIGS[name]["timezone_name"] = row["timezone_name"]
            CLIENT_CONFIGS[name]["requires_jira"] = row["requires_jira"]
            if row["filters"]:
                CLIENT_CONFIGS[name]["filters"] = row["filters"]
            if row["mappings"]:
                CLIENT_CONFIGS[name]["mappings"] = row["mappings"]
        CLIENT_ALIASES[name] = row["aliases"]
        applied += 1
    logger.info("client_config: applied %d client configs to memory", applied)


def delete_client(name: str) -> bool:
    """Delete a custom client. Returns True if deleted, False if not found or not custom."""
    with _conn() as con:
        row = con.execute(
            "SELECT is_custom FROM client_config WHERE name = ?", (name,)
        ).fetchone()
        if not row or not row["is_custom"]:
            return False
        con.execute("DELETE FROM client_config WHERE name = ?", (name,))
    return True

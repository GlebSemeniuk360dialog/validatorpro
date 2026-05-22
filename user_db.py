"""
user_db.py — SQLite-backed user store.

Seeded from the hardcoded _USERS dict on first run.
Subsequent starts read from DB so admin changes survive restarts.

Schema
------
  username      TEXT PK
  display_name  TEXT
  password_hash TEXT  — SHA-256 hex
  is_admin      INTEGER  (1=True / 0=False)
  active        INTEGER  (1=active / 0=deactivated)
  created_at    TEXT  — ISO-8601 UTC
  updated_at    TEXT  — ISO-8601 UTC
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone as _utc
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    display_name  TEXT    NOT NULL DEFAULT '',
    password_hash TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(_utc.utc).isoformat()


def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


# ── init ──────────────────────────────────────────────────────────────────────

def init_db(seed_users: dict) -> None:
    """
    Create table if needed.
    seed_users format: {username: (display_name, password_hash)}
    First user in seed_users that has username 'gleb' gets is_admin=1.
    """
    with _conn() as con:
        con.execute(_CREATE)
        count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            logger.info("user_db: seeding %d users", len(seed_users))
            now = _now()
            for i, (uname, (display, pwd_hash)) in enumerate(seed_users.items()):
                is_admin = 1 if uname == "gleb" else 0
                con.execute(
                    """INSERT OR IGNORE INTO users
                       (username, display_name, password_hash, is_admin, active, created_at, updated_at)
                       VALUES (?,?,?,?,1,?,?)""",
                    (uname, display, pwd_hash, is_admin, now, now),
                )
    logger.info("user_db: DB ready at %s", DB_PATH)


# ── read ──────────────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    """Return all users (password_hash excluded)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT username, display_name, is_admin, active, created_at, updated_at "
            "FROM users ORDER BY username"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user(username: str) -> Optional[dict]:
    """Return a user row including password_hash (for auth). None if not found."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def authenticate(username: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns user dict (without password_hash) on success,
    None on failure (wrong password, inactive, or not found).
    """
    import hmac as _hmac
    user = get_user(username)
    if not user:
        return None
    if not user.get("active"):
        return None
    if not _hmac.compare_digest(hash_password(password), user["password_hash"]):
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


# ── write ─────────────────────────────────────────────────────────────────────

def create_user(
    username:     str,
    display_name: str,
    password:     str,
    is_admin:     bool = False,
) -> dict:
    now = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO users
               (username, display_name, password_hash, is_admin, active, created_at, updated_at)
               VALUES (?,?,?,?,1,?,?)""",
            (username.strip().lower(), display_name.strip(),
             hash_password(password), 1 if is_admin else 0, now, now),
        )
    return {k: v for k, v in (get_user(username) or {}).items() if k != "password_hash"}


def update_user(
    username:     str,
    display_name: Optional[str] = None,
    password:     Optional[str] = None,
    is_admin:     Optional[bool] = None,
    active:       Optional[bool] = None,
) -> Optional[dict]:
    updates: dict = {"updated_at": _now()}
    if display_name is not None: updates["display_name"]  = display_name.strip()
    if password     is not None: updates["password_hash"] = hash_password(password)
    if is_admin     is not None: updates["is_admin"]      = 1 if is_admin else 0
    if active       is not None: updates["active"]        = 1 if active else 0
    if len(updates) == 1:        # only updated_at — nothing to do
        return {k: v for k, v in (get_user(username) or {}).items() if k != "password_hash"}
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as con:
        con.execute(
            f"UPDATE users SET {set_clause} WHERE username = ?",
            (*updates.values(), username),
        )
    return {k: v for k, v in (get_user(username) or {}).items() if k != "password_hash"}


def delete_user(username: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM users WHERE username = ?", (username,))
    return cur.rowcount > 0

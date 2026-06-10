"""
audit_log.py — SQLite persistence for AI audit results and preflight runs.

Replaces the in-memory _audited_sendouts dict so results survive restarts
and can be browsed in the UI.

Schema — audit_log
-------------------
  id           auto PK
  ticket_key   TEXT
  client       TEXT
  sendout_id   TEXT
  overall      TEXT  — PASS / FAIL / ERROR
  scheduling   TEXT  — PASS / FAIL / NA
  copy         TEXT
  footer       TEXT
  cta          TEXT
  tags         TEXT
  images       TEXT
  confidence   INTEGER  (-1 = unknown)
  triggered_by TEXT  — manual / auto
  created_at   TEXT  — ISO-8601 UTC

Schema — preflight_runs
------------------------
  id         auto PK
  ran_at     TEXT  — ISO-8601 UTC
  tickets    TEXT  — JSON array of ticket dicts
  sent_slack INTEGER  (0/1)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone as _utc
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "audit_log.db")

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_key   TEXT    NOT NULL DEFAULT '',
    client       TEXT    NOT NULL DEFAULT '',
    sendout_id   TEXT    NOT NULL DEFAULT '',
    overall      TEXT    NOT NULL DEFAULT '',
    scheduling   TEXT    NOT NULL DEFAULT '',
    copy         TEXT    NOT NULL DEFAULT '',
    footer       TEXT    NOT NULL DEFAULT '',
    cta          TEXT    NOT NULL DEFAULT '',
    tags         TEXT    NOT NULL DEFAULT '',
    images       TEXT    NOT NULL DEFAULT '',
    confidence   INTEGER NOT NULL DEFAULT -1,
    triggered_by TEXT    NOT NULL DEFAULT 'manual',
    user         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL
);
"""

_CREATE_PREFLIGHT = """
CREATE TABLE IF NOT EXISTS preflight_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at     TEXT    NOT NULL,
    tickets    TEXT    NOT NULL DEFAULT '[]',
    sent_slack INTEGER NOT NULL DEFAULT 0
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_al_ticket  ON audit_log (ticket_key)",
    "CREATE INDEX IF NOT EXISTS idx_al_client  ON audit_log (client)",
    "CREATE INDEX IF NOT EXISTS idx_al_created ON audit_log (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_pf_ran     ON preflight_runs (ran_at)",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(_utc.utc).isoformat()


# ── init ──────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables and indexes. Safe to call on every startup."""
    try:
        with _conn() as con:
            con.execute(_CREATE_AUDIT)
            con.execute(_CREATE_PREFLIGHT)
            for idx in _INDEXES:
                con.execute(idx)
            # Migration: add user column if missing (safe to run repeatedly)
            try:
                con.execute("ALTER TABLE audit_log ADD COLUMN user TEXT NOT NULL DEFAULT ''")
                logger.info("audit_log: migrated — added 'user' column")
            except Exception:
                pass  # column already exists
        logger.info("audit_log: DB ready at %s", DB_PATH)
    except Exception as exc:
        logger.error("audit_log: init failed: %s", exc)


# ── audit_log write ───────────────────────────────────────────────────────────

def record_audit(
    ticket_key:   str,
    client:       str,
    sendout_id:   str,
    overall:      str,
    structured:   Optional[dict] = None,
    confidence:   int = -1,
    triggered_by: str = "manual",
    user:         str = "",
) -> int:
    """
    Persist one audit result. `structured` is the AuditOutput.model_dump() dict
    with per-check verdicts (scheduling, copy, footer, cta, tags, images).
    Returns the new row id.
    """
    s = structured or {}

    def _v(key: str) -> str:
        chk = s.get(key, {})
        return chk.get("verdict", "") if isinstance(chk, dict) else ""

    now = _now()
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO audit_log
               (ticket_key, client, sendout_id, overall,
                scheduling, copy, footer, cta, tags, images,
                confidence, triggered_by, user, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ticket_key, client, sendout_id, overall,
                _v("scheduling"), _v("copy"), _v("footer"),
                _v("cta"), _v("tags"), _v("images"),
                confidence, triggered_by, user, now,
            ),
        )
        return cur.lastrowid


# ── audit_log read ────────────────────────────────────────────────────────────

def list_audits(
    limit:      int = 100,
    client:     Optional[str] = None,
    ticket_key: Optional[str] = None,
) -> list[dict]:
    """Return recent audit rows, newest-first."""
    with _conn() as con:
        where, params = [], []
        if client:
            where.append("client = ?");     params.append(client)
        if ticket_key:
            where.append("ticket_key = ?"); params.append(ticket_key)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = con.execute(
            f"SELECT * FROM audit_log {clause} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def was_audited(sendout_id: str = "", ticket_key: str = "") -> Optional[dict]:
    """
    Check if a sendout or ticket was already audited (most recent match).
    Used by the auto-audit job to avoid re-auditing.
    """
    with _conn() as con:
        if sendout_id:
            row = con.execute(
                "SELECT * FROM audit_log WHERE sendout_id = ? ORDER BY created_at DESC LIMIT 1",
                (sendout_id,),
            ).fetchone()
            if row:
                return dict(row)
        if ticket_key:
            row = con.execute(
                "SELECT * FROM audit_log WHERE ticket_key = ? ORDER BY created_at DESC LIMIT 1",
                (ticket_key,),
            ).fetchone()
            if row:
                return dict(row)
    return None


def get_audited_sendout_ids() -> set[str]:
    """Return all sendout_ids that have been audited (for skip-check in auto-audit)."""
    with _conn() as con:
        rows = con.execute("SELECT DISTINCT sendout_id FROM audit_log WHERE sendout_id != ''").fetchall()
    return {r[0] for r in rows}


def get_audited_ticket_keys() -> set[str]:
    """Return all ticket_keys that have been audited."""
    with _conn() as con:
        rows = con.execute("SELECT DISTINCT ticket_key FROM audit_log WHERE ticket_key != ''").fetchall()
    return {r[0] for r in rows}


def get_audit_for_ticket(ticket_key: str) -> Optional[dict]:
    """Return the most recent audit for a ticket (used by preflight job)."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM audit_log WHERE ticket_key = ? ORDER BY created_at DESC LIMIT 1",
            (ticket_key,),
        ).fetchone()
    return dict(row) if row else None


# ── preflight_runs write ──────────────────────────────────────────────────────

def record_preflight(tickets: list[dict], sent_slack: bool = False) -> int:
    """Persist a preflight run result. Returns the new row id."""
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO preflight_runs (ran_at, tickets, sent_slack) VALUES (?,?,?)",
            (_now(), json.dumps(tickets, ensure_ascii=False), 1 if sent_slack else 0),
        )
        row_id = cur.lastrowid
        # Keep only the last 30 runs
        con.execute(
            "DELETE FROM preflight_runs WHERE id NOT IN "
            "(SELECT id FROM preflight_runs ORDER BY ran_at DESC LIMIT 30)"
        )
        return row_id


# ── preflight_runs read ───────────────────────────────────────────────────────

def list_preflight_runs(limit: int = 14) -> list[dict]:
    """Return recent preflight runs, newest-first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM preflight_runs ORDER BY ran_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["tickets"] = json.loads(d["tickets"])
        except Exception:
            d["tickets"] = []
        result.append(d)
    return result


def get_latest_preflight() -> Optional[dict]:
    """Return the most recent preflight run."""
    runs = list_preflight_runs(limit=1)
    return runs[0] if runs else None

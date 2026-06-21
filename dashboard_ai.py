"""
dashboard_ai.py — natural-language Q&A over the audit log.

Flow: question -> Gemini writes a single read-only SQLite SELECT against the
audit_log schema -> we validate it's a safe SELECT -> run it read-only ->
Gemini phrases the answer from the rows. No writes, no arbitrary SQL.
"""

import logging
import re
import sqlite3
import json

logger = logging.getLogger(__name__)

# Columns the model is allowed to know about (audit_log table).
_SCHEMA = """
TABLE audit_log (
  id            INTEGER,
  ticket_key    TEXT,    -- JIRA ticket, e.g. 'MAS-4297'
  client        TEXT,    -- client name, e.g. 'ALDI Sued', 'Kaufland RCS'
  sendout_id    TEXT,
  overall       TEXT,    -- 'PASS' | 'FAIL' | 'ERROR'
  scheduling    TEXT, copy TEXT, footer TEXT, cta TEXT, tags TEXT, images TEXT,  -- per-check 'PASS'/'FAIL'/'NA'/'NO_DATA'
  confidence    INTEGER, -- 0-100, -1 = unknown
  triggered_by  TEXT,    -- 'manual' (AI single) | 'ai' (bulk AI) | 'manual_rule' (rule check) | 'auto' (scheduler)
  user          TEXT,    -- who ran it: 'Gleb Semeniuk','Martina Sesar','Alex Volkonitin','Sergey Denisov', or '🤖 Auto-Audit'
  failed_checks_json TEXT,
  reporter      TEXT,    -- JIRA reporter (client-side requester)
  created_at    TEXT     -- ISO-8601 UTC timestamp
)
"""

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|attach|detach|create|replace|pragma|vacuum|reindex)\b", re.I)


def _gen(api_key: str, model: str, prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(model=model, contents=[prompt])
    return (resp.text or "").strip()


def _clean_sql(raw: str) -> str:
    s = raw.strip()
    # strip ``` fences / language hints
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    # take the first statement only
    s = s.split(";")[0].strip()
    return s


def _is_safe_select(sql: str) -> bool:
    if not sql:
        return False
    if not re.match(r"(?is)^\s*select\b", sql):
        return False
    if _FORBIDDEN.search(sql):
        return False
    return True


def _run_select(db_path: str, sql: str, limit: int = 200):
    # Ensure a row cap
    if not re.search(r"(?is)\blimit\b", sql):
        sql = f"{sql} LIMIT {limit}"
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        cols = [d[0] for d in (cur.description or [])]
        return cols, rows
    finally:
        con.close()


def answer_question(question: str, current_user: str, db_path: str, api_key: str, model: str) -> dict:
    """
    Returns {answer, sql, rows, error}. Never raises for normal failures.
    """
    q = (question or "").strip()
    if not q:
        return {"error": "Empty question."}

    sql_prompt = (
        "You translate a question into ONE read-only SQLite SELECT over this schema. "
        "Output ONLY the SQL — no prose, no markdown, no semicolon.\n\n"
        f"{_SCHEMA}\n"
        f"The person asking is '{current_user}', so 'me'/'I'/'my' refers to user = '{current_user}'.\n"
        "Match user names loosely with LIKE (e.g. user LIKE '%Martina%'). "
        "'checked'/'audited' means rows in audit_log; count distinct ticket_key unless the question is about runs/checks. "
        "Auto-audit is user = '🤖 Auto-Audit'. Dates are ISO strings in created_at; use date() for day comparisons.\n\n"
        f"Question: {q}\nSQL:"
    )
    try:
        sql = _clean_sql(_gen(api_key, model, sql_prompt))
    except Exception as exc:
        logger.warning("dashboard_ai SQL gen failed: %s", exc)
        return {"error": f"AI query generation failed: {exc}"}

    if not _is_safe_select(sql):
        logger.warning("dashboard_ai rejected unsafe SQL: %s", sql)
        return {"error": "Could not build a safe read-only query for that question.", "sql": sql}

    try:
        cols, rows = _run_select(db_path, sql)
    except Exception as exc:
        logger.warning("dashboard_ai query failed: %s | sql=%s", exc, sql)
        return {"error": f"Query failed: {exc}", "sql": sql}

    answer_prompt = (
        "Answer the user's question in one or two short sentences, in English, using ONLY the query result. "
        "Be concrete with numbers. If the result is empty, say no matching data was found.\n\n"
        f"Question: {q}\n"
        f"Result rows (JSON): {json.dumps(rows[:50], ensure_ascii=False)}\n"
        "Answer:"
    )
    try:
        answer = _gen(api_key, model, answer_prompt)
    except Exception as exc:
        answer = ""
        logger.warning("dashboard_ai answer gen failed: %s", exc)

    return {"answer": answer, "sql": sql, "rows": rows[:50]}

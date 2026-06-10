"""
features.py — Five new features:
  1. Scheduled date validation
  2. G-Sheet write-back (validation status + timestamp)
  3. URL reachability check
  4. Bulk export (CSV)
  5. Dashboard data builder

All pure logic — no Streamlit imports.
"""

import csv
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
import pytz
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10   # seconds per URL reachability check
REACHABILITY_DELAY = 0.3  # seconds between checks to be polite


# ─────────────────────────────────────────────────────────────────────────────
# 1. SCHEDULED DATE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_scheduled_date(jira: dict, api: dict) -> dict:
    """
    Compare the scheduled datetime in the JIRA ticket against the DMA API.

    The DMA backend always stores times in CET/Berlin context, so if the
    clock-hour matches we treat it as correct regardless of UTC offset labels.

    Returns:
        {
            "ok": bool,
            "jira_raw": str,
            "api_raw": str,
            "jira_parsed": datetime | None,
            "api_parsed": datetime | None,
            "detail": str,
        }
    """
    jira_raw = str(jira.get("date") or "").strip()
    api_raw  = str(api.get("scheduled_date") or "").strip()

    result = {
        "ok": False,
        "jira_raw": jira_raw,
        "api_raw": api_raw,
        "jira_parsed": None,
        "api_parsed": None,
        "detail": "",
    }

    if not jira_raw or jira_raw in ("None", "null", ""):
        result["detail"] = "No date set in JIRA ticket."
        return result

    if not api_raw or api_raw in ("None", "null", ""):
        result["detail"] = "No scheduled date in DMA API."
        return result

    try:
        jira_dt = dateutil_parser.parse(jira_raw)
        result["jira_parsed"] = jira_dt
    except Exception:
        result["detail"] = f"Could not parse JIRA date: '{jira_raw}'"
        return result

    try:
        api_dt = dateutil_parser.parse(api_raw)
        result["api_parsed"] = api_dt
    except Exception:
        result["detail"] = f"Could not parse API date: '{api_raw}'"
        return result

    # ALDI Portugal special case: DMA time is always 18:00 or 19:00 local — just verify the hour
    if jira.get("_client_timezone") == "Europe/Lisbon":
        api_hour = api_dt.replace(tzinfo=None).hour
        if api_hour in (18, 19):
            result["ok"] = True
            result["detail"] = f"✅ ALDI Portugal sendout at {api_hour:02d}:00 local — accepted"
        else:
            result["ok"] = False
            result["detail"] = f"❌ ALDI Portugal sendout at {api_hour:02d}:xx — expected 18:00 or 19:00"
        return result
    # German clients: DMA Z = CET. JIRA tz-aware → convert to CET → compare.
    # ALDI Portugal: DMA Z = Portugal local (WEST UTC+1 summer). JIRA tz-aware → convert to WEST → compare.

    client_tz_name = jira.get("_client_timezone", "Europe/Berlin")

    try:
        import pytz as _pytz
        cmp_tz = _pytz.timezone(client_tz_name)

        # Convert JIRA tz-aware time to the client's local timezone
        if jira_dt.tzinfo is not None:
            jira_cmp = jira_dt.astimezone(cmp_tz).replace(tzinfo=None)
        else:
            jira_cmp = jira_dt.replace(tzinfo=None)

        # API time: treat as client local clock (strip Z, no conversion)
        api_cmp = api_dt.replace(tzinfo=None)

    except Exception:
        jira_cmp = jira_dt.replace(tzinfo=None)
        api_cmp  = api_dt.replace(tzinfo=None)

    jira_date = jira_cmp.date()
    api_date  = api_cmp.date()
    date_ok   = (jira_date == api_date)

    diff_minutes = abs((jira_cmp - api_cmp).total_seconds() / 60)
    time_ok = diff_minutes <= 40

    result["ok"] = date_ok and time_ok

    if result["ok"]:
        result["detail"] = (
            f"✅ JIRA {jira_cmp.strftime('%Y-%m-%d %H:%M')} ≈ API "
            f"{api_cmp.strftime('%Y-%m-%d %H:%M')} (CET) "
            f"(diff: {int(diff_minutes)}min)"
        )
    else:
        mismatches = []
        if not date_ok:
            mismatches.append(f"date JIRA={jira_date} API={api_date}")
        if not time_ok:
            mismatches.append(
                f"time JIRA={jira_cmp.strftime('%H:%M')} "
                f"API={api_cmp.strftime('%H:%M')} (CET) "
                f"(diff: {int(diff_minutes)}min, tolerance: 40min)"
            )
        result["detail"] = "❌ " + " | ".join(mismatches)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. G-SHEET WRITE-BACK
# ─────────────────────────────────────────────────────────────────────────────

def gsheet_write_validation_status(
    spreadsheet_id: str,
    sheet_name: str,
    ticket_key: str,
    status: str,
    validator_name: str,
    gsheet_data: list[dict],
    credentials_json: dict,
) -> tuple[bool, str]:
    """
    Write validation status + timestamp back to the G-Sheet row matching
    *ticket_key* in the JIRA link column.

    Requires google-auth and gspread installed, and a service account JSON.
    Returns (success, message).
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(credentials_json, scopes=scopes)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

        # Find the row number
        all_values = sheet.get_all_values()
        if not all_values:
            return False, "Sheet appears empty."

        headers    = all_values[0]
        jira_col   = _find_col(headers, "Link to the ticket in JIRA")
        status_col = _find_col(headers, "Validation Status")
        ts_col     = _find_col(headers, "Validated At")
        by_col     = _find_col(headers, "Validated By")

        if jira_col is None:
            return False, "Could not find 'Link to the ticket in JIRA' column."

        row_idx = None
        for i, row in enumerate(all_values[1:], start=2):
            cell = row[jira_col] if jira_col < len(row) else ""
            if ticket_key in cell:
                row_idx = i
                break

        if row_idx is None:
            return False, f"No row found for ticket {ticket_key}."

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        updates = []
        if status_col is not None:
            updates.append(gspread.Cell(row_idx, status_col + 1, status))
        if ts_col is not None:
            updates.append(gspread.Cell(row_idx, ts_col + 1, now_str))
        if by_col is not None:
            updates.append(gspread.Cell(row_idx, by_col + 1, validator_name))

        if updates:
            sheet.update_cells(updates)

        return True, f"Row {row_idx} updated: {status} at {now_str}"

    except ImportError:
        return False, "gspread / google-auth not installed. Run: pip install gspread google-auth"
    except Exception as exc:
        logger.error("gsheet_write_validation_status failed: %s", exc)
        return False, str(exc)


def _find_col(headers: list[str], name: str) -> int | None:
    """Return 0-based column index of *name* in *headers*, or None."""
    for i, h in enumerate(headers):
        if h.strip().lower() == name.strip().lower():
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 3. URL REACHABILITY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_url_reachability(urls: list[str]) -> list[dict]:
    """
    HTTP-GET each URL (HEAD first, fall back to GET) and return a list of:
        {
            "url": str,
            "ok": bool,
            "status_code": int | None,
            "final_url": str,     # after redirects
            "error": str,
        }

    Skips symbolic placeholders (@leaflet_url_path etc.) and media files.
    """
    results = []
    seen: set[str] = set()

    for url in urls:
        url = str(url).strip()

        # Skip placeholders and media
        if not url or url.startswith("@") or url in seen:
            continue
        if not url.startswith("http"):
            continue
        if any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4")):
            continue

        seen.add(url)
        entry = {"url": url, "ok": False, "status_code": None, "final_url": url, "error": ""}

        try:
            # HEAD first (cheap)
            resp = requests.head(
                url,
                timeout=HTTP_TIMEOUT,
                allow_redirects=True,
                headers={"User-Agent": "360dialog-Validator/1.0"},
            )
            entry["status_code"] = resp.status_code
            entry["final_url"]   = resp.url
            entry["ok"]          = resp.status_code < 400

            # Some servers reject HEAD — fall back to GET on 4xx/5xx
            if not entry["ok"]:
                resp2 = requests.get(
                    url,
                    timeout=HTTP_TIMEOUT,
                    allow_redirects=True,
                    headers={"User-Agent": "360dialog-Validator/1.0"},
                    stream=True,   # don't download body
                )
                resp2.close()
                entry["status_code"] = resp2.status_code
                entry["final_url"]   = resp2.url
                entry["ok"]          = resp2.status_code < 400

        except requests.Timeout:
            entry["error"] = "Timed out"
        except requests.ConnectionError as exc:
            entry["error"] = f"Connection error: {exc}"
        except Exception as exc:
            entry["error"] = str(exc)

        results.append(entry)
        time.sleep(REACHABILITY_DELAY)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. BULK EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_bulk_results_csv(results: list) -> bytes:
    """
    Convert a list of BulkTicketResult objects to a UTF-8 CSV byte string
    ready to be passed to st.download_button.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow([
        "Ticket", "Client", "Sendout ID", "Mode", "Status",
        "Issues Found", "Error", "Report Summary",
    ])

    for r in results:
        # Condense report to first 300 chars for the CSV
        report_summary = (r.report or "")[:300].replace("\n", " ")
        if r.checks:
            report_summary = " | ".join(
                f"{'✅' if c['ok'] else '❌'} {c['label']}"
                for c in r.checks
            )
        writer.writerow([
            r.ticket_key,
            r.client,
            r.sendout_id or "",
            getattr(r, "mode", "ai"),
            r.status,
            r.issues_found,
            r.error_msg or "",
            report_summary,
        ])

    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility


# ─────────────────────────────────────────────────────────────────────────────
# 5. DASHBOARD DATA
# ─────────────────────────────────────────────────────────────────────────────

def build_dashboard_data(validation_log: list[dict]) -> dict:
    """
    Compute all dashboard stats from the in-memory validation log.
    Returns a rich dict consumed by the Dashboard UI.
    """
    from collections import Counter

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_start = (datetime.now(timezone.utc).date() - __import__("datetime").timedelta(days=6)).isoformat()

    empty = {
        "total": 0, "passed": 0, "failed": 0, "errors": 0, "pass_rate": 0.0,
        "today_total": 0, "today_passed": 0, "today_failed": 0, "today_pass_rate": 0.0, "today_ai": 0,
        "week_total": 0, "week_passed": 0, "week_failed": 0, "week_pass_rate": 0.0,
        "ai_total": 0, "ai_passed": 0, "ai_failed": 0, "ai_pass_rate": 0.0,
        "ai_auto": 0, "ai_manual": 0,
        "ai_avg_confidence": None, "ai_low_confidence": 0,
        "conf_90plus": 0, "conf_70_89": 0, "conf_60_69": 0, "conf_below60": 0,
        "top_ai_failed_checks": [],
        "top_failed_checks": [],
        "by_client": {}, "by_user": {},
        "recent": [], "daily_counts": {},
    }
    if not validation_log:
        return empty

    total   = len(validation_log)
    passed  = sum(1 for e in validation_log if e.get("status") == "passed")
    failed  = sum(1 for e in validation_log if e.get("status") == "failed")
    errors  = sum(1 for e in validation_log if e.get("status") == "error")
    pass_rate = round(passed / total * 100, 1) if total else 0.0

    # ── Today ────────────────────────────────────────────────────────────────
    today_log = [e for e in validation_log if e.get("timestamp", "")[:10] == today_str]
    t_total  = len(today_log)
    t_passed = sum(1 for e in today_log if e.get("status") == "passed")
    t_failed = sum(1 for e in today_log if e.get("status") == "failed")
    t_ai     = sum(1 for e in today_log if e.get("mode") == "ai")
    t_rate   = round(t_passed / t_total * 100, 1) if t_total else 0.0

    # ── This week (last 7 days) ───────────────────────────────────────────────
    week_log  = [e for e in validation_log if e.get("timestamp", "")[:10] >= week_start]
    w_total   = len(week_log)
    w_passed  = sum(1 for e in week_log if e.get("status") == "passed")
    w_failed  = sum(1 for e in week_log if e.get("status") == "failed")
    w_rate    = round(w_passed / w_total * 100, 1) if w_total else 0.0

    # ── AI audit stats ────────────────────────────────────────────────────────
    ai_log    = [e for e in validation_log if e.get("mode") == "ai"]
    ai_total  = len(ai_log)
    ai_passed = sum(1 for e in ai_log if e.get("status") == "passed")
    ai_failed = sum(1 for e in ai_log if e.get("status") == "failed")
    ai_pass_rate = round(ai_passed / ai_total * 100, 1) if ai_total else 0.0
    ai_auto   = sum(1 for e in ai_log if (e.get("user") or "") == "🤖 Auto-Audit")
    ai_manual = ai_total - ai_auto
    confidences = [e["confidence"] for e in ai_log if e.get("confidence") is not None]
    ai_avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else None
    ai_low_conf = sum(1 for c in confidences if c < 60)
    # Confidence distribution buckets
    conf_90plus  = sum(1 for c in confidences if c >= 90)
    conf_70_89   = sum(1 for c in confidences if 70 <= c < 90)
    conf_60_69   = sum(1 for c in confidences if 60 <= c < 70)
    conf_below60 = sum(1 for c in confidences if c < 60)
    # Top AI-specific failed checks
    ai_check_counter: Counter = Counter()
    for e in ai_log:
        for chk in e.get("failed_checks", []):
            if chk:
                ai_check_counter[chk] += 1
    top_ai_failed = [{"label": k, "count": v} for k, v in ai_check_counter.most_common(6)]

    # ── Most common failed checks ─────────────────────────────────────────────
    check_counter: Counter = Counter()
    for e in validation_log:
        for chk in e.get("failed_checks", []):
            if chk:
                check_counter[chk] += 1
    top_failed = [{"label": k, "count": v} for k, v in check_counter.most_common(8)]

    # ── Per-client breakdown ──────────────────────────────────────────────────
    by_client: dict = {}
    for e in validation_log:
        c = e.get("client") or "Unknown"
        r = by_client.setdefault(c, {"total": 0, "passed": 0, "failed": 0, "issues": 0})
        r["total"] += 1
        if e.get("status") == "passed": r["passed"] += 1
        elif e.get("status") == "failed": r["failed"] += 1
        r["issues"] += e.get("issues", 0)

    # ── Per-user breakdown ────────────────────────────────────────────────────
    by_user: dict = {}
    for e in validation_log:
        u = e.get("user") or "—"
        r = by_user.setdefault(u, {"total": 0, "passed": 0, "failed": 0})
        r["total"] += 1
        if e.get("status") == "passed": r["passed"] += 1
        elif e.get("status") == "failed": r["failed"] += 1

    # ── Daily counts (last 14 days) ───────────────────────────────────────────
    daily: dict = {}
    for e in validation_log:
        day = e.get("timestamp", "")[:10]
        if day:
            r = daily.setdefault(day, {"passed": 0, "failed": 0})
            if e.get("status") == "passed": r["passed"] += 1
            elif e.get("status") == "failed": r["failed"] += 1

    recent = sorted(validation_log, key=lambda x: x.get("timestamp", ""), reverse=True)[:30]

    return {
        "total": total, "passed": passed, "failed": failed, "errors": errors, "pass_rate": pass_rate,
        "today_total": t_total, "today_passed": t_passed, "today_failed": t_failed,
        "today_pass_rate": t_rate, "today_ai": t_ai,
        "week_total": w_total, "week_passed": w_passed, "week_failed": w_failed, "week_pass_rate": w_rate,
        "ai_total": ai_total, "ai_passed": ai_passed, "ai_failed": ai_failed,
        "ai_pass_rate": ai_pass_rate,
        "ai_auto": ai_auto, "ai_manual": ai_manual,
        "ai_avg_confidence": ai_avg_conf, "ai_low_confidence": ai_low_conf,
        "conf_90plus": conf_90plus, "conf_70_89": conf_70_89,
        "conf_60_69": conf_60_69, "conf_below60": conf_below60,
        "top_ai_failed_checks": top_ai_failed,
        "top_failed_checks": top_failed,
        "by_client": by_client, "by_user": by_user,
        "recent": recent, "daily_counts": daily,
    }


def record_validation(
    ticket_key: str,
    client: str,
    status: str,
    mode: str,
    issues: int,
    approved: bool,
    log: list[dict],
    user: str = "",
    failed_checks: list | None = None,
    confidence: int | None = None,
) -> list[dict]:
    """
    Append a validation event to *log* and return it.
    Call this after every successful validation run.
    """
    log.append({
        "ticket_key":   ticket_key,
        "client":       client,
        "status":       status,
        "mode":         mode,
        "issues":       issues,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "approved":     approved,
        "user":         user or "",
        "failed_checks": failed_checks or [],
        "confidence":   confidence,
    })
    # Cap at 1000 entries so the in-memory log doesn't grow unboundedly.
    if len(log) > 1000:
        del log[:-1000]
    return log

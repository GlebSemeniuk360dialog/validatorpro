"""
server.py — FastAPI backend for Validator Pro.
Wraps the existing Python business logic and serves the React SPA.
Run with:  python -m uvicorn server:app --host 0.0.0.0 --port 8502 --reload
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Business logic imports ────────────────────────────────────────────────────
from config import CLIENT_CONFIGS, CLIENT_ALIASES, GSHEET_COLS, GSHEET_DEFAULT_URL
from api_client import (
    fetch_account_leaflets,
    fetch_all_servicedesk_issues,
    fetch_api_data,
    fetch_api_key_via_dma,
    fetch_jira_tickets_jql,
    fetch_pending_sendouts,
    fetch_template_data,
    fetch_ticket_data,
    approve_ticket_jira,
    write_ai_status_to_jira,
)
from ai_audit import build_comparison_data, run_ai_audit
from ai_examples import ExamplesLibrary, extract_snippet
import dataclasses
from bulk_validator import BulkTicketResult, run_bulk_validation, run_bulk_regular_check
from features import build_dashboard_data, record_validation, validate_scheduled_date
from parsers import pick_carousel_parser
from schedule import fetch_gsheet_data_csv, get_client_schedule_wide
import tag_registry as _reg
import client_config as _cfg
import audit_log as _al
import user_db as _udb
from ui_renderer import build_results_html
from utils import (
    check_tags,
    detect_client_from_text,
    extract_all_tags,
    extract_api_urls_advanced,
    extract_urls,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────────────────────
JIRA_SERVER   = "https://360dialog.atlassian.net"
JIRA_EMAIL    = "gleb.semeniuk@360dialog.com"
JIRA_TOKEN    = os.environ.get("JIRA_TOKEN", "")
API_TOKEN     = os.environ.get("DMA_API_TOKEN", "")
GEMINI_KEY         = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL       = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")        # single-ticket audit
GEMINI_BULK_MODEL  = os.environ.get("GEMINI_BULK_MODEL", "gemini-2.5-flash") # bulk AI — faster & cheaper
# Freestyle (non-standard ticket) always uses the pro model for deeper reasoning.
GEMINI_PRO_MODEL   = os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
APP_BASE_URL  = os.environ.get("APP_BASE_URL", "http://localhost:8502")

# ── Auth ──────────────────────────────────────────────────────────────────────
_USERS = {
    "gleb":    ("Gleb Semeniuk",   "0df575df0654539e8fc2e39038cd153f7f012ce5cee3b2bc4301b4a7ea9738bb"),
    "martina": ("Martina Sesar",   "3127e30f336fbcc6c6ee3f87c2e4aa3509120b48fa3b841cf91eb91512c49824"),
    "alex":    ("Alex Volkonitin", "554c22e0e5bc5d80b4a0015eddfc4a2556afb3879b98e8f1123652070a26b993"),
}
_sessions: dict[str, dict] = {}
SESSION_TTL = 8 * 3600

def _seed_validation_log_from_db(limit: int = 500) -> list[dict]:
    """Seed the in-memory validation log from the SQLite audit_log DB on startup."""
    try:
        rows = _al.list_audits(limit=limit)
        log: list[dict] = []
        for r in reversed(rows):  # oldest first
            log.append({
                "ticket_key":    r.get("ticket_key", ""),
                "client":        r.get("client", ""),
                "status":        "passed" if r.get("overall") == "PASS" else "failed" if r.get("overall") == "FAIL" else "error",
                "mode":          "ai" if r.get("triggered_by") in ("ai", "bulk_ai", "auto") else "regular",
                "issues":        0,
                "timestamp":     r.get("created_at", ""),
                "approved":      False,
                "user":          r.get("user") or ("🤖 Auto-Audit" if r.get("triggered_by") == "auto" else ""),
                "failed_checks": r.get("failed_checks_json_parsed") or [k for k in ("scheduling","copy","footer","cta","tags","images") if r.get(k) == "FAIL"],
                "confidence":    r.get("confidence"),
            })
        return log
    except Exception as exc:
        logger.warning("Could not seed validation log from DB: %s", exc)
        return []

_validation_log: list[dict] = _seed_validation_log_from_db()
_gsheet_cache: list[dict] = []
_gsheet_fetched_at: float = 0.0
_queue_cache: list[dict] = []
_queue_fetched_at: float = 0.0

# sendout_id → {ticket_key, client, issues, confidence, ts}
_audited_sendouts: dict[str, dict] = {}

# ── Slack notifications ───────────────────────────────────────────────────────

def _extract_failed_checks(ai_text: str) -> list[str]:
    """Pull section names that have a ❌ near them from the AI report text."""
    raw = re.findall(
        r'(?:#{1,3}\s*)?(?:\d+\.\s*)?\*{0,2}([A-Za-z][^*\n❌]{2,50}?)\*{0,2}[\s:]*❌',
        ai_text,
    )
    out = []
    for m in raw:
        m = re.sub(r'^\d+[\.)\s]+', '', m.strip().rstrip(':').strip())
        if m and "overall" not in m.lower() and "status" not in m.lower() and len(m) > 3:
            out.append(m)
    return out or [f"{ai_text.count('❌')} issue(s) found"]


def _send_slack_alert(
    ticket_key: str,
    client: str,
    mode: str,
    issues: int,
    user_name: str = "Validator",
    failed_checks: list | None = None,
    sendout_id: str = "",
    webhook: str = "",
) -> None:
    """Send a Slack notification when an AI audit finds issues."""
    url = webhook or SLACK_WEBHOOK
    if not url:
        return
    try:
        import json as _json
        import urllib.parse as _up
        import urllib.request as _ur

        ticket_url = f"{JIRA_SERVER.rstrip('/')}/browse/{ticket_key}"
        params = {"ticket": ticket_key, "client": client}
        if sendout_id:
            params["sendout"] = sendout_id
        app_link = f"{APP_BASE_URL.rstrip('/')}?{_up.urlencode(params)}"

        checks_text = (
            "\n".join(f"• {c}" for c in (failed_checks or [])[:10])
            if failed_checks
            else f"{issues} issue(s) found"
        )

        payload = {
            "text": "<!here> ❌ *AI Audit Failed — Manual Review Required*",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "❌ AI Audit Failed — Manual Review Required"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "<!here> Please review this sendout manually."},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Ticket:*\n<{ticket_url}|{ticket_key}>"},
                        {"type": "mrkdwn", "text": f"*Client:*\n{client}"},
                        {"type": "mrkdwn", "text": f"*Mode:*\n{mode}"},
                        {"type": "mrkdwn", "text": f"*Checked by:*\n{user_name}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*❌ Failed checks:*\n{checks_text}"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in Validator"},
                            "url": app_link,
                            "style": "danger",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in JIRA"},
                            "url": ticket_url,
                        },
                    ],
                },
            ],
        }

        req = _ur.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        _ur.urlopen(req, timeout=5)
        logger.info("SLACK_ALERT\t%s %s — %d issue(s)", ticket_key, client, issues)
    except Exception as exc:
        logger.warning("Slack alert failed: %s", exc)


def _send_slack_bulk_alert(
    failed_tickets: list[dict],
    user_name: str = "Validator",
    webhook: str = "",
) -> None:
    """Send a single Slack notification summarising all failed tickets from a bulk AI check."""
    url = webhook or SLACK_WEBHOOK
    if not url or not failed_tickets:
        return
    try:
        import json as _json
        import urllib.parse as _up
        import urllib.request as _ur

        total = len(failed_tickets)
        header_text = f"❌ AI Bulk Check — {total} ticket{'s' if total > 1 else ''} failed"

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<!here> *{total} sendout{'s' if total > 1 else ''}* need manual review — checked by *{user_name}*."},
            },
        ]

        for item in failed_tickets:
            ticket_key = item["ticket_key"]
            client = item["client"]
            sendout_id = item.get("sendout_id", "")
            failed_checks = item.get("failed_checks", [])
            issues = item.get("issues", 0)

            ticket_url = f"{JIRA_SERVER.rstrip('/')}/browse/{ticket_key}"
            params = {"ticket": ticket_key, "client": client}
            if sendout_id:
                params["sendout"] = sendout_id
            app_link = f"{APP_BASE_URL.rstrip('/')}?{_up.urlencode(params)}"

            checks_text = (
                ", ".join(f"_{c}_" for c in failed_checks[:6])
                if failed_checks
                else f"{issues} issue(s)"
            )

            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*<{ticket_url}|{ticket_key}>* — {client}\n"
                        f"❌ {checks_text}"
                    ),
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open in Validator"},
                    "url": app_link,
                    "style": "danger",
                },
            })

        payload = {
            "text": f"<!here> {header_text}",
            "blocks": blocks,
        }

        req = _ur.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        _ur.urlopen(req, timeout=8)
        logger.info("SLACK_BULK_ALERT\t%d failed ticket(s) — %s", total, user_name)
    except Exception as exc:
        logger.warning("Slack bulk alert failed: %s", exc)


def _send_slack_approval(ticket_key: str, user_name: str, approver: str, webhook: str = "") -> None:
    """Post an approval confirmation to Slack."""
    url = webhook or SLACK_WEBHOOK
    if not url:
        return
    try:
        import json as _json
        import urllib.request as _ur
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%H:%M")
        payload = {"text": f"✅ {ticket_key} approved by {user_name} ({approver}) at {ts}"}
        req = _ur.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        _ur.urlopen(req, timeout=5)
    except Exception as exc:
        logger.warning("Slack approval notification failed: %s", exc)


# ── Utility helpers (extracted from app.py) ───────────────────────────────────
_TAG_EMPTY = {"none", "-", "—", "n/a", ""}


def _norm_tags(s: str) -> str:
    parts = re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p and p.lower() not in _TAG_EMPTY:
            cleaned.append(p)
    return ", ".join(cleaned)


def _strip_slide_labels(text: str) -> str:
    m = re.search(r'(?im)^[\s*]*(?:Slide|Slider)\s*\d+\s*:', text)
    if m:
        return text[:m.start()].strip()
    return text.strip()


# _collect_custom_carousel_images was moved to audit_prep.py
from audit_prep import _collect_custom_carousel_images  # keep name for any remaining callers


def _ticket_client(issue: dict) -> str:
    fields = issue["fields"]
    summary = fields.get("summary", "")
    desc = fields.get("description") or ""
    text = f"{summary} {desc}".strip()
    reporter = fields.get("reporter") or {}
    reporter_email = (reporter.get("emailAddress") or "").lower()
    if "aldi-sued.de" in reporter_email or "aldi-sud.de" in reporter_email:
        return "ALDI Sued"
    if "aldi-pt.pt" in reporter_email or "aldi.pt" in reporter_email:
        return "ALDI Portugal"
    if "aldi-nord.de" in reporter_email:
        return "ALDI Nord"
    if "aldi-ch.ch" in reporter_email or "aldi.ch" in reporter_email:
        return "ALDI Suisse"
    if "aldi.it" in reporter_email or "aldi-italy.it" in reporter_email:
        return "ALDI Italy"
    if "kaufland.de" in reporter_email:
        # Prefer the explicit "WABA or RCS" JIRA field (customfield_16693) over text sniffing
        _wr_raw = fields.get("customfield_16693")
        if isinstance(_wr_raw, list) and _wr_raw:
            _wr_val = (_wr_raw[0].get("value", "") if isinstance(_wr_raw[0], dict) else str(_wr_raw[0])).upper()
        else:
            _wr_val = str(_wr_raw or "").upper()
        if "RCS" in _wr_val:
            return "Kaufland RCS"
        if "WABA" in _wr_val:
            return "Kaufland WABA"
        # Fallback: text-based detection for older tickets without the field
        return "Kaufland RCS" if "rcs" in text.lower() else "Kaufland WABA"
    if "penny.at" in reporter_email:
        return "PENNY Austria"
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("sonntag", "reminder", "prospekt living",
                                        "prospekt women", "prospekt grilling",
                                        "prospekt haushalt", "prospekt familien",
                                        "prospekt elektronik", "prospekt garten",
                                        "whatsapp chat prospekt")):
        return "ALDI Sued"
    return detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"


def _hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def _friendly_exc(exc: Exception) -> str:
    """
    Return a short, human-readable version of an exception string.
    Strips verbose Python dotted-class prefixes and long URLs.
    """
    s = str(exc)
    # Strip dotted class prefix like "google.api_core.exceptions.ResourceExhausted: "
    s = re.sub(r'^(?:[a-zA-Z_][a-zA-Z0-9_]*\.)+[a-zA-Z_][a-zA-Z0-9_]*:\s*', '', s)
    # Strip "Please retry or report in https://..." fragments
    s = re.sub(r'[Pp]lease retry or report in\s+https?://\S*', 'please try again later', s)
    # Strip bare URLs
    s = re.sub(r'https?://\S+', '', s).strip()
    # Collapse repeated whitespace / punctuation left by URL removal
    s = re.sub(r'\s{2,}', ' ', s).strip().rstrip('. ')
    # Truncate
    if len(s) > 280:
        s = s[:277] + '…'
    return s or str(exc)[:280]


def _get_session(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    session = _sessions.get(token)
    if not session or session["expires"] < time.time():
        _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired")
    return session


def _require_admin(authorization: Optional[str]) -> dict:
    session = _get_session(authorization)
    if not session.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return session


def _cached_queue() -> list[dict]:
    """Return raw JIRA issue dicts (for bulk_validator which reads issue['fields'])."""
    global _queue_cache, _queue_fetched_at
    if not _queue_cache or (time.time() - _queue_fetched_at) > 120:
        try:
            _queue_cache = fetch_all_servicedesk_issues(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN)
            _queue_fetched_at = time.time()
        except Exception as exc:
            logger.warning("Queue cache refresh failed: %s", exc)
    return _queue_cache


def _normalize_issue(issue: dict) -> dict:
    """
    Convert a raw JIRA issue dict (with 'fields' sub-dict) into a flat dict
    with 'key', 'summary', 'client', 'date', 'status' — as used by preflight,
    auto-audit, and dashboard.  Safe to call on already-normalized dicts too.
    """
    if "fields" not in issue:
        # Already normalized
        return issue
    fields = issue.get("fields", {})
    client = _ticket_client(issue)
    summary = fields.get("summary", "")
    # ALDI Portugal: append segment to summary for task matching
    if client == "ALDI Portugal":
        seg_raw = fields.get("customfield_14287")
        if isinstance(seg_raw, dict):
            seg = seg_raw.get("value") or seg_raw.get("name") or ""
        elif seg_raw is not None:
            seg = str(seg_raw)
        else:
            seg = ""
        if seg and seg.lower() not in summary.lower():
            summary = f"{summary} {seg}".strip()
    _ai_raw = fields.get("customfield_16417")
    if isinstance(_ai_raw, list) and _ai_raw:
        _ai_status = (_ai_raw[0].get("value") if isinstance(_ai_raw[0], dict) else str(_ai_raw[0]))
    else:
        _ai_status = None
    if not _ai_status:
        _db = _al.get_audit_for_ticket(issue["key"])
        if _db:
            _ai_status = _db.get("overall")
    return {
        "key":       issue["key"],
        "summary":   summary,
        "client":    client,
        "date":      str(fields.get("customfield_12665", ""))[:10],
        "status":    fields.get("status", {}).get("name", ""),
        "ai_status": _ai_status,
    }


def _normalized_queue() -> list[dict]:
    """Return queue as flat normalized dicts (for preflight/auto-audit/dashboard)."""
    return [_normalize_issue(i) for i in _cached_queue()]


def _gsheet() -> list[dict]:
    global _gsheet_cache, _gsheet_fetched_at
    if not _gsheet_cache or (time.time() - _gsheet_fetched_at) > 300:
        try:
            _gsheet_cache = fetch_gsheet_data_csv(GSHEET_DEFAULT_URL)
            _gsheet_fetched_at = time.time()
        except Exception as exc:
            logger.warning("G-Sheet fetch failed: %s", exc)
    return _gsheet_cache


# ── Core audit data preparation (mirrors _execute_ai_audit from app.py) ──────

def _prepare_audit_data(api: dict, tmpl: Optional[dict], leaflet_data: list, jira: dict, client: str):
    """
    Thin wrapper around audit_prep.extract_dma_components().
    Returns the same tuple as before so all call-sites remain unchanged:
        (tmpl_body, tmpl_footer, tmpl_buttons, dma_carousel_texts,
         dma_image_urls, tag_str, api_urls, rcs_cards)
    """
    from audit_prep import extract_dma_components
    d = extract_dma_components(api=api, tmpl=tmpl, leaflet_data=leaflet_data,
                               jira=jira, client=client)
    return (
        d["tmpl_body"],
        d["tmpl_footer"],
        d["tmpl_buttons"],
        d["dma_carousel_texts"],
        d["dma_image_urls"],
        d["tag_str"],
        d["api_urls"],
        d["rcs_cards"],
    )


def _fetch_core_data(client: str, ticket_key: str, sendout_id: str,
                     leaflet_url: str = "", gsheet_tags: str = "", exclude_tags: str = ""):
    """Fetch JIRA + DMA API + template + leaflet data. Returns (j_data, a_data, t_data, leaflet_data)."""
    j_data = fetch_ticket_data(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, ticket_key)
    if not j_data:
        raise HTTPException(status_code=404, detail="Ticket not found in JIRA")

    a_data = fetch_api_data(API_TOKEN, sendout_id)
    if not a_data or "error_code" in a_data:
        err = a_data or {}
        raise HTTPException(
            status_code=404,
            detail=f"Sendout not found ({err.get('error_code', '')}): {err.get('error_msg', '')}"
        )

    t_name = a_data.get("template_name") or (a_data.get("template") or {}).get("name")
    try:
        waba_key = fetch_api_key_via_dma(API_TOKEN, a_data.get("account_id"))
        t_data = fetch_template_data(waba_key, t_name) if (t_name and waba_key) else None
    except Exception:
        t_data = None

    if leaflet_url:
        j_data["leaflet_url"] = leaflet_url
    if gsheet_tags:
        j_data["gsheet_tags"] = gsheet_tags
    if exclude_tags:
        j_data["gsheet_exclude_tags"] = exclude_tags

    leaflet_data: list = []
    components_str = str(a_data.get("component_parameters", []))
    has_leaflet = (
        "leaflet" in components_str
        or isinstance(a_data.get("leaflet_filter"), dict)
        or "leaflet" in str(a_data.get("google_rcs_content", ""))
    )
    if has_leaflet:
        try:
            leaflet_data = fetch_account_leaflets(
                API_TOKEN, a_data.get("account_id"), a_data.get("scheduled_date", "")
            )
        except Exception:
            pass

    # Only run regex parser if the Forms API didn't already populate parsed_carousel
    # (fetch_ticket_data sets it directly from structured form answers when available)
    if not j_data.get("parsed_carousel"):
        j_data["parsed_carousel"] = pick_carousel_parser(str(j_data.get("description", "")), client)

    return j_data, a_data, t_data, leaflet_data


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Validator Pro API")

# Initialise tag-registry SQLite DB on startup (no-op if already exists)
_reg.init_db()

# Initialise client-config SQLite DB, seed from config.py on first run
_cfg.init_db(CLIENT_CONFIGS, CLIENT_ALIASES)
_cfg.apply_to_memory(CLIENT_CONFIGS, CLIENT_ALIASES)

# Initialise audit log and user DB
_al.init_db()
_udb.init_db(_USERS)

# Initialise few-shot examples library
_examples_lib = ExamplesLibrary()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_BASE = os.path.dirname(__file__)
_UI_DIR     = os.path.join(_BASE, "validator-pro-design-system", "project", "ui_kits", "validator-pro")
_ASSETS_DIR = os.path.join(_BASE, "validator-pro-design-system", "project", "assets")
_STATIC_DIR = os.path.join(_BASE, "static")

if os.path.isdir(_UI_DIR):
    app.mount("/ui", StaticFiles(directory=_UI_DIR), name="ui")
if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


_MOBILE_UA = ("android", "iphone", "ipad", "ipod", "mobile", "webos", "windows phone", "blackberry")

def _is_mobile_ua(request: Request) -> bool:
    ua = request.headers.get("user-agent", "").lower()
    return any(kw in ua for kw in _MOBILE_UA)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, force: str = ""):
    """Serve desktop SPA; auto-redirect mobile browsers unless force=desktop."""
    if force != "desktop" and _is_mobile_ua(request):
        return RedirectResponse("/mobile", status_code=302)
    path = os.path.join(_STATIC_DIR, "index.html")
    if not os.path.exists(path):
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    return HTMLResponse(
        open(path, encoding="utf-8").read(),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/mobile", response_class=HTMLResponse)
async def mobile(request: Request, force: str = ""):
    """Serve mobile SPA; auto-redirect desktop browsers unless force=mobile."""
    if force != "mobile" and not _is_mobile_ua(request):
        return RedirectResponse("/", status_code=302)
    path = os.path.join(_STATIC_DIR, "mobile.html")
    if not os.path.exists(path):
        return HTMLResponse("<h1>mobile.html not found</h1>", status_code=404)
    return HTMLResponse(open(path, encoding="utf-8").read())


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    username = req.username.strip().lower()
    user = _udb.authenticate(username, req.password)
    if not user:
        # Fallback: check legacy hardcoded _USERS (so existing sessions survive the migration)
        entry = _USERS.get(username)
        if not entry or not hmac.compare_digest(_hash_pwd(req.password), entry[1]):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        user = {"username": username, "display_name": entry[0], "is_admin": username == "gleb", "active": 1}
    token = secrets.token_hex(32)
    _sessions[token] = {
        "user":     user["username"],
        "name":     user["display_name"],
        "is_admin": bool(user.get("is_admin")),
        "expires":  time.time() + SESSION_TTL,
    }
    logger.info("LOGIN\t%s (admin=%s)", user["display_name"], user.get("is_admin"))
    return {"token": token, "name": user["display_name"], "is_admin": bool(user.get("is_admin"))}


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        _sessions.pop(authorization.split(" ", 1)[1], None)
    return {"ok": True}


# ── Queue ─────────────────────────────────────────────────────────────────────

@app.get("/api/queue")
async def get_queue(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    try:
        issues = fetch_all_servicedesk_issues(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"JIRA fetch failed: {exc}")
    rows = []
    for issue in issues:
        fields = issue["fields"]
        client = _ticket_client(issue)
        summary = fields.get("summary", "")
        if client == "ALDI Portugal":
            seg_raw = fields.get("customfield_14287")
            if isinstance(seg_raw, dict):
                seg = seg_raw.get("value") or seg_raw.get("name") or ""
            elif seg_raw is not None:
                seg = str(seg_raw)
            else:
                seg = ""
            if seg and seg.lower() not in summary.lower():
                summary = f"{summary} {seg}".strip()
        # AI audit status — from JIRA field first, then our internal DB as fallback
        _ai_jira_raw = fields.get("customfield_16417")
        if isinstance(_ai_jira_raw, list) and _ai_jira_raw:
            _ai_status = (_ai_jira_raw[0].get("value") if isinstance(_ai_jira_raw[0], dict) else str(_ai_jira_raw[0]))
        else:
            _ai_status = None
        if not _ai_status:
            _db_audit = _al.get_audit_for_ticket(issue["key"])
            if _db_audit:
                _ai_status = _db_audit.get("overall")  # "PASS" or "FAIL"

        rows.append({
            "key":       issue["key"],
            "summary":   summary,
            "client":    client,
            "date":      str(fields.get("customfield_12665", ""))[:10],
            "status":    fields.get("status", {}).get("name", ""),
            "ai_status": _ai_status,   # "Approved", "Rejected", "PASS", "FAIL", or None
        })
    rows.sort(key=lambda r: r["date"] or "0000", reverse=True)
    return rows


# ── Sendouts ──────────────────────────────────────────────────────────────────

@app.get("/api/sendouts/{client}")
async def get_sendouts(client: str, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    cfg = CLIENT_CONFIGS.get(client, {})
    account_id = cfg.get("account_id")
    if not account_id:
        return []
    try:
        tasks = fetch_pending_sendouts(API_TOKEN, account_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DMA fetch failed: {exc}")
    # Name patterns that are system tasks, not WhatsApp sendouts — never show these
    _SYSTEM_NAME_PATTERNS = (
        "load shops", "load leaflet", "load store", "load data",
        "test sendout", "test send", "[test]", "dummy",
    )
    _INACTIVE_STATUSES = {"disabled", "cancelled", "canceled", "draft", "inactive", "deleted", "archived"}

    result = []
    for t in tasks:
        task_id = str(t.get("id") or t.get("task_id") or t.get("sendout_id") or "")
        if not task_id:
            continue
        name = str(t.get("name") or t.get("campaign_name") or t.get("task_name")
                   or t.get("title") or t.get("sendout_name") or "")
        name_lower = name.lower()

        # Skip system tasks (dma_bot action type = Load Shops/Leaflets etc.)
        if t.get("action_type") == "dma_bot":
            continue
        # Skip disabled sendouts — is_active=False means disabled in DMA
        if t.get("is_active") is False:
            continue
        # Skip system/utility tasks by name (fallback)
        if any(pat in name_lower for pat in _SYSTEM_NAME_PATTERNS):
            continue
        # Skip if status explicitly inactive
        task_status = str(t.get("status") or t.get("task_status") or t.get("state") or "").lower()
        if task_status in _INACTIVE_STATUSES:
            continue



        date = str(t.get("scheduled_date") or t.get("date") or t.get("send_date") or "")[:10]
        result.append({"id": task_id, "name": name, "date": date, "status": task_status})
    result.sort(key=lambda r: r["date"] or "0000")
    return result


# ── Ticket enrichment (auto-match sendout + G-Sheet tags) ────────────────────

class EnrichRequest(BaseModel):
    client:      str
    ticket_key:  str
    jira_date:   Optional[str] = ""   # YYYY-MM-DD from the JIRA ticket
    jira_summary: Optional[str] = ""  # JIRA summary for tie-breaking


@app.post("/api/ticket/enrich")
async def ticket_enrich(req: EnrichRequest, authorization: Optional[str] = Header(None)):
    """
    Auto-match a DMA sendout by JIRA date and pull G-Sheet tags/leaflet URL.
    Mirrors the render_control_panel() logic from app.py.
    Returns:
      { sendout_id, sendout_name, sendout_date,
        gsheet_tags, gsheet_exclude_tags, leaflet_url }
    """
    _get_session(authorization)
    import difflib as _dl

    result: dict = {
        "sendout_id":        "",
        "sendout_name":      "",
        "sendout_date":      "",
        "gsheet_tags":       "",
        "gsheet_exclude_tags": "",
        "leaflet_url":       "",
    }

    # ── 1. Auto-match DMA sendout by JIRA date ────────────────────────────────
    # For ALDI Sued we use the full segment-aware matcher from bulk_validator;
    # for all other clients we do a fast date+similarity match here.
    jira_date_str = (req.jira_date or "")[:10]
    _client_lower = req.client.lower()
    _is_aldi_sued = "aldi sued" in _client_lower or "aldi süd" in _client_lower or "aldi sud" in _client_lower

    if _is_aldi_sued and jira_date_str:
        # Delegate to the full segment-aware matcher used by bulk validation
        from bulk_validator import _find_sendout_id as _bv_find_sendout_id
        from api_client import fetch_pending_sendouts as _fps
        try:
            _tasks_all = _fps(API_TOKEN, CLIENT_CONFIGS.get(req.client, {}).get("account_id", 0))
        except Exception:
            _tasks_all = []
        # Use jira_summary as-is; bulk_validator._find_sendout_id handles segment lookup
        _sid = _bv_find_sendout_id(
            req.ticket_key, req.client, _gsheet(),
            api_token=API_TOKEN, jira_date=jira_date_str, jira_summary=req.jira_summary or ""
        )
        if _sid:
            # Look up task name + date from the task list
            _task = next((t for t in _tasks_all if str(t.get("id") or t.get("task_id", "")) == _sid), None)
            result["sendout_id"]   = _sid
            result["sendout_name"] = str(_task.get("name") or _task.get("campaign_name") or "") if _task else ""
            result["sendout_date"] = str(_task.get("scheduled_date") or "")[:10] if _task else ""
    else:
        cfg        = CLIENT_CONFIGS.get(req.client, {})
        account_id = cfg.get("account_id")

        if account_id and jira_date_str:
            try:
                from datetime import datetime as _dti
                jira_date = _dti.fromisoformat(jira_date_str).date()
            except Exception:
                jira_date = None

            if jira_date:
                try:
                    tasks = fetch_pending_sendouts(API_TOKEN, account_id)
                except Exception:
                    tasks = []

                _SYS_PATS  = ("load shops","load leaflet","load store","load data",
                               "test sendout","test send","[test]","dummy")
                _INACT_STS = {"disabled","cancelled","canceled","draft","inactive","deleted","archived"}
                date_matches = []
                for task in tasks:
                    if task.get("action_type") == "dma_bot":
                        continue
                    if task.get("is_active") is False:
                        continue
                    _tn = (task.get("name") or task.get("campaign_name") or task.get("task_name") or "").lower()
                    if any(p in _tn for p in _SYS_PATS):
                        continue
                    _ts = str(task.get("status") or task.get("task_status") or task.get("state") or "").lower()
                    if _ts in _INACT_STS:
                        continue
                    raw_d = str(task.get("scheduled_date") or task.get("date") or "")
                    try:
                        if _dti.fromisoformat(raw_d[:10]).date() == jira_date:
                            date_matches.append(task)
                    except Exception:
                        continue

                if date_matches:
                    if len(date_matches) == 1 or not req.jira_summary:
                        best = date_matches[0]
                    else:
                        # Tie-break by name similarity to JIRA summary
                        summary_lower = req.jira_summary.lower()
                        summary_words = set(summary_lower.split())
                        def _score(t):
                            tn = (t.get("name") or t.get("campaign_name") or "").lower()
                            hits = sum(1 for w in summary_words if len(w) > 3 and w in tn)
                            sim  = _dl.SequenceMatcher(None, summary_lower, tn).ratio()
                            return hits * 10 + sim
                        best = max(date_matches, key=_score)

                    result["sendout_id"]   = str(best.get("id") or best.get("task_id") or "")
                    result["sendout_name"] = str(best.get("name") or best.get("campaign_name") or "")
                    result["sendout_date"] = str(best.get("scheduled_date") or "")[:10]

    # ── 2. Tag Registry (takes priority over G-Sheet) ────────────────────────
    # Priority: ticket_key > sendout_id > sendout_date
    registry_hit = _reg.match_by_ticket(req.client, req.ticket_key)
    if not registry_hit and req.client and result["sendout_id"]:
        registry_hit = _reg.match_entry(req.client, result["sendout_id"])
    if not registry_hit and req.client and jira_date_str:
        registry_hit = _reg.match_by_date(req.client, jira_date_str)

    if registry_hit:
        result["gsheet_tags"]         = registry_hit.get("include_tags", "")
        result["gsheet_exclude_tags"] = registry_hit.get("exclude_tags", "")
        result["tags_source"]         = "registry"
        result["registry_id"]         = registry_hit.get("id")
        return result

    result["tags_source"] = "none"

    # ── 3. G-Sheet enrichment (fallback when no registry entry) ──────────────
    gsheet = _gsheet()
    if gsheet and req.client:
        schedule = get_client_schedule_wide(gsheet, req.client)
        # Match by JIRA ticket key first, then by date.
        # Recurring sendouts can have the same ticket linked in several rows
        # (old weeks + current) — prefer the row whose date is closest to the
        # JIRA sendout date instead of the first hit.
        matched_row = None
        _tk_rows = []
        for row in schedule:
            jira_link = str(row.get(GSHEET_COLS.get("jira_link", ""), "")).strip()
            if req.ticket_key and (req.ticket_key == jira_link or req.ticket_key in jira_link):
                _tk_rows.append(row)
        if len(_tk_rows) == 1 or (_tk_rows and not jira_date_str):
            matched_row = _tk_rows[0]
        elif _tk_rows:
            def _row_date_dist(row):
                raw = str(row.get(GSHEET_COLS.get("date", ""), "")).strip()[:10]
                if len(raw) == 10 and raw[2] == "/" and raw[5] == "/":
                    raw = f"{raw[6:10]}-{raw[3:5]}-{raw[0:2]}"
                try:
                    from datetime import date as _d
                    return abs((_d.fromisoformat(raw) - _d.fromisoformat(jira_date_str[:10])).days)
                except Exception:
                    return 9999
            matched_row = sorted(_tk_rows, key=_row_date_dist)[0]
        if not matched_row and jira_date_str:
            for row in schedule:
                try:
                    row_date = str(row.get("_parsed_date", ""))[:10]
                    if not row_date:
                        from dateutil import parser as _dup
                        row_date = _dup.parse(
                            str(row.get(GSHEET_COLS.get("date", ""), "")), dayfirst=True
                        ).strftime("%Y-%m-%d")
                    if row_date == jira_date_str:
                        matched_row = row
                        break
                except Exception:
                    continue

        if matched_row:
            def _clean(v): return str(v or "").replace("nan", "").strip()
            result["gsheet_tags"]         = _clean(matched_row.get(GSHEET_COLS.get("include_tags", ""), ""))
            result["gsheet_exclude_tags"] = _clean(matched_row.get(GSHEET_COLS.get("exclude_tags", ""), ""))
            result["leaflet_url"]         = _clean(matched_row.get(GSHEET_COLS.get("leaflet", ""), ""))
            result["tags_source"]         = "gsheet"

    return result


# ── Validate ──────────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    client: str
    ticket_key: str
    sendout_id: str
    leaflet_url: Optional[str] = ""
    gsheet_tags: Optional[str] = ""
    exclude_tags: Optional[str] = ""


@app.post("/api/validate")
async def validate(req: ValidateRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)

    try:
        j_data, a_data, t_data, leaflet_data = _fetch_core_data(
            req.client, req.ticket_key, req.sendout_id,
            req.leaflet_url or "", req.gsheet_tags or "", req.exclude_tags or ""
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_friendly_exc(exc))

    jira_for_html = dict(j_data)
    if jira_for_html.get("description"):
        jira_for_html["description"] = _strip_slide_labels(jira_for_html["description"])

    try:
        sched_result = validate_scheduled_date(j_data, a_data)
    except Exception:
        sched_result = {"ok": True, "detail": "Date check skipped"}

    html_output = build_results_html(
        jira=jira_for_html,
        api=a_data,
        tmpl=t_data,
        leaflet_data=leaflet_data,
        client=req.client,
        ai_result="",
        ai_urls=None,
        dma_image_urls=[],
        dark=False,
    )

    session = _sessions.get((authorization or "").split(" ", 1)[-1], {})
    global _validation_log
    _validation_log = record_validation(
        ticket_key=req.ticket_key, client=req.client,
        status="pending", mode="regular", issues=0,
        approved=bool(j_data.get("approval_status")),
        log=_validation_log,
        user=session.get("name", ""),
    )

    return {
        "html":           html_output,
        "ticket_key":     req.ticket_key,
        "client":         req.client,
        "sendout_id":     req.sendout_id,
        "schedule_check": sched_result,
    }


# ── AI Audit ──────────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    client: str
    ticket_key: str
    sendout_id: str
    leaflet_url: Optional[str] = ""
    gsheet_tags: Optional[str] = ""
    exclude_tags: Optional[str] = ""


@app.post("/api/ai-audit")
async def ai_audit(req: AuditRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)

    try:
        j_data, a_data, t_data, leaflet_data = _fetch_core_data(
            req.client, req.ticket_key, req.sendout_id,
            req.leaflet_url or "", req.gsheet_tags or "", req.exclude_tags or ""
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_friendly_exc(exc))

    # Prepare all data needed for build_comparison_data
    (tmpl_body, tmpl_footer, tmpl_buttons,
     dma_carousel_texts, dma_image_urls, tag_str, api_urls, rcs_cards) = _prepare_audit_data(
        a_data, t_data, leaflet_data, j_data, req.client
    )
    if not dma_carousel_texts:
        logger.info("SINGLE %s: dma_carousel_texts empty — component_parameters: %s | template components types: %s",
            req.ticket_key,
            [cp.get("type") for cp in (a_data.get("component_parameters") or [])],
            [c.get("type") for c in (t_data.get("components") or [])] if t_data else [],
        )

    # Build jira_for_comparison with slide labels stripped
    jira_for_comparison = dict(j_data)
    if jira_for_comparison.get("description"):
        jira_for_comparison["description"] = _strip_slide_labels(jira_for_comparison["description"])

    # Kaufland RCS Sunday carousel static cards — only inject for carousel, not standaloneCard
    _is_standalone_rcs = bool(
        a_data.get("google_rcs_content", {}).get("richCard", {}).get("standaloneCard")
    )
    if req.client == "Kaufland RCS" and rcs_cards and not _is_standalone_rcs:
        try:
            from datetime import datetime as _dt_rcs
            _is_sun = _dt_rcs.fromisoformat(
                a_data.get("scheduled_date", "").replace("Z", "+00:00")
            ).weekday() == 6
        except Exception:
            _is_sun = False
        if _is_sun:
            static = CLIENT_CONFIGS.get("Kaufland RCS", {}).get("sunday_rcs_cards", [])
            if static:
                expected = " | ".join(
                    f"Card {i+1}: Title='{c['title']}' Body='{c['body'][:80]}...' Button='{c['button']}'"
                    for i, c in enumerate(static)
                )
                jira_for_comparison["description"] = f"[STATIC RCS TEMPLATE] Expected card texts:\n{expected}"

    # Kaufland WABA Sunday static body
    if req.client == "Kaufland WABA" and not jira_for_comparison.get("description"):
        _WABA_STATIC = (
            "Hier findest du unseren aktuellen Prospekt mit den Angeboten vom {{1}} – {{2}} "
            "für deine Filiale in {{3}} {{4}} ⬇️"
        )
        jira_for_comparison["description"] = (
            f"[STATIC WABA CAROUSEL TEMPLATE] Both carousel cards use this body text:\n"
            f"{_WABA_STATIC}\n"
            f"Card 1: leaflet_type=special, offset_days=1 | Card 2: leaflet_type=regular, offset_days=4"
        )

    # Strip cover note from description before building comparison data
    from ai_audit import strip_cover_note as _strip_cover_note
    if jira_for_comparison.get("description"):
        jira_for_comparison["description"] = _strip_cover_note(jira_for_comparison["description"])

    comparison_data = build_comparison_data(
        jira=jira_for_comparison,
        tmpl_body=tmpl_body,
        tmpl_footer=tmpl_footer,
        tmpl_buttons=tmpl_buttons,
        dma_carousel_texts=dma_carousel_texts,
        api_tag_str=tag_str,
        api_urls=[u for u in api_urls if "{{" not in u],
        client_name=req.client,
        api_date=str(a_data.get("scheduled_date", "")),
    )

    # ── Pre-audit data quality gate ───────────────────────────────────────────
    from ai_audit import check_audit_preconditions as _pre_check, run_ai_audit_freestyle as _run_freestyle
    _blockers = _pre_check(j_data, a_data, req.client, comparison_data)
    _hard_blocks = [b for b in _blockers if b["severity"] == "block"]

    # Determine whether to use freestyle mode:
    #   • Hard pre-audit blockers (e.g. URL-only description) → freestyle instead of blocking
    #   • comparison_data signals a non-standard ticket → freestyle
    _freestyle = comparison_data.get("_freestyle_recommended", False) or bool(_hard_blocks)
    _freestyle_reason = comparison_data.get("_freestyle_reason", "") or (
        " | ".join(b["message"] for b in _hard_blocks) if _hard_blocks else ""
    )

    # Download DMA images so Gemini can visually compare them (same URLs shown in Visuals tab)
    import urllib.request as _ur_img
    _dma_img_bytes: list[bytes | None] = []
    for _img_url in (dma_image_urls or [])[:6]:   # cap at 6 to stay within Gemini limits
        try:
            with _ur_img.urlopen(_img_url, timeout=8) as _resp:
                _dma_img_bytes.append(_resp.read())
        except Exception as _img_exc:
            logger.warning("Could not fetch DMA image %s: %s", _img_url, _img_exc)
            _dma_img_bytes.append(None)

    _few_shot = _examples_lib.select_for_audit(req.client)
    try:
        if _freestyle:
            logger.info("Single audit %s: using freestyle mode — %s", req.ticket_key, _freestyle_reason[:80])
            # Also try to fetch JIRA-side images from the G-Sheet image URLs
            _jira_imgs = list(j_data.get("carousel_images") or [])
            if not _jira_imgs:
                for _jimg_url in (comparison_data.get("jira_image_urls") or [])[:6]:
                    try:
                        with _ur_img.urlopen(_jimg_url, timeout=8) as _r:
                            _jira_imgs.append({"name": _jimg_url.split("/")[-1], "bytes": _r.read()})
                    except Exception:
                        pass
            result = _run_freestyle(
                GEMINI_KEY, GEMINI_PRO_MODEL,
                jira=j_data,
                dma_setup=comparison_data.get("DMA_API_Setup", {}),
                client_name=req.client,
                freestyle_reason=_freestyle_reason,
                jira_images=_jira_imgs or None,
                dma_images=_dma_img_bytes or None,
                precomputed_diffs=comparison_data.get("Precomputed_Diffs", {}),
            )
        else:
            result = run_ai_audit(
                GEMINI_KEY, GEMINI_MODEL, comparison_data, req.client,
                jira_images=j_data.get("carousel_images"),
                dma_images=_dma_img_bytes or None,
                examples=_few_shot,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI audit failed: {_friendly_exc(exc)}")

    # Gemini 503 / overload — return a structured "retry later" response instead of
    # an ugly raw error string embedded in the HTML output.
    if result.get("retry_later"):
        return {
            "html":         "",
            "ticket_key":   req.ticket_key,
            "client":       req.client,
            "sendout_id":   req.sendout_id,
            "overloaded":   True,
            "summary":      "AI model temporarily unavailable (high demand). Please try again in a moment.",
            "confidence":   None,
        }

    # Apply the same data-quality confidence cap as the bulk path so the recorded
    # and displayed confidence is honest when key inputs (template body / JIRA
    # description) were absent. Does NOT change the approve decision below — that
    # keys on `issues`, so a clean pass still auto-approves (single check is
    # human-supervised); only the confidence number/reason is corrected.
    from ai_audit import apply_data_quality_cap as _apply_dq_cap
    _capped_conf, _capped_reason = _apply_dq_cap(
        result.get("confidence", -1), result.get("confidence_reason", ""),
        comparison_data, log_key=req.ticket_key,
    )
    result["confidence"] = _capped_conf
    result["confidence_reason"] = _capped_reason

    ai_result_text = result.get("audit_report", "Error extracting report")
    ai_urls = {
        "jira": result.get("jira_extracted_urls", []),
        "api":  result.get("api_extracted_urls", []),
    }
    # Count FAIL verdicts from structured output (avoids counting ❌ multiple times
    # per failed check in the generated markdown — header + verdict + table + overall)
    _structured = result.get("structured") or {}
    _CHECK_NAMES = ("scheduling", "copy", "footer", "cta", "tags", "images")
    if _structured:
        issues = sum(
            1 for k in _CHECK_NAMES
            if isinstance(_structured.get(k), dict) and _structured[k].get("verdict") == "FAIL"
        )
    else:
        issues = ai_result_text.count("❌") if ai_result_text else 0

    jira_for_html = dict(j_data)
    if jira_for_html.get("description"):
        jira_for_html["description"] = _strip_slide_labels(jira_for_html["description"])

    html_output = build_results_html(
        jira=jira_for_html,
        api=a_data,
        tmpl=t_data,
        leaflet_data=leaflet_data,
        client=req.client,
        ai_result=ai_result_text,
        ai_urls=ai_urls,
        dma_image_urls=dma_image_urls,
        dark=False,
    )

    session = _sessions.get((authorization or "").split(" ", 1)[-1], {})
    user_name = session.get("name", "Validator Pro")
    _ai_failed_checks = _extract_failed_checks(ai_result_text) if issues > 0 else []
    global _validation_log
    _validation_log = record_validation(
        ticket_key=req.ticket_key, client=req.client,
        status="failed" if issues else "passed",
        mode="ai", issues=issues,
        approved=False, log=_validation_log,
        user=user_name,
        failed_checks=_ai_failed_checks,
        confidence=result.get("confidence"),
    )

    # Write AI status back to JIRA
    from ai_audit import _is_audit_error
    if not _is_audit_error(ai_result_text):
        jira_status = "Rejected" if issues > 0 else "Approved"
        write_ai_status_to_jira(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, req.ticket_key, jira_status)
        logger.info("JIRA AI status → %s for %s", jira_status, req.ticket_key)

    # Record audit result so scheduled jobs can skip already-audited sendouts
    _al.record_audit(
        ticket_key=req.ticket_key,
        client=req.client,
        sendout_id=req.sendout_id or "",
        overall="FAIL" if issues > 0 else "PASS",
        structured=result.get("structured"),
        confidence=result.get("confidence", -1),
        triggered_by="manual",
        user=user_name,
        failed_checks=_ai_failed_checks,
    )
    if req.sendout_id:
        _audited_sendouts[req.sendout_id] = {
            "ticket_key": req.ticket_key,
            "client":     req.client,
            "issues":     issues,
            "confidence": result.get("confidence", -1),
            "ts":         datetime.now(timezone.utc).isoformat(),
        }

    # Fire Slack alert when AI audit finds issues
    if issues > 0:
        failed = _extract_failed_checks(ai_result_text)
        _send_slack_alert(
            ticket_key=req.ticket_key,
            client=req.client,
            mode="AI Single Check",
            issues=issues,
            user_name=user_name,
            failed_checks=failed[:8],
            sendout_id=req.sendout_id,
        )

    return {
        "html":            html_output,
        "ai_result":       ai_result_text,
        "issues":          issues,
        "confidence":      result.get("confidence", -1),
        "confidence_reason": result.get("confidence_reason", ""),
        "ticket_key":      req.ticket_key,
        "client":          req.client,
        "structured":      result.get("structured"),       # per-check verdicts for Save-as-Example
        "comparison_data": comparison_data,                # snippets extracted server-side on save
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/api/dashboard")
async def dashboard(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    try:
        data = build_dashboard_data(_validation_log)
        data["log"] = list(reversed(_validation_log[-50:]))

        # ── Queue health (live from cache) ────────────────────────────────────
        from datetime import datetime as _dti, timedelta as _tdi
        queue = _normalized_queue()   # flat dicts with "date" key
        today = _dti.utcnow().date()
        due_24h = due_48h = 0
        for t in queue:
            raw = (t.get("date") or "")[:10]
            if not raw:
                continue
            try:
                delta = (_dti.fromisoformat(raw).date() - today).days
                if 0 <= delta <= 1:
                    due_24h += 1
                if 0 <= delta <= 2:
                    due_48h += 1
            except Exception:
                pass
        data["queue_health"] = {
            "queue_size": len(queue),
            "due_24h":    due_24h,
            "due_48h":    due_48h,
        }
    except Exception:
        data = {"total": 0, "pass_rate": 0, "log": [], "queue_health": {"queue_size": 0, "due_24h": 0, "due_48h": 0}}
    return data


# ── Few-shot Examples Library ────────────────────────────────────────────────

class ExampleSaveRequest(BaseModel):
    client:      str
    check:       str                  # scheduling / copy / footer / cta / tags / images
    scenario:    str                  # human description, e.g. "Wrong segment excluded"
    verdict:     str                  # PASS / FAIL / NA  (user-confirmed)
    reason:      str
    expected:    str
    actual:      str
    added_by:    str = ""
    comparison_data: dict | None = None   # full comparison_data to extract snippet from


class ExampleUpdateRequest(BaseModel):
    active:   bool | None = None
    scenario: str  | None = None
    verdict:  str  | None = None
    reason:   str  | None = None
    expected: str  | None = None
    actual:   str  | None = None


@app.get("/api/examples")
async def list_examples(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    return {"examples": _examples_lib.get_all()}


@app.post("/api/examples", status_code=201)
async def add_example(req: ExampleSaveRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    snippet = {}
    if req.comparison_data:
        snippet = extract_snippet(req.comparison_data, req.check)
    ex_id = _examples_lib.add({
        "client":        req.client,
        "check":         req.check,
        "scenario":      req.scenario,
        "verdict":       req.verdict,
        "added_by":      req.added_by,
        "input_snippet": snippet,
        "correct_output": {
            "verdict":  req.verdict,
            "reason":   req.reason,
            "expected": req.expected,
            "actual":   req.actual,
        },
    })
    return {"id": ex_id, "ok": True}


@app.put("/api/examples/{ex_id}")
async def update_example(
    ex_id: str, req: ExampleUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    _get_session(authorization)
    fields: dict = {k: v for k, v in req.model_dump().items() if v is not None}
    # If verdict/reason/expected/actual updated, sync correct_output too
    _out_keys = {"verdict", "reason", "expected", "actual"}
    out_updates = {k: v for k, v in fields.items() if k in _out_keys}
    if out_updates:
        ex = _examples_lib.get_by_id(ex_id)
        if ex:
            merged = dict(ex.get("correct_output") or {})
            merged.update(out_updates)
            fields["correct_output"] = merged
    ok = _examples_lib.update(ex_id, fields)
    if not ok:
        raise HTTPException(status_code=404, detail="Example not found")
    return {"ok": True}


@app.delete("/api/examples/{ex_id}")
async def delete_example(ex_id: str, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    ok = _examples_lib.delete(ex_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Example not found")
    return {"ok": True}


# ── G-Sheet refresh ───────────────────────────────────────────────────────────

@app.post("/api/gsheet/refresh")
async def refresh_gsheet(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    global _gsheet_cache, _gsheet_fetched_at
    try:
        _gsheet_cache = fetch_gsheet_data_csv(GSHEET_DEFAULT_URL)
        _gsheet_fetched_at = time.time()
        return {"ok": True, "rows": len(_gsheet_cache)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── Approve ticket ────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    approver: Optional[str] = ""


@app.post("/api/approve/{ticket_key}")
async def approve(ticket_key: str, req: ApproveRequest = ApproveRequest(), authorization: Optional[str] = Header(None)):
    session = _get_session(authorization)
    approver_label = req.approver or session["name"]
    try:
        ok, msg = approve_ticket_jira(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, ticket_key, approver_label)
        if not ok:
            raise HTTPException(status_code=502, detail=msg)
        logger.info("APPROVE\t%s\t%s", session["name"], ticket_key)
        _send_slack_approval(ticket_key, user_name=session["name"], approver=approver_label)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── Tag Registry ─────────────────────────────────────────────────────────────

class TagRegistryCreate(BaseModel):
    client:        str
    ticket_key:    str = ""
    sendout_id:    str = ""
    sendout_name:  str = ""
    sendout_date:  str = ""
    sendout_time:  str = ""
    tz:            str = "Europe/Berlin"
    platform:      str = ""   # "WABA" | "RCS" | ""
    template_type: str = ""   # "Regular" | "Carousel" | ""
    include_tags:  str = ""
    exclude_tags:  str = ""
    notes:         str = ""


class TagRegistryUpdate(BaseModel):
    ticket_key:    Optional[str] = None
    sendout_id:    Optional[str] = None
    sendout_name:  Optional[str] = None
    sendout_date:  Optional[str] = None
    sendout_time:  Optional[str] = None
    tz:            Optional[str] = None
    platform:      Optional[str] = None
    template_type: Optional[str] = None
    include_tags:  Optional[str] = None
    exclude_tags:  Optional[str] = None
    notes:         Optional[str] = None


@app.get("/api/tag-registry")
async def registry_list(client: Optional[str] = None, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    return _reg.list_entries(client or None)


@app.post("/api/tag-registry", status_code=201)
async def registry_create(body: TagRegistryCreate, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    entry = _reg.create_entry(
        client=body.client, ticket_key=body.ticket_key, sendout_id=body.sendout_id,
        sendout_name=body.sendout_name, sendout_date=body.sendout_date,
        sendout_time=body.sendout_time, tz=body.tz,
        platform=body.platform, template_type=body.template_type,
        include_tags=body.include_tags, exclude_tags=body.exclude_tags,
        notes=body.notes,
    )
    return entry


@app.put("/api/tag-registry/{entry_id}")
async def registry_update(entry_id: int, body: TagRegistryUpdate, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    existing = _reg.get_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entry not found")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    return _reg.update_entry(entry_id, **updates)


@app.delete("/api/tag-registry/{entry_id}")
async def registry_delete(entry_id: int, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    if not _reg.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


# ── Client config editor ──────────────────────────────────────────────────────

class ClientConfigUpdate(BaseModel):
    timezone_name: str
    requires_jira: bool
    filters:       dict
    aliases:       list
    mappings:      Optional[dict] = None

class ClientConfigCreate(BaseModel):
    name:          str
    account_id:    int  = 0
    timezone_name: str  = "Europe/Berlin"
    requires_jira: bool = True
    filters:       dict = {}
    aliases:       list = []
    mappings:      Optional[dict] = None


def _enrich_client_row(row: dict) -> dict:
    """Merge account_id: prefer CLIENT_CONFIGS (hardcoded), fall back to DB value (custom clients)."""
    name = row.get("name", "")
    hardcoded = CLIENT_CONFIGS.get(name, {}).get("account_id")
    row["account_id"] = hardcoded if hardcoded else row.get("account_id", 0)
    return row


@app.get("/api/config/clients")
async def config_list_clients(authorization: Optional[str] = Header(None)):
    """Return all editable client configs (account_id included for display)."""
    _get_session(authorization)
    return [_enrich_client_row(r) for r in _cfg.list_clients()]


@app.get("/api/config/clients/{name}")
async def config_get_client(name: str, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    row = _cfg.get_client(name)
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return _enrich_client_row(row)


@app.post("/api/config/clients")
async def config_create_client(
    body: ClientConfigCreate,
    authorization: Optional[str] = Header(None),
):
    """Create a new custom client. Fails if a client with that name already exists."""
    _get_session(authorization)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Client name cannot be empty")
    if _cfg.get_client(name):
        raise HTTPException(status_code=409, detail=f"Client '{name}' already exists")
    saved = _cfg.upsert_client(
        name=name,
        account_id=body.account_id,
        timezone_name=body.timezone_name,
        requires_jira=body.requires_jira,
        filters=body.filters or {},
        aliases=body.aliases or [],
        mappings=body.mappings,
        is_custom=True,
    )
    _cfg.apply_to_memory(CLIENT_CONFIGS, CLIENT_ALIASES)
    return _enrich_client_row(saved)


@app.put("/api/config/clients/{name}")
async def config_update_client(
    name: str,
    body: ClientConfigUpdate,
    authorization: Optional[str] = Header(None),
):
    _get_session(authorization)
    if not _cfg.get_client(name):
        raise HTTPException(status_code=404, detail="Client not found")
    saved = _cfg.upsert_client(
        name=name,
        timezone_name=body.timezone_name,
        requires_jira=body.requires_jira,
        filters=body.filters,
        aliases=body.aliases,
        mappings=body.mappings,
    )
    _cfg.apply_to_memory(CLIENT_CONFIGS, CLIENT_ALIASES)
    return _enrich_client_row(saved)


@app.delete("/api/config/clients/{name}")
async def config_delete_client(name: str, authorization: Optional[str] = Header(None)):
    """Delete a custom client (non-custom/hardcoded clients cannot be deleted)."""
    _get_session(authorization)
    ok = _cfg.delete_client(name)
    if not ok:
        raise HTTPException(status_code=400, detail="Client not found or is a built-in client (cannot delete)")
    # Remove from memory
    CLIENT_CONFIGS.pop(name, None)
    CLIENT_ALIASES.pop(name, None)
    return {"ok": True, "deleted": name}


@app.post("/api/config/reload")
async def config_reload(authorization: Optional[str] = Header(None)):
    """Re-apply all DB rows to in-memory CLIENT_CONFIGS / CLIENT_ALIASES."""
    _get_session(authorization)
    _cfg.apply_to_memory(CLIENT_CONFIGS, CLIENT_ALIASES)
    return {"ok": True, "clients": len(CLIENT_CONFIGS)}


# ── Slack test ────────────────────────────────────────────────────────────────

@app.get("/api/slack/status")
async def slack_status(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    return {"configured": bool(SLACK_WEBHOOK)}


@app.post("/api/slack/test")
async def slack_test(authorization: Optional[str] = Header(None)):
    session = _get_session(authorization)
    if not SLACK_WEBHOOK:
        raise HTTPException(status_code=400, detail="SLACK_WEBHOOK_URL is not configured in .env")
    _send_slack_alert(
        ticket_key="TEST-000",
        client="Test Client",
        mode="Test",
        issues=1,
        user_name=session["name"],
        failed_checks=["This is a test notification from Validator Pro"],
    )
    return {"ok": True, "message": "Test alert sent to Slack"}


# ── Clients list ──────────────────────────────────────────────────────────────

@app.get("/api/clients")
async def get_clients(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    return list(CLIENT_CONFIGS.keys())


# ── Audit history ─────────────────────────────────────────────────────────────

@app.get("/api/audit-history")
async def audit_history(
    limit:      int = 100,
    client:     Optional[str] = None,
    ticket_key: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _get_session(authorization)
    return _al.list_audits(limit=limit, client=client or None, ticket_key=ticket_key or None)


# ── Preflight history ─────────────────────────────────────────────────────────

@app.get("/api/preflight/runs")
async def preflight_runs(authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    return _al.list_preflight_runs(limit=14)


@app.post("/api/preflight/run-now")
async def preflight_run_now(authorization: Optional[str] = Header(None)):
    """Manually trigger the preflight job (admin only)."""
    _require_admin(authorization)
    import asyncio as _aio
    await _aio.get_event_loop().run_in_executor(None, lambda: None)  # yield
    await _job_preflight_alert()
    return {"ok": True}


# ── User management ───────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username:     str
    display_name: str
    password:     str
    is_admin:     bool = False


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    password:     Optional[str] = None
    is_admin:     Optional[bool] = None
    active:       Optional[bool] = None


@app.get("/api/users")
async def users_list(authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    return _udb.list_users()


@app.post("/api/users", status_code=201)
async def users_create(body: UserCreate, authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    existing = _udb.get_user(body.username.strip().lower())
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    return _udb.create_user(
        username=body.username,
        display_name=body.display_name,
        password=body.password,
        is_admin=body.is_admin,
    )


@app.put("/api/users/{username}")
async def users_update(username: str, body: UserUpdate, authorization: Optional[str] = Header(None)):
    session = _require_admin(authorization)
    if not _udb.get_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    # Prevent admin from accidentally removing their own admin flag
    if username == session["user"] and body.is_admin is False:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin privileges")
    return _udb.update_user(
        username=username,
        display_name=body.display_name,
        password=body.password,
        is_admin=body.is_admin,
        active=body.active,
    )


@app.delete("/api/users/{username}")
async def users_delete(username: str, authorization: Optional[str] = Header(None)):
    session = _require_admin(authorization)
    if username == session["user"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if not _udb.delete_user(username):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


# ── Bulk validation ──────────────────────────────────────────────────────────

class BulkRequest(BaseModel):
    ticket_keys: list[str]


def _serialize_result(r: BulkTicketResult) -> dict:
    import datetime as _dt
    d = dataclasses.asdict(r)
    # keep only JSON-safe fields (drop large api_payload)
    d.pop("api_payload", None)
    # Convert any non-serializable types
    def _make_safe(obj):
        if isinstance(obj, dict):
            return {k: _make_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_make_safe(v) for v in obj]
        if isinstance(obj, (_dt.datetime, _dt.date)):
            return obj.isoformat()
        return obj
    return _make_safe(d)


@app.post("/api/bulk-validate")
async def bulk_validate(req: BulkRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    key_set = set(req.ticket_keys)
    issues = [i for i in _cached_queue() if i["key"] in key_set]
    if not issues:
        raise HTTPException(status_code=404, detail="None of the requested tickets found in the JIRA queue — try refreshing the queue first")

    try:
        results: list[BulkTicketResult] = run_bulk_regular_check(
            tickets=issues,
            gsheet_data=_gsheet(),
            jira_server=JIRA_SERVER,
            jira_email=JIRA_EMAIL,
            jira_token=JIRA_TOKEN,
            api_token=API_TOKEN,
            on_progress=lambda r, i, t: None,
        )
    except Exception as exc:
        logger.error("bulk_validate failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Bulk validation failed: {_friendly_exc(exc)}")

    session = _sessions.get((authorization or "").split(" ", 1)[-1], {})
    bulk_user = session.get("name", "")
    global _validation_log
    for r in results:
        _fc = [c["label"] for c in (r.checks or []) if not c.get("ok")]
        _validation_log = record_validation(
            ticket_key=r.ticket_key, client=r.client,
            status=r.status, mode="regular",
            issues=r.issues_found, approved=False,
            log=_validation_log,
            user=bulk_user,
            failed_checks=_fc,
        )
        # Persist rule-based checks to DB so they survive restarts
        _al.record_audit(
            ticket_key=r.ticket_key,
            client=r.client,
            sendout_id=getattr(r, "sendout_id", "") or "",
            overall="FAIL" if r.issues_found > 0 else "PASS",
            structured=None,
            confidence=-1,
            triggered_by="manual_rule",
            user=bulk_user,
            failed_checks=_fc,
        )

    return [_serialize_result(r) for r in results]


@app.post("/api/bulk-ai-audit")
async def bulk_ai_audit(req: BulkRequest, authorization: Optional[str] = Header(None)):
    """
    Streaming SSE endpoint — emits one JSON event per completed ticket plus a
    final 'done' event.  Each event is:  data: <json>\n\n
    Event types: { type: "progress", index, total, result }
                 { type: "done", results: [...] }
                 { type: "error", detail }
    """
    from fastapi.responses import StreamingResponse as _SR
    import asyncio as _aio
    import json as _json

    session = _get_session(authorization)
    user_name = session.get("name", "Validator Pro")
    key_set = set(req.ticket_keys)
    issues = [i for i in _cached_queue() if i["key"] in key_set]
    if not issues:
        raise HTTPException(status_code=404, detail="None of the requested tickets found in the JIRA queue — try refreshing the queue first")

    total = len(issues)
    results_collector: list = []
    progress_queue: "asyncio.Queue" = _aio.Queue()

    def _on_progress(r: "BulkTicketResult", idx: int, tot: int):
        progress_queue.put_nowait((r, idx, tot))

    async def _run_in_thread():
        loop = _aio.get_event_loop()
        try:
            results = await loop.run_in_executor(None, lambda: run_bulk_validation(
                tickets=issues,
                gsheet_data=_gsheet(),
                jira_server=JIRA_SERVER,
                jira_email=JIRA_EMAIL,
                jira_token=JIRA_TOKEN,
                api_token=API_TOKEN,
                gemini_key=GEMINI_KEY,
                gemini_model=GEMINI_BULK_MODEL,
                on_progress=_on_progress,
                examples_lib=_examples_lib,
            ))
            results_collector.extend(results)
        except Exception as exc:
            logger.error("bulk_ai_audit failed: %s", exc, exc_info=True)
            results_collector.append(exc)
        finally:
            progress_queue.put_nowait(None)  # sentinel

    async def _stream():
        try:
            task = _aio.create_task(_run_in_thread())
            while True:
                item = await progress_queue.get()
                if item is None:
                    break
                r, idx, tot = item
                try:
                    safe = _serialize_result(r)
                    yield f"data: {_json.dumps({'type':'progress','index':idx,'total':tot,'result':safe})}\n\n"
                except Exception as _pe:
                    logger.warning("bulk_ai_audit: failed to serialize progress result: %s", _pe)

            await task  # ensure thread finished

            if results_collector and isinstance(results_collector[0], Exception):
                yield f"data: {_json.dumps({'type':'error','detail':str(results_collector[0])})}\n\n"
                return

            results = results_collector

            # Post-process: validation log + Slack
            global _validation_log
            _slack_failed: list[dict] = []
            for r in results:
                try:
                    _ai_fc = [c["label"] for c in (r.checks or []) if not c.get("ok")]
                    _validation_log = record_validation(
                        ticket_key=r.ticket_key, client=r.client,
                        status=r.status, mode="ai",
                        issues=r.issues_found, approved=False,
                        log=_validation_log,
                        user=user_name,
                        failed_checks=_ai_fc,
                        confidence=getattr(r, "confidence", None),
                    )
                    if r.status == "failed" and r.issues_found > 0:
                        failed_checks = [c["label"] for c in (r.checks or []) if not c.get("ok")]
                        if not failed_checks and r.report:
                            failed_checks = _extract_failed_checks(r.report)
                        _slack_failed.append({
                            "ticket_key": r.ticket_key,
                            "client": r.client,
                            "issues": r.issues_found,
                            "failed_checks": failed_checks[:8],
                            "sendout_id": r.sendout_id or "",
                        })
                except Exception as _re:
                    logger.warning("bulk_ai_audit: post-process error for %s: %s", getattr(r, 'ticket_key', '?'), _re)

            if _slack_failed:
                _send_slack_bulk_alert(_slack_failed, user_name=user_name)

            try:
                all_safe = [_serialize_result(r) for r in results]
                yield f"data: {_json.dumps({'type':'done','results':all_safe})}\n\n"
            except Exception as _se:
                logger.error("bulk_ai_audit: failed to serialize final results: %s", _se, exc_info=True)
                yield f"data: {_json.dumps({'type':'error','detail':f'Result serialization failed: {_se}'})}\n\n"

        except Exception as _ue:
            logger.error("bulk_ai_audit _stream crashed: %s", _ue, exc_info=True)
            try:
                yield f"data: {_json.dumps({'type':'error','detail':str(_ue)})}\n\n"
            except Exception:
                pass

    return _SR(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _orphan_scan_sync(days_ahead: int, days_back: int) -> dict:  # kept for internal use only
    """
    Synchronous implementation of the orphan scan — runs in a thread pool
    so it doesn't block the async event loop.
    """
    from datetime import datetime as _dt, timedelta as _td

    gsheet = _gsheet()

    # Build JIRA lookup: client → set of dates
    # Strategy: run TWO sources and union the results.
    #   1. JQL search — covers all tickets regardless of queue assignment
    #   2. Service-desk queue pagination — known reliable fallback
    jira_by_client_date: dict[str, set] = {}
    jira_scan_count = 0
    try:
        jql_issues = fetch_jira_tickets_jql(
            JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN,
            "project = MAS ORDER BY created DESC",
            fields=["summary", "description", "reporter", "customfield_12665"],
        )
        sd_issues = fetch_all_servicedesk_issues(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN)

        seen_keys: set = set()
        all_jira: list[dict] = []
        for iss in jql_issues + sd_issues:
            k = iss.get("key", "")
            if k and k not in seen_keys:
                seen_keys.add(k)
                all_jira.append(iss)

        jira_scan_count = len(all_jira)
        logger.info("orphan_scan: %d unique JIRA issues (%d JQL + %d SD)",
                    jira_scan_count, len(jql_issues), len(sd_issues))

        for issue in all_jira:
            client   = _ticket_client(issue)
            date_raw = str(issue["fields"].get("customfield_12665", ""))[:10]
            if client and client != "Unknown" and date_raw and len(date_raw) == 10:
                jira_by_client_date.setdefault(client, set()).add(date_raw)
                for alias in CLIENT_ALIASES.get(client, []):
                    jira_by_client_date.setdefault(alias, set()).add(date_raw)
    except Exception as exc:
        logger.warning("JIRA fetch for orphan scan failed: %s", exc)

    # Build G-Sheet lookup: client → set of dates
    gsheet_by_client_date: dict[str, set] = {}
    for row in gsheet:
        rc = str(row.get(GSHEET_COLS.get("client", "Client"), "")).strip()
        rd = str(row.get(GSHEET_COLS.get("date", "Date"), "")).strip()
        if len(rd) == 10 and rd[2] == "/" and rd[5] == "/":
            rd = f"{rd[6:10]}-{rd[3:5]}-{rd[0:2]}"
        else:
            rd = rd[:10]
        if rc and rd:
            gsheet_by_client_date.setdefault(rc, set()).add(rd)

    # Fetch all DMA sendouts (window covers past days_back + future days_ahead)
    all_sendouts: list[dict] = []
    seen_accounts: set = set()
    for client, cfg in CLIENT_CONFIGS.items():
        acc_id = cfg.get("account_id")
        if not acc_id or acc_id in seen_accounts:
            continue
        seen_accounts.add(acc_id)
        try:
            tasks = fetch_pending_sendouts(API_TOKEN, acc_id,
                                           days_ahead=days_ahead, days_back=days_back)
            for task in tasks:
                task["_client"] = client
                all_sendouts.append(task)
        except Exception as exc:
            logger.warning("DMA fetch failed for %s (%s): %s", client, acc_id, exc)

    # Classify each sendout within [today-days_back … today+days_ahead]
    now_date   = _dt.utcnow().date()
    start_date = now_date - _td(days=days_back)
    cutoff     = now_date + _td(days=days_ahead)
    results: list[dict] = []

    for task in all_sendouts:
        date_raw = str(task.get("scheduled_date", ""))[:10]
        try:
            task_date = _dt.fromisoformat(date_raw).date()
        except Exception:
            continue
        if task_date < start_date or task_date > cutoff:
            continue

        client    = task["_client"]
        task_name = task.get("name") or task.get("campaign_name") or ""
        task_id   = str(task.get("id") or task.get("task_id") or "")

        # Skip internal system tasks that are never JIRA-tracked
        _task_name_lower = task_name.strip().lower()
        if any(_task_name_lower == s for s in {
            "load shops and leaflets",
            "load shops & leaflets",
            "hofer load shops and leaflets",
            "hofer load shops & leaflets",
        }):
            continue

        in_jira = date_raw in jira_by_client_date.get(client, set())
        if not in_jira:
            for alias in CLIENT_ALIASES.get(client, []):
                if date_raw in jira_by_client_date.get(alias, set()):
                    in_jira = True
                    break

        in_gsheet = date_raw in gsheet_by_client_date.get(client, set())
        if not in_gsheet:
            for alias in CLIENT_ALIASES.get(client, []):
                if date_raw in gsheet_by_client_date.get(alias, set()):
                    in_gsheet = True
                    break

        requires_jira = CLIENT_CONFIGS.get(client, {}).get("requires_jira", True)
        if not requires_jira:
            status = "auto"
        elif in_jira and in_gsheet:
            status = "ok"
        elif not in_jira:
            status = "no_jira"
        else:
            status = "no_gsheet"

        # Extract filter tags from the raw task payload
        _body = task.get("data", {}).get("body")
        api_body = (
            _body if isinstance(_body, dict) and
            ("filters" in _body or "leaflet_filter" in _body or "component_parameters" in _body)
            else task
        )

        filter_parts: list[str] = []
        for f in api_body.get("filters", []):
            if not isinstance(f, dict):
                continue
            if f.get("locale"):
                filter_parts.append(f"locale={f['locale']}")
            if f.get("shop_number"):
                filter_parts.append(f"shop_number={f['shop_number']}")
            if f.get("wids"):
                n = len(str(f["wids"]).split(","))
                filter_parts.append(f"wids ({n} contacts)")
            for tg in f.get("tags", []):
                if not isinstance(tg, dict):
                    continue
                n, v = tg.get("name", ""), tg.get("value", "")
                excl = tg.get("mode", "") == "exclude" or "exclude_value" in tg
                if n and v:
                    filter_parts.append(f"{'Excl' if excl else 'Incl'}: {n}={v}")

        lf = api_body.get("leaflet_filter", {})
        if isinstance(lf, dict):
            if lf.get("offset_days") is not None:
                filter_parts.append(f"offset_days={lf['offset_days']}")
            for lt in lf.get("tags", []):
                n, v = lt.get("name", ""), lt.get("value", "")
                if n and v:
                    filter_parts.append(f"leaflet_{n}={v}")

        config_ok: Optional[bool] = None
        try:
            mock_jira = {"date": date_raw, "gsheet_tags": "", "gsheet_exclude_tags": "",
                         "request_type": task_name}
            tag_result = check_tags(mock_jira, api_body, client)
            if tag_result.get("expected_filters"):
                config_ok = not bool(tag_result.get("missing_filters"))
        except Exception:
            pass

        results.append({
            "client":    client,
            "date":      date_raw,
            "name":      task_name,
            "id":        task_id,
            "in_jira":   in_jira,
            "in_gsheet": in_gsheet,
            "status":    status,
            "filters":   filter_parts,
            "config_ok": config_ok,
        })

    results.sort(key=lambda r: (r["date"], r["client"]))
    return {
        "results":      results,
        "jira_count":   jira_scan_count,
        "gsheet_count": sum(len(v) for v in gsheet_by_client_date.values()),
    }


# ── Proactive Monitoring (APScheduler) ───────────────────────────────────────

def _send_slack_block(
    header: str,
    sections: list[str],
    actions: list[dict] | None = None,
    webhook: str = "",
) -> None:
    """Post a rich Slack Block Kit message."""
    url = webhook or SLACK_WEBHOOK
    if not url:
        return
    try:
        import json as _json
        import urllib.request as _ur

        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        ]
        for sec in sections:
            if sec:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": sec[:3000]}})
        if actions:
            blocks.append({"type": "actions", "elements": actions[:5]})

        payload = {"text": header, "blocks": blocks}
        req = _ur.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        _ur.urlopen(req, timeout=5)
        logger.info("SLACK_BLOCK sent: %s", header[:80])
    except Exception as exc:
        logger.warning("_send_slack_block failed: %s", exc)


def _safe_date_delta(date_str: str, today) -> int:
    """Return (parsed_date - today).days or 999 on parse error."""
    try:
        from datetime import datetime as _dt
        return (_dt.fromisoformat(date_str[:10]).date() - today).days
    except Exception:
        return 999


def _safe_date_str_match(date_str: str, target_date) -> bool:
    """Return True if date_str parses to target_date."""
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(date_str).date() == target_date
    except Exception:
        return False


def _enrich_for_scheduler(
    client: str, ticket_key: str, jira_date: str, jira_summary: str
) -> dict:
    """Synchronous sendout enrichment for use in a thread executor."""
    import difflib as _dl
    from datetime import datetime as _dti

    result: dict = {
        "sendout_id": "", "sendout_name": "", "sendout_date": "",
        "gsheet_tags": "", "gsheet_exclude_tags": "", "leaflet_url": "",
    }

    _client_lower = client.lower()
    _is_aldi_sued = "aldi sued" in _client_lower or "aldi süd" in _client_lower

    if _is_aldi_sued and jira_date:
        from bulk_validator import _find_sendout_id as _bv_find
        _sid = _bv_find(
            ticket_key, client, _gsheet(),
            api_token=API_TOKEN, jira_date=jira_date, jira_summary=jira_summary
        )
        if _sid:
            result["sendout_id"] = _sid
    else:
        cfg = CLIENT_CONFIGS.get(client, {})
        account_id = cfg.get("account_id")
        if account_id and jira_date:
            try:
                jira_dt = _dti.fromisoformat(jira_date[:10]).date()
            except Exception:
                return result
            try:
                from api_client import fetch_pending_sendouts as _fps
                tasks = _fps(API_TOKEN, account_id)
            except Exception:
                return result

            _SYS2  = ("load shops","load leaflet","load store","load data",
                       "test sendout","test send","[test]","dummy")
            _INACT2 = {"disabled","cancelled","canceled","draft","inactive","deleted","archived"}
            date_matches = [
                t for t in tasks
                if _safe_date_str_match(str(t.get("scheduled_date") or "")[:10], jira_dt)
                and t.get("action_type") != "dma_bot"
                and t.get("is_active") is not False
                and not any(p in (t.get("name") or t.get("campaign_name") or t.get("task_name") or "").lower() for p in _SYS2)
                and str(t.get("status") or t.get("task_status") or t.get("state") or "").lower() not in _INACT2
            ]

            if date_matches:
                if len(date_matches) == 1 or not jira_summary:
                    best = date_matches[0]
                else:
                    summary_lower = jira_summary.lower()
                    summary_words = set(summary_lower.split())

                    def _score(t):
                        tn = (t.get("name") or t.get("campaign_name") or "").lower()
                        hits = sum(1 for w in summary_words if len(w) > 3 and w in tn)
                        sim = _dl.SequenceMatcher(None, summary_lower, tn).ratio()
                        return hits * 10 + sim

                    best = max(date_matches, key=_score)
                result["sendout_id"]   = str(best.get("id") or best.get("task_id") or "")
                result["sendout_name"] = str(best.get("name") or best.get("campaign_name") or "")
                result["sendout_date"] = str(best.get("scheduled_date") or "")[:10]

    # G-Sheet tags
    gsheet = _gsheet()
    if gsheet and client:
        schedule = get_client_schedule_wide(gsheet, client)
        for row in schedule:
            try:
                row_date = str(row.get("_parsed_date", ""))[:10]
                if not row_date:
                    from dateutil import parser as _dup
                    row_date = _dup.parse(
                        str(row.get(GSHEET_COLS.get("date", ""), "")), dayfirst=True
                    ).strftime("%Y-%m-%d")
                if row_date == jira_date[:10]:
                    def _clean(v):
                        return str(v or "").replace("nan", "").strip()
                    result["gsheet_tags"]         = _clean(row.get(GSHEET_COLS.get("include_tags", ""), ""))
                    result["gsheet_exclude_tags"] = _clean(row.get(GSHEET_COLS.get("exclude_tags", ""), ""))
                    result["leaflet_url"]         = _clean(row.get(GSHEET_COLS.get("leaflet", ""), ""))
                    break
            except Exception:
                continue

    return result


def _run_audit_sync(
    client: str, ticket_key: str, sendout_id: str,
    leaflet_url: str = "", gsheet_tags: str = "", exclude_tags: str = "",
) -> dict:
    """Full AI audit, synchronous — intended for thread executor calls."""
    try:
        j_data, a_data, t_data, leaflet_data = _fetch_core_data(
            client, ticket_key, sendout_id, leaflet_url, gsheet_tags, exclude_tags
        )
    except Exception as exc:
        logger.warning("_run_audit_sync fetch failed for %s: %s", ticket_key, exc)
        return {"issues": -1, "confidence": -1, "ai_result": ""}

    (tmpl_body, tmpl_footer, tmpl_buttons,
     dma_carousel_texts, dma_image_urls, tag_str, api_urls, rcs_cards) = _prepare_audit_data(
        a_data, t_data, leaflet_data, j_data, client
    )

    jira_for_comparison = dict(j_data)
    if jira_for_comparison.get("description"):
        jira_for_comparison["description"] = _strip_slide_labels(jira_for_comparison["description"])

    comparison_data = build_comparison_data(
        jira=jira_for_comparison,
        tmpl_body=tmpl_body,
        tmpl_footer=tmpl_footer,
        tmpl_buttons=tmpl_buttons,
        dma_carousel_texts=dma_carousel_texts,
        api_tag_str=tag_str,
        api_urls=[u for u in api_urls if "{{" not in u],
        client_name=client,
        api_date=str(a_data.get("scheduled_date", "")),
    )

    import urllib.request as _ur_img
    _dma_img_bytes: list[bytes | None] = []
    for _img_url in (dma_image_urls or [])[:6]:
        try:
            with _ur_img.urlopen(_img_url, timeout=8) as _resp:
                _dma_img_bytes.append(_resp.read())
        except Exception as _img_exc:
            logger.warning("auto-audit: could not fetch image %s: %s", _img_url, _img_exc)
            _dma_img_bytes.append(None)

    _few_shot = _examples_lib.select_for_audit(client)
    try:
        result = run_ai_audit(
            GEMINI_KEY, GEMINI_BULK_MODEL, comparison_data, client,
            jira_images=j_data.get("carousel_images"),
            dma_images=_dma_img_bytes or None,
            examples=_few_shot,
        )
    except Exception as exc:
        logger.warning("_run_audit_sync AI call failed for %s: %s", ticket_key, exc)
        return {"issues": -1, "confidence": -1, "ai_result": ""}

    if result.get("retry_later"):
        return {"issues": -1, "confidence": -1, "ai_result": "model_overloaded"}

    ai_text = result.get("audit_report", "")
    _structured = result.get("structured") or {}
    _CHECK_NAMES = ("scheduling", "copy", "footer", "cta", "tags", "images")
    if _structured:
        issues = sum(
            1 for k in _CHECK_NAMES
            if isinstance(_structured.get(k), dict) and _structured[k].get("verdict") == "FAIL"
        )
    else:
        issues = ai_text.count("❌") if ai_text else 0

    return {"issues": issues, "confidence": result.get("confidence", -1), "ai_result": ai_text}


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

async def _job_preflight_alert() -> None:
    """
    Daily 08:30 UTC — post a Slack preflight digest for all JIRA tickets
    going live in the next 48 hours.
    """
    import asyncio as _asyncio
    import urllib.parse as _up
    from datetime import datetime as _dt

    logger.info("SCHEDULER: running preflight alert job")
    if not SLACK_WEBHOOK:
        logger.info("SCHEDULER: preflight skipped — no SLACK_WEBHOOK")
        return

    loop = _asyncio.get_event_loop()
    try:
        queue = await loop.run_in_executor(None, _normalized_queue)
    except Exception as exc:
        logger.warning("SCHEDULER preflight: queue fetch failed: %s", exc)
        return

    today = _dt.utcnow().date()
    logger.info("SCHEDULER preflight: %d tickets in queue, today=%s", len(queue), today)
    upcoming: list[dict] = []
    for t in queue:
        raw = (t.get("date") or "")[:10]
        if not raw:
            continue
        delta = _safe_date_delta(raw, today)
        logger.debug("SCHEDULER preflight: ticket=%s date=%s delta=%d", t.get("key"), raw, delta)
        if 0 <= delta <= 2:
            upcoming.append({**t, "_delta": delta})

    if not upcoming:
        logger.info("SCHEDULER: preflight — no tickets due in 48h, skipping (queue had %d tickets, today=%s)", len(queue), today)
        return

    upcoming.sort(key=lambda x: (x["_delta"], x["date"]))

    # Group by day label, build compact table
    groups: dict[str, list[str]] = {"🔴 TODAY": [], "🟡 Tomorrow": [], "🟠 In 2 days": []}
    for t in upcoming[:20]:
        delta     = t["_delta"]
        day_label = "🔴 TODAY" if delta == 0 else ("🟡 Tomorrow" if delta == 1 else "🟠 In 2 days")
        ticket    = t["key"]
        client    = t.get("client", "")
        status    = t.get("status", "")

        audited = _al.get_audit_for_ticket(ticket)
        if not audited:
            audited = next((v for v in _audited_sendouts.values() if v.get("ticket_key") == ticket), None)
        if audited:
            overall = audited.get("overall", "")
            conf    = audited.get("confidence", -1)
            conf_str = f" {conf}%" if conf and conf >= 0 else ""
            if overall == "FAIL":
                _check_names = ["scheduling", "copy", "footer", "cta", "tags", "images"]
                _failed = [c.upper() for c in _check_names if audited.get(c, "").upper() == "FAIL"]
                _fail_str = f" — _{', '.join(_failed)}_" if _failed else ""
                audit_str = f"❌{conf_str}{_fail_str}"
            else:
                audit_str = f"✅{conf_str}"
        else:
            audit_str = "⏳"

        jira_link = f"{JIRA_SERVER.rstrip('/')}/browse/{ticket}"
        params    = {"ticket": ticket, "client": client}
        # Include sendout_id in the deep-link if the audit recorded it
        _sendout_id = (audited or {}).get("sendout_id", "")
        if _sendout_id:
            params["sendout"] = _sendout_id
        app_link  = f"{APP_BASE_URL.rstrip('/')}?{_up.urlencode(params)}"
        groups[day_label].append(
            f"<{jira_link}|{ticket}> {client} | _{status}_ | AI: {audit_str} | <{app_link}|Validator ↗>"
        )

    sections: list[str] = [
        f"*{len(upcoming)}* sendout(s) going live in the next 48 h — please review."
    ]
    for day_label, rows in groups.items():
        if rows:
            sections.append(f"*{day_label}*\n" + "\n".join(rows))

    _send_slack_block(
        header="🔔 Preflight Check — Upcoming Sendouts",
        sections=sections,
    )
    logger.info("SCHEDULER: preflight alert sent for %d tickets", len(upcoming))

    # Persist run so UI can display history even when Slack is unavailable
    pf_tickets = []
    for t in upcoming[:15]:
        tk = t["key"]
        audited = _al.get_audit_for_ticket(tk)
        pf_tickets.append({
            "key":        tk,
            "client":     t.get("client", ""),
            "date":       t.get("date", ""),
            "delta":      t.get("_delta", -1),
            "status":     t.get("status", ""),
            "audit":      audited.get("overall") if audited else None,
            "confidence": audited.get("confidence", -1) if audited else -1,
        })
    _al.record_preflight(pf_tickets, sent_slack=True)




async def _job_auto_audit() -> None:
    """
    Daily 09:00 UTC — find JIRA tickets going live in ≤24h that haven't been
    AI-audited yet, run a full audit for each, post results to Slack.

    Uses the same _validate_single_ticket_ai pipeline as the bulk UI:
    _fetch_and_enrich → _build_audit_payload → run_ai_audit → BulkTicketResult.
    This means all improvements (URL diff, ALDI Portugal shop check, structured
    output, proper tag normalization) apply to auto-audit too.
    """
    import asyncio as _asyncio
    import urllib.parse as _up
    from datetime import datetime as _dt
    from bulk_validator import _validate_single_ticket_ai as _bv_ai

    logger.info("SCHEDULER: running auto-audit job")
    if not GEMINI_KEY:
        logger.info("SCHEDULER: auto-audit skipped — no GEMINI_API_KEY")
        return
    if not SLACK_WEBHOOK:
        logger.info("SCHEDULER: auto-audit skipped — no SLACK_WEBHOOK")
        return

    loop = _asyncio.get_event_loop()
    try:
        # Use raw queue — _validate_single_ticket_ai expects issue["fields"] structure
        raw_queue = await loop.run_in_executor(None, _cached_queue)
    except Exception as exc:
        logger.warning("SCHEDULER auto-audit: queue fetch failed: %s", exc)
        return

    today = _dt.utcnow().date()
    # Normalize each raw issue to get its date, then filter to today/tomorrow
    imminent = [
        issue for issue in raw_queue
        if _safe_date_delta((_normalize_issue(issue).get("date") or "")[:10], today) in (0, 1)
    ]

    if not imminent:
        logger.info("SCHEDULER: auto-audit — no imminent tickets, skipping")
        return

    logger.info("SCHEDULER auto-audit: %d imminent ticket(s) found", len(imminent))

    # Tickets going live TODAY are always re-audited (stale results may be from
    # before the sendout was fixed). Tickets going live tomorrow are skipped if
    # already audited today (avoid redundant checks).
    _today_keys: set[str] = set()
    _already_audited_keys: set[str] = {v.get("ticket_key") for v in _audited_sendouts.values()}
    for _iss in imminent:
        _tk  = _iss.get("key", "")
        _nd  = _normalize_issue(_iss)
        _raw = (_nd.get("date") or "")[:10]
        try:
            _delta = _safe_date_delta(_raw, today)
        except Exception:
            _delta = 99
        if _delta == 0:
            _today_keys.add(_tk)   # always re-audit today's tickets
        elif _tk and _al.get_audit_for_ticket(_tk):
            _already_audited_keys.add(_tk)   # skip tomorrow+ if already done

    gsheet_data   = _gsheet()
    audited_count = 0
    skipped_count = 0
    passed_rows: list[str] = []   # collected for single summary message
    failed_rows: list[str] = []   # collected for single summary message

    for issue in imminent[:5]:   # cap at 5 to respect Gemini rate limits
        norm       = _normalize_issue(issue)
        ticket_key = norm["key"]
        client     = norm.get("client", "")
        jira_date  = norm.get("date", "")

        _going_live_today = ticket_key in _today_keys
        if not _going_live_today and ticket_key in _already_audited_keys:
            skipped_count += 1
            logger.info("SCHEDULER auto-audit: %s already audited (not today), skipping", ticket_key)
            continue

        logger.info("SCHEDULER auto-audit: processing %s (%s) for %s", ticket_key, client, jira_date)

        try:
            result = await loop.run_in_executor(
                None, _bv_ai,
                # Positional args matching _validate_single_ticket_ai signature:
                # (issue, gsheet_data, jira_server, jira_email, jira_token,
                #  api_token, gemini_key, gemini_model, examples_lib=None)
                issue, gsheet_data,
                JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN,
                API_TOKEN, GEMINI_KEY, GEMINI_BULK_MODEL,
                _examples_lib.select_for_audit(client),
            )
        except Exception as exc:
            logger.warning("SCHEDULER auto-audit: audit failed for %s: %s", ticket_key, exc)
            continue

        if result.status == "error":
            logger.warning("SCHEDULER auto-audit: %s errored — %s", ticket_key, result.error_msg)
            continue
        if result.status == "skipped":
            logger.info("SCHEDULER auto-audit: %s skipped — %s", ticket_key, result.error_msg)
            skipped_count += 1
            continue

        issues     = result.issues_found or 0
        confidence = result.confidence
        sendout_id = result.sendout_id or ""

        # Record so preflight (runs after) can show real AI status
        if sendout_id:
            _audited_sendouts[sendout_id] = {
                "ticket_key": ticket_key,
                "client":     client,
                "issues":     issues,
                "confidence": confidence,
                "ts":         _dt.utcnow().isoformat(),
            }
        _al.record_audit(
            ticket_key=ticket_key,
            client=client,
            sendout_id=sendout_id,
            overall="FAIL" if issues > 0 else "PASS",
            structured=result.structured or None,
            confidence=confidence,
            triggered_by="auto",
            user="🤖 Auto-Audit",
            failed_checks=[c["label"] for c in (getattr(result, "checks", None) or []) if not c.get("ok")],
        )
        # Also record in in-memory log so dashboard reflects auto-audit results
        _auto_failed_checks = [c["label"] for c in (getattr(result, "checks", None) or []) if not c.get("ok")]
        global _validation_log
        _validation_log = record_validation(
            ticket_key=ticket_key, client=client,
            status="failed" if issues > 0 else "passed",
            mode="ai", issues=issues, approved=False,
            log=_validation_log,
            user="🤖 Auto-Audit",
            failed_checks=_auto_failed_checks,
            confidence=confidence if confidence >= 0 else None,
        )
        audited_count += 1
        already_audited_keys.add(ticket_key)

        params    = {"ticket": ticket_key, "client": client, "sendout": sendout_id}
        app_link  = f"{APP_BASE_URL.rstrip('/')}?{_up.urlencode(params)}"
        jira_link = f"{JIRA_SERVER.rstrip('/')}/browse/{ticket_key}"

        conf_str = f" {confidence}%" if confidence >= 0 else ""
        if issues > 0:
            failed_labels = [c["label"] for c in (result.checks or []) if not c.get("ok")]
            checks_str = ", ".join(failed_labels[:4])
            failed_rows.append(
                f"❌{conf_str}  <{jira_link}|{ticket_key}> {client} — {jira_date}"
                f"  _{checks_str}_  <{app_link}|Open>"
            )
            try:
                write_ai_status_to_jira(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, ticket_key, "Rejected")
            except Exception:
                pass
        else:
            passed_rows.append(
                f"✅{conf_str}  <{jira_link}|{ticket_key}> {client} — {jira_date}"
                f"  <{app_link}|Open>"
            )
            try:
                write_ai_status_to_jira(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, ticket_key, "Approved")
            except Exception:
                pass

    # Single combined summary message
    if failed_rows or passed_rows:
        sections = []
        if failed_rows:
            sections.append(f"<!here>\n*❌ Failed ({len(failed_rows)})*\n" + "\n".join(failed_rows))
        if passed_rows:
            sections.append(f"*✅ Passed ({len(passed_rows)})*\n" + "\n".join(passed_rows))
        _send_slack_block(
            header=f"🤖 Auto-Audit complete — {len(failed_rows)} failed, {len(passed_rows)} passed",
            sections=sections,
        )

    logger.info("SCHEDULER: auto-audit done — %d audited, %d skipped", audited_count, skipped_count)


# ── APScheduler startup / shutdown ────────────────────────────────────────────

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler as _APScheduler
    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    logger.warning(
        "APScheduler not installed — proactive monitoring disabled. "
        "Run: pip install apscheduler"
    )

_scheduler = None


@app.on_event("startup")
async def _start_scheduler():
    import asyncio as _aio
    global _scheduler
    if not _APSCHEDULER_AVAILABLE:
        return
    _scheduler = _APScheduler()
    # Explicitly bind the running event loop so AsyncIOScheduler works correctly
    # inside FastAPI's async startup context (Python 3.10+ deprecates get_event_loop)
    _scheduler._event_loop = _aio.get_running_loop()
    # auto_audit runs first so preflight can show real AI results
    _scheduler.add_job(
        _job_auto_audit,      _CronTrigger(hour=8,  minute=30, timezone="UTC"), id="auto_audit"
    )
    _scheduler.add_job(
        _job_preflight_alert, _CronTrigger(hour=9,  minute=0,  timezone="UTC"), id="preflight"
    )
    _scheduler.add_job(
        _job_auto_audit,      _CronTrigger(hour=14, minute=0,  timezone="UTC"), id="auto_audit_pm"
    )
    _scheduler.start()
    logger.info(
        "APScheduler started: state=%s running=%s auto_audit@08:30+14:00, preflight@09:00 UTC",
        _scheduler.state, _scheduler.running,
    )


@app.on_event("shutdown")
async def _stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


@app.get("/api/scheduler/status")
async def scheduler_status(authorization: Optional[str] = Header(None)):
    """Return scheduler state — running jobs and next fire times."""
    _get_session(authorization)
    if not _scheduler:
        return {
            "running":           False,
            "reason":            "APScheduler not available or not started",
            "audited_sendouts":  len(_audited_sendouts),
            "jobs":              [],
        }
    # Use raw state for diagnostics; treat any non-stopped state as running
    raw_state = getattr(_scheduler, "state", -1)
    try:
        from apscheduler.schedulers.base import STATE_STOPPED
        is_running = (raw_state != STATE_STOPPED)
    except Exception:
        is_running = bool(_scheduler.running)
    jobs = [
        {"id": job.id, "next_run": str(job.next_run_time) if job.next_run_time else None}
        for job in _scheduler.get_jobs()
    ]
    logger.info("SCHEDULER_STATUS: state=%s running=%s jobs=%d", raw_state, is_running, len(jobs))
    return {
        "running":           is_running,
        "state":             raw_state,
        "jobs":              jobs,
        "audited_sendouts":  len(_audited_sendouts),
        "models": {
            "single":    GEMINI_MODEL,
            "bulk":      GEMINI_BULK_MODEL,
            "freestyle": GEMINI_PRO_MODEL,
        },
    }


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8502, reload=True)

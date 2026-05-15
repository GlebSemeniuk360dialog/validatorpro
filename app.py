"""
app.py — Streamlit UI layer.
All business logic lives in: config.py, utils.py, api_client.py,
                              parsers.py, schedule.py, ai_audit.py
"""

import base64
import difflib
import json
import logging
import os
import datetime as _dt

import pandas as pd
import streamlit as st
import streamlit.components.v1 as st_components

from ai_audit import build_comparison_data, run_ai_audit, _is_audit_error
from ui_renderer import build_results_html, STREAMLIT_DARK_CSS, STREAMLIT_LIGHT_CSS
from bulk_validator import BulkTicketResult, run_bulk_validation, run_bulk_regular_check
from api_client import (
    approve_ticket_jira,
    fetch_account_leaflets,
    fetch_api_data,
    fetch_api_key_via_dma,
    fetch_dma_image_bytes,
    fetch_pending_sendouts,
    fetch_service_desk_issues_paginated,
    fetch_template_data,
    fetch_ticket_data,
    write_ai_status_to_jira,
)
from config import CLIENT_CONFIGS, CLIENT_ALIASES, GSHEET_COLS, GSHEET_DEFAULT_URL, TEAM_EMAILS
from parsers import pick_carousel_parser
from schedule import fetch_gsheet_data_csv, get_client_schedule, get_client_schedule_wide
from features import (
    validate_scheduled_date,
    check_url_reachability,
    export_bulk_results_csv,
    build_dashboard_data,
    record_validation,
)
from utils import (
    clean_button_text,
    compare_urls_smart,
    detect_client_from_text,
    extract_all_tags,
    extract_api_urls_advanced,
    extract_urls,
    highlight_diff,
    is_media_url,
)

import os

# Load .env if present (local testing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="360Dialog Validator Pro", layout="wide", page_icon="⚡")

ENV_JIRA_TOKEN    = os.environ.get("JIRA_TOKEN", "")
ENV_API_TOKEN     = os.environ.get("DMA_API_TOKEN", "")
ENV_GEMINI_KEY    = os.environ.get("GEMINI_API_KEY", "")
ENV_SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
APP_BASE_URL      = os.environ.get("APP_BASE_URL", "http://104.238.167.142:8501")


def _send_slack_thread_reply(ticket_key: str, approver: str):
    """Reply in the Slack thread of the original alert when a ticket is approved."""
    webhook = st.session_state.get("slack_webhook") or ENV_SLACK_WEBHOOK
    if not webhook:
        return
    try:
        import urllib.request, json as _json
        user = st.session_state.get("authenticated_name", "Unknown")
        from datetime import datetime as _dt2
        timestamp = _dt2.now().strftime("%H:%M")
        payload = {
            "text": f"✅ {ticket_key} approved by {user} ({approver}) at {timestamp}",
        }
        req = urllib.request.Request(
            webhook,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        logging.warning("Slack thread reply failed: %s", exc)


def _send_slack_alert(ticket_key: str, client: str, mode: str, issues: int,
                      jira_server: str = "", failed_checks: list = None,
                      sendout_id: str = ""):
    """Send a Slack notification when an AI audit fails."""
    webhook = st.session_state.get("slack_webhook") or ENV_SLACK_WEBHOOK
    if not webhook:
        return
    try:
        import urllib.request, json as _json, urllib.parse as _up
        ticket_url = f"{jira_server.rstrip('/')}/browse/{ticket_key}" if jira_server else ticket_key
        user = st.session_state.get("authenticated_name", "Unknown")

        # Build deep link into the app with ticket + sendout pre-selected
        params = {"ticket": ticket_key}
        if sendout_id:
            params["sendout"] = sendout_id
        app_deep_link = f"{APP_BASE_URL}?{_up.urlencode(params)}"

        # Build failed checks summary
        if failed_checks:
            checks_text = "\n".join(f"• {c}" for c in failed_checks[:10])
        else:
            checks_text = f"{issues} issue(s) found"

        payload = {
            "text": f"<!here> ❌ *AI Audit Failed — Manual Review Required*",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "❌ AI Audit Failed — Manual Review Required"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "<!here> Please review this sendout manually."}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Ticket:*\n<{ticket_url}|{ticket_key}>"},
                        {"type": "mrkdwn", "text": f"*Client:*\n{client}"},
                        {"type": "mrkdwn", "text": f"*Mode:*\n{mode}"},
                        {"type": "mrkdwn", "text": f"*Checked by:*\n{user}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*❌ Failed checks:*\n{checks_text}"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in Validator"},
                            "url": app_deep_link,
                            "style": "danger",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in JIRA"},
                            "url": ticket_url,
                        },
                    ]
                },
            ]
        }
        req = urllib.request.Request(
            webhook,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        _audit("SLACK_ALERT", f"{ticket_key} {client} — {issues} issue(s)")
    except Exception as exc:
        logging.warning("Slack alert failed: %s", exc)

# Dark theme injected via ui_renderer.STREAMLIT_DARK_CSS below


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def get_image_html(img_data) -> str:
    if not img_data:
        return ""
    if isinstance(img_data, bytes):
        b64 = base64.b64encode(img_data).decode()
        return f'<img src="data:image/png;base64,{b64}" style="width:100%;border-radius:8px;display:block;margin-bottom:10px;">'
    if isinstance(img_data, str) and img_data.startswith("http"):
        return f'<img src="{img_data}" style="width:100%;border-radius:8px;display:block;margin-bottom:10px;">'
    return ""


# ---------------------------------------------------------------------------
# Session-state initialisers
# ---------------------------------------------------------------------------

def _init_session() -> None:
    defaults = {
        "gsheet_data": None,
        "selected_ticket_key": "",
        "queue_data": [],
        "cached_jira_scan": {},
        "dark_mode": False,
        "validation_log": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state["gsheet_data"] is None:
        st.session_state["gsheet_data"] = fetch_gsheet_data_csv(GSHEET_DEFAULT_URL)


def _handle_deep_link() -> None:
    """Read ?ticket=MAS-4141&sendout=xxx from URL and pre-select in session state."""
    try:
        params = st.query_params
        ticket = params.get("ticket", "")
        sendout = params.get("sendout", "")
        if ticket and not st.session_state.get("_deep_link_loaded"):
            st.session_state["selected_ticket_key"] = ticket
            if sendout:
                st.session_state["deep_link_sendout"] = sendout
            st.session_state["_deep_link_loaded"] = True
            # Clear params from URL so refresh doesn't re-trigger
            st.query_params.clear()
    except Exception:
        pass
    defaults = {
        "gsheet_data": None,
        "selected_ticket_key": "",
        "queue_data": [],
        "cached_jira_scan": {},
        "dark_mode": False,
        "validation_log": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state["gsheet_data"] is None:
        st.session_state["gsheet_data"] = fetch_gsheet_data_csv(GSHEET_DEFAULT_URL)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

# Hardcoded — not shown to user
JIRA_SERVER    = "https://360dialog.atlassian.net"
JIRA_EMAIL     = "gleb.semeniuk@360dialog.com"
GEMINI_MODEL   = "gemini-2.5-pro"


def render_sidebar():
    with st.sidebar:
        # User info + logout
        user_name = st.session_state.get("authenticated_name", "")
        if user_name:
            st.markdown(f"**{user_name}**")
            if st.button("Sign out", width="stretch"):
                _audit("LOGOUT", "")
                st.session_state.pop("authenticated_user", None)
                st.session_state.pop("authenticated_name", None)
                st.rerun()
            st.divider()

        show_inspector = st.checkbox("JIRA Field Inspector", value=False)

        if st.button("Refresh G-Sheet", width='stretch'):
            st.session_state["gsheet_data"] = fetch_gsheet_data_csv(GSHEET_DEFAULT_URL)
            st.toast("G-Sheet refreshed")

        if st.button("Clear Cache", width='stretch'):
            st.session_state["cached_jira_scan"] = {}
            st.toast("Cache cleared")

    jira_token = ENV_JIRA_TOKEN
    api_token  = ENV_API_TOKEN
    gemini_key = ENV_GEMINI_KEY

    with st.sidebar:
        with st.expander("Slack Notifications", expanded=False):
            slack_url = st.text_input(
                "Webhook URL",
                value=st.session_state.get("slack_webhook", ENV_SLACK_WEBHOOK),
                type="password",
                placeholder="https://hooks.slack.com/...",
                key="slack_webhook_input",
            )
            if slack_url:
                st.session_state["slack_webhook"] = slack_url

    return JIRA_SERVER, JIRA_EMAIL, jira_token, api_token, gemini_key, GEMINI_MODEL, show_inspector


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Ticket queue
# ---------------------------------------------------------------------------

import hashlib as _hashlib
import hmac as _hmac

# ── Audit logger ──────────────────────────────────────────────────────────────
_AUDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "audit.log")
_audit_logger = logging.getLogger("audit")
if not _audit_logger.handlers:
    _fh = logging.FileHandler(_AUDIT_LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s\t%(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _audit_logger.addHandler(_fh)
    _audit_logger.setLevel(logging.INFO)


def _audit(action: str, detail: str = ""):
    """Log a user action to audit.log."""
    user = st.session_state.get("authenticated_name", "unknown")
    _audit_logger.info("%s\t%s\t%s", user, action, detail)

# ── User credentials (username → (full_name, sha256_password_hash)) ──────────
_USERS = {
    "gleb":    ("Gleb Semeniuk",   "0df575df0654539e8fc2e39038cd153f7f012ce5cee3b2bc4301b4a7ea9738bb"),
    "martina": ("Martina Sesar",   "3127e30f336fbcc6c6ee3f87c2e4aa3509120b48fa3b841cf91eb91512c49824"),
    "alex":    ("Alex Volkonitin", "554c22e0e5bc5d80b4a0015eddfc4a2556afb3879b98e8f1123652070a26b993"),
}


def _hash_pwd(pwd: str) -> str:
    return _hashlib.sha256(pwd.encode()).hexdigest()


def _render_login() -> bool:
    """Show login form. Returns True if user is authenticated."""
    if st.session_state.get("authenticated_user"):
        return True

    # Brute force protection — lockout after 5 failed attempts for 5 minutes
    _now = _dt.datetime.utcnow().timestamp()
    _attempts = st.session_state.setdefault("login_attempts", 0)
    _locked_until = st.session_state.get("login_locked_until", 0)

    if _locked_until > _now:
        _wait = int(_locked_until - _now)
        st.error(f"🔒 Too many failed attempts. Try again in {_wait} seconds.")
        return False

    st.markdown("""
    <style>
    [data-testid="stSidebar"] {display:none}
    .block-container {max-width:420px; margin:auto; padding-top:80px}
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### 🔍 Validator Pro — Sign in")
    st.markdown("---")

    username = st.text_input("Username", placeholder="gleb / martina / alex").strip().lower()
    password = st.text_input("Password", type="password")

    if st.button("Sign in →", type="primary", width="stretch"):
        entry = _USERS.get(username)
        if entry and _hmac.compare_digest(_hash_pwd(password), entry[1]):
            st.session_state["authenticated_user"] = username
            st.session_state["authenticated_name"] = entry[0]
            st.session_state["login_attempts"] = 0
            st.session_state.pop("login_locked_until", None)
            _audit_logger.info("%s\tLOGIN\t", entry[0])
            st.rerun()
        else:
            st.session_state["login_attempts"] = _attempts + 1
            if st.session_state["login_attempts"] >= 5:
                st.session_state["login_locked_until"] = _now + 300  # 5 min lockout
                st.session_state["login_attempts"] = 0
                _audit_logger.warning("LOCKOUT\tToo many failed attempts for username: %s", username)
                st.error("🔒 Too many failed attempts. Locked for 5 minutes.")
            else:
                remaining = 5 - st.session_state["login_attempts"]
                st.error(f"Invalid username or password. {remaining} attempt(s) remaining.")

    return False


def _jira_field_snapshot(jira: dict) -> dict:
    """Return a snapshot of key fields used for diff detection."""
    return {
        "description":     str(jira.get("description", ""))[:500],
        "cta_link":        str(jira.get("cta_link", "")),
        "cta_button":      str(jira.get("cta_button", "")),
        "footer_text":     str(jira.get("footer_text", "")),
        "date":            str(jira.get("date", "")),
        "gsheet_tags":     str(jira.get("gsheet_tags", "")),
        "gsheet_exclude":  str(jira.get("gsheet_exclude_tags", "")),
    }


def _jira_content_hash(jira: dict) -> str:
    """Hash key JIRA fields to detect changes."""
    import hashlib as _hl
    snap = _jira_field_snapshot(jira)
    return _hl.md5("|".join(snap.values()).encode()).hexdigest()


def _check_ticket_changed(ticket_key: str, jira: dict) -> tuple:
    """Return (changed: bool, diff: list[tuple[field, before, after]])."""
    store      = st.session_state.setdefault("ticket_hashes", {})
    snap_store = st.session_state.setdefault("ticket_snapshots", {})
    current      = _jira_content_hash(jira)
    current_snap = _jira_field_snapshot(jira)
    prev      = store.get(ticket_key)
    prev_snap = snap_store.get(ticket_key, {})

    diff = []
    if prev is not None and prev != current:
        for k, new_val in current_snap.items():
            old_val = prev_snap.get(k, "")
            if old_val != new_val:
                diff.append((k, old_val, new_val))

    store[ticket_key]      = current
    snap_store[ticket_key] = current_snap
    return (bool(diff), diff)


def _ticket_client(issue: dict) -> str:
    fields  = issue["fields"]
    summary = fields.get("summary", "")
    desc    = fields.get("description") or ""
    text    = f"{summary} {desc}".strip()

    # Detect by reporter email domain first (most reliable)
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
        if "rcs" in text.lower():
            return "Kaufland RCS"
        return "Kaufland WABA"
    if "penny.at" in reporter_email:
        return "PENNY Austria"

    # Keyword detection from summary
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("sonntag", "reminder", "prospekt living",
                                        "prospekt women", "prospekt grilling",
                                        "prospekt haushalt", "prospekt familien",
                                        "prospekt elektronik", "prospekt garten",
                                        "whatsapp chat prospekt")):
        return "ALDI Sued"

    return detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"
    fields  = issue["fields"]
    summary = fields.get("summary", "")
    desc    = fields.get("description") or ""
    text    = f"{summary} {desc}".strip()

    # Detect by reporter email domain first (most reliable)
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
        if "rcs" in text.lower():
            return "Kaufland RCS"
        return "Kaufland WABA"
    if "penny.at" in reporter_email:
        return "PENNY Austria"

    # Keyword detection from summary
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("sonntag", "reminder", "prospekt living",
                                        "prospekt women", "prospekt grilling",
                                        "prospekt haushalt", "prospekt familien",
                                        "prospekt elektronik", "prospekt garten",
                                        "whatsapp chat prospekt")):
        return "ALDI Sued"

    return detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"
    fields  = issue["fields"]
    summary = fields.get("summary", "")
    desc    = fields.get("description") or ""
    text    = f"{summary} {desc}".strip()

    # Detect by reporter email domain first (most reliable)
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
        # Distinguish RCS vs WABA from summary
        if "rcs" in text.lower():
            return "Kaufland RCS"
        return "Kaufland WABA"
    if "penny.at" in reporter_email:
        return "PENNY Austria"

    # Keyword detection from summary
    text_lower = text.lower()
    if any(kw in text_lower for kw in ("sonntag", "reminder", "prospekt living",
                                        "prospekt women", "prospekt grilling",
                                        "prospekt haushalt", "prospekt familien",
                                        "prospekt elektronik", "prospekt garten",
                                        "whatsapp chat prospekt")):
        return "ALDI Sued"

    return detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"




def _render_sendout_picker(ticket_key: str, ticket_row, api_token: str):
    """Shown inline after a ticket is selected — lets user pick the matching DMA sendout."""
    client = ticket_row.get("Client", "")
    jira_date_str = str(ticket_row.get("Date", ""))
    account_id = CLIENT_CONFIGS.get(client, {}).get("account_id")

    if not account_id:
        return

    # Fetch pending sendouts (cached)
    cache_key = f"dma_tasks_{account_id}"
    if cache_key not in st.session_state:
        with st.spinner(f"Fetching DMA sendouts for {client}..."):
            st.session_state[cache_key] = fetch_pending_sendouts(api_token, account_id)

    tasks = st.session_state.get(cache_key, [])
    if not tasks:
        st.warning(f"No pending sendouts found in DMA for {client}.")
        return

    # Sort by date
    from datetime import datetime as _dt
    def _task_date(t):
        try: return _dt.fromisoformat(str(t.get("scheduled_date",""))[:10])
        except: return _dt(2099,1,1)
    tasks_sorted = sorted(tasks, key=_task_date)

    # Filter out inactive sendouts
    tasks_sorted = [t for t in tasks_sorted if t.get("is_active", True) is not False]

    if not tasks_sorted:
        st.warning(f"No active pending sendouts found in DMA for {client}.")
        return

    # Try to auto-match by date
    auto_idx = 0
    try:
        jira_date = _dt.fromisoformat(jira_date_str[:10]).date()
        for i, t in enumerate(tasks_sorted):
            try:
                if _dt.fromisoformat(str(t.get("scheduled_date",""))[:10]).date() == jira_date:
                    auto_idx = i
                    break
            except: pass
    except: pass

    st.markdown("---")
    st.markdown(f"#### 📋 Pick DMA Sendout for **{ticket_key}**")

    task_options = [
        f"{str(t.get('scheduled_date',''))[:10]}  |  {t.get('name') or t.get('campaign_name') or t.get('task_name','')}  |  {t.get('id') or t.get('task_id','')}"
        for t in tasks_sorted
    ]

    picked_idx = st.selectbox(
        "Matching sendouts from DMA API:",
        range(len(task_options)),
        format_func=lambda x: task_options[x],
        index=auto_idx,
        key=f"ps_sel_{ticket_key}",
    )

    picked_task = tasks_sorted[picked_idx]
    picked_sid = str(picked_task.get("id") or picked_task.get("task_id", ""))

    col_sid, col_go = st.columns([3, 1])
    with col_sid:
        st.code(picked_sid, language=None)
    with col_go:
        if st.button("Validate", type="primary", width="stretch", key=f"ps_validate_{ticket_key}"):
            st.session_state["selected_ticket_key"]        = ticket_key
            st.session_state["selected_client_from_queue"] = client
            st.session_state["_last_loaded_key"]           = ticket_key
            st.session_state["ps_override_sid"]            = picked_sid
            st.session_state["bulk_trigger"]               = False
            st.session_state["validation_run"]             = False
            st.rerun()


def render_queue(jira_server, jira_email, jira_token, api_token=""):
    """Ticket queue — original st.dataframe design with multi-row selection."""
    col_btn, col_search = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Refresh Queue", width='stretch'):
            if jira_server and jira_email and jira_token:
                st.session_state["queue_data"] = fetch_service_desk_issues_paginated(
                    jira_server, jira_email, jira_token
                )
                st.rerun()
    with col_search:
        search_q = st.text_input("Search tickets", placeholder="Type key or summary...",
                                 label_visibility="collapsed")

    if not st.session_state.get("queue_data"):
        return


    table_rows = []
    for issue in st.session_state["queue_data"]:
        fields = issue["fields"]
        table_rows.append({
            "Key":    issue["key"],
            "Summary": fields.get("summary", ""),
            "Client":  _ticket_client(issue),
            "Date":    fields.get("customfield_12665", "No Date"),
            "Status":  fields.get("status", {}).get("name", ""),
        })

    df = pd.DataFrame(table_rows)
    # Sort descending by date — newest tickets first
    if "Date" in df.columns:
        df = df.sort_values("Date", ascending=False, ignore_index=True)

    # Client filter
    if "Client" in df.columns:
        clients_in_queue = sorted(df["Client"].unique().tolist())
        col_cf, _ = st.columns([1, 3])
        with col_cf:
            client_filter = st.selectbox(
                "Filter by client",
                ["All clients"] + clients_in_queue,
                label_visibility="collapsed",
                key="queue_client_filter",
            )
            if client_filter != "All clients":
                df = df[df["Client"] == client_filter].reset_index(drop=True)
    if search_q:
        mask = df.apply(lambda col: col.astype(str).str.contains(search_q, case=False)).any(axis=1)
        df = df[mask]

    col_count, col_hint, col_clr = st.columns([2, 2, 1])
    col_count.write(f"**Pending Tickets: {len(df)}**")
    col_hint.caption("Select one ticket to validate · select multiple for bulk actions")
    with col_clr:
        if st.button("✕ Clear", width='stretch', key="btn_clr_top"):
            st.session_state["queue_selected"] = set()
            st.rerun()

    # Select-all checkbox above the table
    all_keys = df["Key"].tolist()
    if "queue_selected" not in st.session_state:
        st.session_state["queue_selected"] = set()

    col_sa, _ = st.columns([1, 5])
    with col_sa:
        current_all = set(all_keys) <= st.session_state["queue_selected"] and len(all_keys) > 0
        if st.checkbox("Select all", value=current_all, key="chk_select_all"):
            st.session_state["queue_selected"] |= set(all_keys)
        else:
            st.session_state["queue_selected"] -= set(all_keys)

    selection = st.dataframe(
        df,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        width='stretch',
        column_config={
            "Key":     st.column_config.TextColumn("ID",           width="small"),
            "Summary": st.column_config.TextColumn("Summary",      width="large"),
            "Client":     st.column_config.TextColumn("Client",       width="medium"),
            "Date":       st.column_config.DateColumn("Sendout Date", format="YYYY-MM-DD"),
            "Status":     st.column_config.TextColumn("Status",       width="small"),
        },
    )

    # Sync dataframe selection → session state
    selected_rows = selection.selection.rows
    if selected_rows:
        selected_keys = [df.iloc[r]["Key"] for r in selected_rows]
    else:
        selected_keys = []

    if not selected_keys:
        return

    if len(selected_keys) == 1:
        key = selected_keys[0]
        row = df[df["Key"] == key].iloc[0]
        c_info, c_go = st.columns([3, 1])
        with c_info:
            st.info(f"**{key}** — ready to validate")
        with c_go:
            if st.button("▶ Load ticket", type="primary", width='stretch'):
                st.session_state["selected_ticket_key"]        = key
                st.session_state["selected_client_from_queue"] = row["Client"]
                st.session_state["_last_loaded_key"]           = key
                st.session_state["queue_selected"]             = set()
                st.session_state["bulk_trigger"]               = False
                st.session_state["validation_run"]             = False
                # Clear any previous sendout picker state
                st.session_state.pop("ps_picked_sid", None)
                st.session_state.pop("ps_pending_tasks", None)
                st.rerun()

        # ── Step 2: Sendout picker (shown after ticket is loaded) ──
        loaded_key = st.session_state.get("selected_ticket_key", "")
        if loaded_key == key and api_token:
            _render_sendout_picker(key, row, api_token)
    else:
        st.info(f"**{len(selected_keys)} tickets selected:** {', '.join(selected_keys)}")
        col_b1, col_b2, col_b3 = st.columns([2, 2, 1])
        with col_b1:
            if st.button("⚡ Regular Bulk Check", type="primary", width='stretch'):
                key_set = set(selected_keys)
                st.session_state["bulk_tickets"]   = [iss for iss in st.session_state["queue_data"] if iss["key"] in key_set]
                st.session_state["bulk_trigger"]   = True
                st.session_state["bulk_mode"]      = "regular"
                st.session_state["validation_run"] = False
                st.session_state["queue_selected"] = set()
                st.rerun()
        with col_b2:
            if st.button("🤖 AI Bulk Audit", width='stretch'):
                key_set = set(selected_keys)
                st.session_state["bulk_tickets"]   = [iss for iss in st.session_state["queue_data"] if iss["key"] in key_set]
                st.session_state["bulk_trigger"]   = True
                st.session_state["bulk_mode"]      = "ai"
                st.session_state["validation_run"] = False
                st.session_state["queue_selected"] = set()
                st.rerun()
        with col_b3:
            if st.button("✕ Clear selection", width='stretch'):
                st.session_state["queue_selected"] = set()
                st.rerun()


def _get_schedule_wide(gsheet_data, client):
    """Wide-window schedule lookup (±30 days) for the control panel."""
    return get_client_schedule_wide(gsheet_data, client, days_back=3, days_forward=30)


def render_control_panel(jira_server, jira_email, jira_token, api_token=""):
    selected_key = st.session_state.get("selected_ticket_key", "")
    scan_ticket: dict = {}

    # ── Fetch JIRA ticket data and detect client ──
    if selected_key and jira_server and jira_token:
        cache = st.session_state.setdefault("cached_jira_scan", {})
        if selected_key not in cache:
            cache[selected_key] = fetch_ticket_data(jira_server, jira_email, jira_token, selected_key)
        scan_ticket = cache.get(selected_key) or {}

        if scan_ticket:
            full_text = f"{scan_ticket.get('description', '')} {scan_ticket.get('segment', '')}".strip()
            if "reminder" in full_text.lower():
                detected = "ALDI Sued"
            else:
                detected = detect_client_from_text(full_text, list(CLIENT_CONFIGS.keys()))

            # Only write the JIRA-detected client if this ticket was NOT
            # loaded from the queue (queue already set the right client).
            # _last_loaded_key is set by "Load ticket" to lock the queue value.
            if detected and detected in CLIENT_CONFIGS:
                if st.session_state.get("_last_loaded_key") != selected_key:
                    # Ticket typed manually — use JIRA detection
                    st.session_state["selected_client_from_queue"] = detected
                    st.session_state["_last_loaded_key"] = selected_key
                # else: loaded from queue, keep the queue-detected client as-is

    # ── Client selectbox ──
    all_clients = list(CLIENT_CONFIGS.keys())
    stored_client = st.session_state.get("selected_client_from_queue", "")
    det_idx = all_clients.index(stored_client) if stored_client in all_clients else 0

    auto_sendout_id = auto_leaflet_url = auto_gsheet_tags = auto_exclude_tags = ""

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        # Key includes both the ticket AND the stored client so Streamlit
        # re-renders the widget (respecting index=) whenever either changes.
        client = st.selectbox("🎯 Client Context", all_clients, index=det_idx,
                              key=f"ctrl_client_{selected_key}_{stored_client}")
        # If user manually changes client, persist it and lock key
        if client != stored_client:
            st.session_state["selected_client_from_queue"] = client
            st.session_state["_last_loaded_key"] = selected_key

    with col2:
        # Use a key that changes when the selected ticket changes — this forces
        # Streamlit to re-render the widget with the new value
        t_id = st.text_input("🎫 Ticket ID", value=selected_key,
                             key=f"ctrl_tid_{selected_key}")
        if t_id != selected_key:
            st.session_state["selected_ticket_key"] = t_id
            # Reset client detection when ticket changes manually
            st.session_state.pop("_last_loaded_key", None)
            st.rerun()

    with col3:
        gsheet_data = st.session_state.get("gsheet_data", [])
        schedule = _get_schedule_wide(gsheet_data, client) if client and gsheet_data else []

        # ── Step 1: fetch pending sendouts from DMA API and match by JIRA date ──
        # Skip if user already manually picked a sendout for this ticket
        manual_sid_key = f"manual_sid_{selected_key}"
        api_sendout_id = st.session_state.get(manual_sid_key, "")

        if not api_sendout_id:
            cfg = CLIENT_CONFIGS.get(client, {})
            account_id = cfg.get("account_id")
            jira_date_str = str(scan_ticket.get("date", "") if scan_ticket else "")

            if account_id and api_token and jira_date_str:
                cache_key = f"dma_tasks_{account_id}"
                if cache_key not in st.session_state:
                    with st.spinner("Fetching pending sendouts from DMA..."):
                        st.session_state[cache_key] = fetch_pending_sendouts(api_token, account_id)
                pending_tasks = st.session_state.get(cache_key, [])

                from datetime import datetime as _dt
                try:
                    jira_date = _dt.fromisoformat(jira_date_str.split("T")[0]).date()
                except Exception:
                    jira_date = None

                if jira_date and pending_tasks:
                    import difflib as _dl2
                    date_matches = []
                    for task in pending_tasks:
                        if not task.get("is_active", True):
                            continue
                        task_date_raw = str(task.get("scheduled_date", "") or task.get("date", ""))
                        try:
                            task_date = _dt.fromisoformat(task_date_raw[:10]).date()
                        except Exception:
                            continue
                        if task_date == jira_date:
                            date_matches.append(task)

                    if date_matches:
                        jira_summary = str(scan_ticket.get("summary", "") if scan_ticket else "")
                        if len(date_matches) == 1 or not jira_summary:
                            api_sendout_id = str(date_matches[0].get("id") or date_matches[0].get("task_id", ""))
                        else:
                            import difflib as _dl3
                            summary_words = set(jira_summary.lower().split())
                            def _score(task):
                                tn = (task.get("name") or task.get("campaign_name") or "").lower()
                                hits = sum(1 for w in summary_words if len(w) > 3 and w in tn)
                                sim = _dl3.SequenceMatcher(None, jira_summary.lower(), tn).ratio()
                                return hits * 10 + sim
                            best = max(date_matches, key=_score)
                            api_sendout_id = str(best.get("id") or best.get("task_id", ""))

        if api_sendout_id:
            auto_sendout_id = api_sendout_id

        # ── Step 2: G-Sheet row for tags / leaflet URL ──
        row_match_idx = 0
        if t_id and schedule:
            for i, r in enumerate(schedule):
                jira_link = str(r.get(GSHEET_COLS["jira_link"], ""))
                if t_id == jira_link.strip() or t_id in jira_link:
                    row_match_idx = i
                    break

        if schedule:
            sel_idx = st.selectbox(
                f"📅 G-Sheet row for {client}",
                range(len(schedule)),
                format_func=lambda x: schedule[x]["_display_str"],
                index=row_match_idx,
                key=f"ctrl_sched_{client}",
            )
            selected_row = schedule[sel_idx]
            auto_leaflet_url  = str(selected_row.get(GSHEET_COLS["leaflet"],      "")).replace("nan", "").strip()
            auto_gsheet_tags  = str(selected_row.get(GSHEET_COLS["include_tags"], "")).replace("nan", "").strip()
            auto_exclude_tags = str(selected_row.get(GSHEET_COLS["exclude_tags"], "")).replace("nan", "").strip()
        else:
            st.caption("No upcoming rows in G-Sheet for this client.")

    # Override with retried sendout ID if user just corrected a 404
    if st.session_state.get("retry_sendout_id_value"):
        auto_sendout_id = st.session_state.pop("retry_sendout_id_value")

    # Override with sendout ID picked from sendout picker — and persist it
    if st.session_state.get("ps_override_sid"):
        auto_sendout_id = st.session_state.pop("ps_override_sid")
        # Persist so subsequent reruns (e.g. clicking RUN) don't overwrite it
        st.session_state[f"manual_sid_{selected_key}"] = auto_sendout_id

    # Clear persisted manual SID if ticket changes
    for k in list(st.session_state.keys()):
        if k.startswith("manual_sid_") and k != f"manual_sid_{selected_key}":
            del st.session_state[k]

    # Show found sendout info cleanly, allow override
    if auto_sendout_id:
        st.caption(f"Sendout found: `{auto_sendout_id[:36]}`")
    s_id = st.text_input("Sendout ID (override)", value=auto_sendout_id,
                         key=f"ctrl_sid_{auto_sendout_id or 'empty'}", label_visibility="collapsed",
                         placeholder="Sendout ID auto-detected — override if needed")

    return client, t_id, s_id, scan_ticket, auto_leaflet_url, auto_gsheet_tags, auto_exclude_tags


# ---------------------------------------------------------------------------
# Pending Sendouts tab
# ---------------------------------------------------------------------------

def render_pending_sendouts(jira_server, jira_email, jira_token, api_token):
    """Show all pending DMA sendouts for the next 7 days across all clients,
    paired with JIRA tickets so user can pick a pair to validate."""
    st.markdown("### 📋 Pending Sendouts — Next 7 Days")
    st.caption("Select a JIRA ticket and a DMA sendout to validate together.")

    if not api_token:
        st.warning("⚠️ DMA API Token required.")
        return

    col_ref, col_act = st.columns(2)

    # ── Left: JIRA queue ──
    with col_ref:
        st.markdown("#### 🎫 JIRA Tickets")
        if st.button("Refresh Queue", key="ps_refresh_jira", width="stretch"):
            st.session_state.pop("queue_data", None)
            st.rerun()

        queue = st.session_state.get("queue_data", [])
        if not queue and jira_token:
            with st.spinner("Loading JIRA queue..."):
                queue = fetch_service_desk_issues_paginated(jira_server, jira_email, jira_token)
                st.session_state["queue_data"] = queue

        if queue:
            jira_rows = []
            for issue in queue:
                summary = issue["fields"].get("summary", "")
                desc = issue["fields"].get("description") or ""
                text = f"{summary} {desc}".strip()
                detected = detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"
                jira_rows.append({
                    "Key":     issue["key"],
                    "Summary": summary,
                    "Client":  detected,
                    "Date":    issue["fields"].get("customfield_12665", ""),
                })
            import pandas as _pd
            jira_df = _pd.DataFrame(jira_rows)
            jira_sel = st.dataframe(
                jira_df, hide_index=True,
                on_select="rerun", selection_mode="single-row",
                use_container_width=True,
                column_config={
                    "Key":     st.column_config.TextColumn("Ticket", width="small"),
                    "Summary": st.column_config.TextColumn("Summary", width="large"),
                    "Client":  st.column_config.TextColumn("Client", width="medium"),
                    "Date":    st.column_config.TextColumn("Date", width="small"),
                },
                key="ps_jira_df",
            )
            selected_jira = None
            if jira_sel.selection.rows:
                selected_jira = jira_df.iloc[jira_sel.selection.rows[0]]
                st.success(f"Selected: **{selected_jira['Key']}** — {selected_jira['Client']}")
        else:
            st.info("No JIRA tickets loaded. Refresh queue or check token.")
            selected_jira = None

    # ── Right: DMA pending sendouts ──
    with col_act:
        st.markdown("#### 🚀 DMA Pending Sendouts")

        # Fetch for selected client's account, or let user pick client
        ps_client = None
        if "selected_jira" in dir() and selected_jira is not None:
            ps_client = selected_jira.get("Client")

        filter_client = st.selectbox(
            "Filter by client",
            ["All"] + list(CLIENT_CONFIGS.keys()),
            index=0 if not ps_client else (
                (["All"] + list(CLIENT_CONFIGS.keys())).index(ps_client)
                if ps_client in CLIENT_CONFIGS else 0
            ),
            key="ps_client_filter",
        )

        if st.button("Refresh Sendouts", key="ps_refresh_dma", width="stretch"):
            # Clear cached tasks for all accounts
            for k in list(st.session_state.keys()):
                if k.startswith("dma_tasks_"):
                    del st.session_state[k]
            st.rerun()

        # Collect sendouts — fetch for selected client or all clients
        all_tasks = []
        clients_to_fetch = (
            [filter_client] if filter_client != "All" else list(CLIENT_CONFIGS.keys())
        )
        for c in clients_to_fetch:
            acc_id = CLIENT_CONFIGS.get(c, {}).get("account_id")
            if not acc_id:
                continue
            cache_key = f"dma_tasks_{acc_id}"
            if cache_key not in st.session_state:
                tasks = fetch_pending_sendouts(api_token, acc_id)
                st.session_state[cache_key] = tasks
            for task in st.session_state.get(cache_key, []):
                task["_client"] = c
                all_tasks.append(task)

        if all_tasks:
            import pandas as _pd2
            dma_rows = []
            for task in all_tasks:
                dma_rows.append({
                    "Client":      task.get("_client", ""),
                    "Sendout ID":  str(task.get("task_id", task.get("id", ""))),
                    "Name":        str(task.get("task_name", task.get("campaign_name", ""))),
                    "Date":        str(task.get("scheduled_date", ""))[:10],
                    "Status":      str(task.get("status", "")),
                })
            dma_df = _pd2.DataFrame(dma_rows).sort_values("Date")
            dma_sel = st.dataframe(
                dma_df, hide_index=True,
                on_select="rerun", selection_mode="single-row",
                use_container_width=True,
                column_config={
                    "Client":     st.column_config.TextColumn("Client", width="medium"),
                    "Sendout ID": st.column_config.TextColumn("ID", width="medium"),
                    "Name":       st.column_config.TextColumn("Name", width="large"),
                    "Date":       st.column_config.TextColumn("Date", width="small"),
                    "Status":     st.column_config.TextColumn("Status", width="small"),
                },
                key="ps_dma_df",
            )
            selected_dma = None
            if dma_sel.selection.rows:
                selected_dma = dma_df.iloc[dma_sel.selection.rows[0]]
                st.success(f"Selected: **{selected_dma['Sendout ID']}** — {selected_dma['Name']}")
        else:
            st.info("No pending sendouts found.")
            selected_dma = None

    # ── Validate button ──
    st.divider()
    col_v1, col_v2, col_v3 = st.columns([2, 2, 1])
    with col_v1:
        sel_ticket = selected_jira["Key"] if selected_jira is not None else ""
        st.metric("JIRA Ticket", sel_ticket or "—")
    with col_v2:
        sel_sid = selected_dma["Sendout ID"] if selected_dma is not None else ""
        st.metric("Sendout ID", sel_sid or "—")
    with col_v3:
        if st.button("🚀 Validate Pair", type="primary", width="stretch",
                     disabled=not (sel_ticket and sel_sid)):
            # Detect client from selected JIRA row
            ps_detected_client = selected_jira.get("Client", "") if selected_jira is not None else ""
            if ps_detected_client not in CLIENT_CONFIGS:
                ps_detected_client = list(CLIENT_CONFIGS.keys())[0]
            # Store everything needed and trigger validation
            st.session_state["selected_ticket_key"] = sel_ticket
            st.session_state["selected_client_from_queue"] = ps_detected_client
            st.session_state["ps_pending_validation"] = {
                "t_id": sel_ticket,
                "s_id": sel_sid,
                "client": ps_detected_client,
            }
            st.rerun()

    # ── Run validation if triggered from this tab ──
    pending_val = st.session_state.pop("ps_pending_validation", None)
    if pending_val:
        run_validation(
            jira_server, jira_email, jira_token, api_token,
            pending_val["client"],
            pending_val["t_id"],
            pending_val["s_id"],
            "", "", "",  # no G-Sheet overrides
        )


# ---------------------------------------------------------------------------
# Orphan Sendout Scanner
# ---------------------------------------------------------------------------

def render_orphan_scanner(jira_server, jira_email, jira_token, api_token):
    """
    Fetch all pending DMA sendouts across all configured accounts and
    cross-reference against JIRA queue + G-Sheet.
    Surfaces anything configured in DMA with no matching JIRA ticket.
    """
    st.markdown("### ⚠️ Orphan Sendout Scanner")
    st.caption(
        "Finds DMA sendouts that have no matching JIRA ticket in the queue or G-Sheet row. "
        "These may be manually created sendouts, duplicates, or forgotten configurations."
    )

    if not api_token:
        st.warning("DMA API Token required.")
        return

    col_run, col_clear, col_days = st.columns([2, 1, 1])
    with col_days:
        days_ahead = st.number_input("Days ahead", min_value=1, max_value=30, value=7, step=1)
    with col_run:
        run_scan = st.button("Scan all accounts", type="primary", width="stretch")
    with col_clear:
        if st.button("Clear", width="stretch"):
            st.session_state.pop("orphan_scan_results", None)
            st.rerun()

    if run_scan:
        _run_orphan_scan(jira_server, jira_email, jira_token, api_token, int(days_ahead))

    results = st.session_state.get("orphan_scan_results")
    if results is None:
        st.info("Click **Scan all accounts** to start.")
        return

    _render_orphan_results(results, jira_server, jira_email, jira_token, api_token)


def _run_orphan_scan(jira_server, jira_email, jira_token, api_token, days_ahead):
    """Fetch sendouts, JIRA queue, G-Sheet and compute orphan status."""
    from datetime import datetime as _dt, timedelta as _td
    from api_client import fetch_pending_sendouts

    queue   = st.session_state.get("queue_data") or []
    gsheet  = st.session_state.get("gsheet_data") or []

    # Build lookup sets for fast cross-referencing
    # JIRA: set of (client, date) pairs
    jira_by_client_date: dict[str, set] = {}
    for issue in queue:
        client = _ticket_client(issue)
        date_raw = str(issue["fields"].get("customfield_12665", ""))[:10]
        if client and date_raw:
            jira_by_client_date.setdefault(client, set()).add(date_raw)

    # G-Sheet: set of (client, date) pairs
    gsheet_by_client_date: dict[str, set] = {}
    for row in gsheet:
        rc = str(row.get(GSHEET_COLS["client"], "")).strip()
        rd = str(row.get(GSHEET_COLS["date"], "")).strip()
        # Normalise DD/MM/YYYY -> YYYY-MM-DD
        if len(rd) == 10 and rd[2] == "/" and rd[5] == "/":
            rd = f"{rd[6:10]}-{rd[3:5]}-{rd[0:2]}"
        else:
            rd = rd[:10]
        if rc and rd:
            gsheet_by_client_date.setdefault(rc, set()).add(rd)

    # Fetch sendouts for all accounts
    all_sendouts: list[dict] = []
    seen_accounts: set = set()
    progress = st.progress(0, text="Fetching sendouts...")

    clients = list(CLIENT_CONFIGS.keys())
    for i, client in enumerate(clients):
        acc_id = CLIENT_CONFIGS[client].get("account_id")
        if not acc_id or acc_id in seen_accounts:
            progress.progress((i + 1) / len(clients), text=f"Scanning {client}...")
            continue
        seen_accounts.add(acc_id)
        tasks = fetch_pending_sendouts(api_token, acc_id)
        for task in tasks:
            if not task.get("is_active", True):
                continue
            task["_client"] = client
            task["_account_id"] = acc_id
            all_sendouts.append(task)
        progress.progress((i + 1) / len(clients), text=f"Scanned {client} ({len(tasks)} tasks)")

    progress.empty()

    # Classify each sendout
    results = []
    now_date = _dt.utcnow().date()
    cutoff   = now_date + _td(days=days_ahead)

    for task in all_sendouts:
        date_raw = str(task.get("scheduled_date", ""))[:10]
        try:
            task_date = _dt.fromisoformat(date_raw).date()
        except Exception:
            continue
        if task_date < now_date or task_date > cutoff:
            continue

        client     = task["_client"]
        task_name  = task.get("name") or task.get("campaign_name") or ""
        task_id    = task.get("id") or task.get("task_id") or ""

        # Check JIRA: any ticket for this client on this date?
        in_jira = date_raw in jira_by_client_date.get(client, set())

        # Check G-Sheet: any row for this client on this date?
        # Also check canonical client name variations
        in_gsheet = date_raw in gsheet_by_client_date.get(client, set())
        if not in_gsheet:
            for alias in CLIENT_ALIASES.get(client, []):
                if date_raw in gsheet_by_client_date.get(alias, set()):
                    in_gsheet = True
                    break

        requires_jira = CLIENT_CONFIGS.get(client, {}).get("requires_jira", True)
        if not requires_jira:
            status = "auto"
        else:
            status = "ok" if (in_jira and in_gsheet) else \
                     "no_jira" if not in_jira else \
                     "no_gsheet" if not in_gsheet else "ok"

        results.append({
            "client":     client,
            "date":       date_raw,
            "name":       task_name,
            "id":         task_id,
            "in_jira":    in_jira,
            "in_gsheet":  in_gsheet,
            "status":     status,
            "task":       task,
        })

    results.sort(key=lambda r: (r["date"], r["client"]))
    st.session_state["orphan_scan_results"] = results
    st.rerun()


def _render_orphan_results(results: list, jira_server, jira_email, jira_token, api_token):
    """Render the orphan scan results table."""
    if not results:
        st.success("✅ No sendouts found in the scan window.")
        return

    orphans    = [r for r in results if r["status"] in ("no_jira", "no_gsheet")]
    auto_count = len([r for r in results if r["status"] == "auto"])
    ok_count  = len(results) - len(orphans)

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total sendouts",  len(results))
    col_m2.metric("✅ Matched",       ok_count)
    col_m3.metric("⚠️ Untracked",     len(orphans))
    if auto_count:
        st.info(f"🔵 {auto_count} automated sendout(s) excluded from orphan check (no JIRA required).")

    show_ok = st.checkbox("Show matched sendouts too", value=False)
    filtered = results if show_ok else orphans

    if not filtered:
        st.success("✅ All sendouts are tracked in JIRA and G-Sheet.")
        return

    st.markdown("---")

    # Group by status
    for status, label, icon in [
        ("no_jira",    "Missing from JIRA queue",      "🔴"),
        ("no_gsheet",  "Missing from G-Sheet",          "🟡"),
        ("auto",       "Automated (no JIRA required)",  "🔵"),
        ("ok",         "Matched (JIRA + G-Sheet)",      "🟢"),
    ]:
        group = [r for r in filtered if r["status"] == status]
        if not group:
            continue

        st.markdown(f"#### {icon} {label} ({len(group)})")

        for r in group:
            jira_badge   = "✅ JIRA" if r["in_jira"]   else "❌ JIRA"
            gsheet_badge = "✅ G-Sheet" if r["in_gsheet"] else "❌ G-Sheet"

            # Pre-compute config check for expander title badge
            from utils import check_tags, extract_all_tags
            task_data = r["task"]
            # sage/get_tasks nests config under data.body; fetch_api_data returns it directly
            _body_candidate = task_data.get("data", {}).get("body")
            api_body = _body_candidate if isinstance(_body_candidate, dict) and \
                       ("filters" in _body_candidate or "leaflet_filter" in _body_candidate or
                        "component_parameters" in _body_candidate) else task_data
            mock_jira = {"date": r["date"], "gsheet_tags": "", "gsheet_exclude_tags": "",
                         "request_type": str(task_data.get("name", ""))}
            tag_result = check_tags(mock_jira, api_body, r["client"])
            if tag_result["expected_filters"]:
                config_badge = " ✅" if not tag_result["missing_filters"] else " ❌"
            else:
                config_badge = ""

            with st.expander(
                f"{r['date']} · **{r['client']}**{config_badge} · {r['name'][:60]}",
                expanded=(status == "no_jira")
            ):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                c1.markdown(f"**Name:** {r['name']}")
                c2.markdown(f"**ID:** `{r['id'][:36]}`")
                c3.markdown(jira_badge)
                c4.markdown(gsheet_badge)

                # Show filters: regular filters[] AND leaflet_filter on the same row
                reg_parts = []
                for f in api_body.get("filters", []):
                    if not isinstance(f, dict):
                        continue
                    # Direct locale key e.g. {"locale": "de", "tags": []}
                    loc = f.get("locale", "")
                    if loc:
                        reg_parts.append(f"locale={loc}")
                    # shop_number direct
                    sn = f.get("shop_number", "")
                    if sn:
                        reg_parts.append(f"shop_number={sn}")
                    # wids — WhatsApp ID list filter (test sendouts)
                    wids = f.get("wids", "")
                    if wids:
                        wid_count = len(str(wids).split(","))
                        reg_parts.append(f"wids ({wid_count} contacts)")
                    # Tags array inside filter
                    for t in f.get("tags", []):
                        if not isinstance(t, dict):
                            continue
                        n = t.get("name",""); v = t.get("value","")
                        excl = t.get("mode","") == "exclude" or "exclude_value" in t
                        prefix = "Excl" if excl else "Incl"
                        if n and v:
                            reg_parts.append(f"{prefix}: {n}={v}")

                lf = api_body.get("leaflet_filter", {})
                lf_parts = []
                if isinstance(lf, dict):
                    lf_od = lf.get("offset_days")
                    if lf_od is not None:
                        lf_parts.append(f"offset_days={lf_od}")
                    for lt in lf.get("tags", []):
                        n = lt.get("name",""); v = lt.get("value","")
                        if n and v:
                            lf_parts.append(f"{n}={v}")

                row_parts = []
                if reg_parts:
                    row_parts.append("**Audience filter:** " + " · ".join(f"`{p}`" for p in reg_parts))
                if lf_parts:
                    row_parts.append("**Leaflet filter:** " + " · ".join(f"`{p}`" for p in lf_parts))
                if row_parts:
                    st.markdown("  |  ".join(row_parts))

                # Action: validate this sendout against config
                if status in ("no_jira", "auto"):
                    if status == "no_jira":
                        st.warning(
                            "⚠️ This sendout has no matching JIRA ticket. "
                            "It may have been created directly in DMA without going through the approval process."
                        )
                    else:
                        st.info("ℹ️ Automated sendout — no JIRA ticket required.")

                    if tag_result["expected_filters"]:
                        missing = tag_result["missing_filters"]
                        if missing:
                            st.error(f"❌ Config filter mismatch — Missing: {missing}")
                        else:
                            st.success("✅ Config filters match")

                elif status == "no_gsheet":
                    st.warning("⚠️ This sendout has no matching G-Sheet row for this date.")

    st.divider()
    # Export
    import pandas as _pd
    export_rows = []
    for r in results:
        export_rows.append({
            "Date":      r["date"],
            "Client":    r["client"],
            "Name":      r["name"],
            "Sendout ID": r["id"],
            "In JIRA":   r["in_jira"],
            "In G-Sheet": r["in_gsheet"],
            "Status":    r["status"],
        })
    st.download_button(
        "Export CSV",
        data=_pd.DataFrame(export_rows).to_csv(index=False),
        file_name="orphan_scan.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------

def run_validation(jira_server, jira_email, jira_token, api_token, client, t_id, s_id,
                   auto_leaflet_url, auto_gsheet_tags, auto_exclude_tags):
    with st.spinner("Performing Setup Checks..."):
        st.session_state.pop("ai_urls", None)
        st.session_state.pop("ai_result", None)

        j_data = fetch_ticket_data(jira_server, jira_email, jira_token, t_id)
        a_data = fetch_api_data(api_token, s_id)

        if not j_data:
            st.error("JIRA Fetch Failed")
            st.stop()

        # Change detection — warn if ticket content changed since last validation
        _changed, _diff = _check_ticket_changed(t_id, j_data)
        if _changed:
            st.warning(f"Ticket {t_id} has changed since last validation — re-run the audit.")
            with st.expander("View changes", expanded=False):
                for field, before, after in _diff:
                    st.markdown(f"**{field}**")
                    col_b, col_a = st.columns(2)
                    col_b.caption("Before")
                    col_b.code((before or "(empty)")[:200], language=None)
                    col_a.caption("After")
                    col_a.code((after or "(empty)")[:200], language=None)
        if not a_data or "error_code" in a_data:
            err = a_data or {}
            code = err.get("error_code", "Unknown")
            msg  = err.get("error_msg", "")
            st.error(f"API Fetch Failed ({code}): {msg}")
            if code == 404:
                st.warning("The Sendout ID was not found. Please enter the correct ID below and try again.")
                new_sid = st.text_input("Sendout ID (DMA)", value=s_id, key="retry_sendout_id")
                if st.button("Retry with new Sendout ID", type="primary"):
                    st.session_state["retry_sendout_id_value"] = new_sid
                    st.rerun()
            st.stop()

        t_name  = a_data.get("template_name") or (a_data.get("template") or {}).get("name")
        waba_key = fetch_api_key_via_dma(api_token, a_data.get("account_id"))
        t_data  = fetch_template_data(waba_key, t_name) if (t_name and waba_key) else None

        if auto_leaflet_url:
            j_data["leaflet_url"] = auto_leaflet_url
        if auto_gsheet_tags:
            j_data["gsheet_tags"] = auto_gsheet_tags
        if auto_exclude_tags:
            j_data["gsheet_exclude_tags"] = auto_exclude_tags

        leaflet_data = []
        components_str = str(a_data.get("component_parameters", []))
        has_leaflet = (
            "leaflet" in components_str
            or isinstance(a_data.get("leaflet_filter"), dict)
            or "leaflet" in str(a_data.get("google_rcs_content", ""))
        )
        if has_leaflet:
            leaflet_data = fetch_account_leaflets(api_token, a_data.get("account_id"), a_data.get("scheduled_date", ""))

        # Parse carousel FIRST (needs full description with Slide N: labels)
        j_data["parsed_carousel"] = pick_carousel_parser(str(j_data.get("description", "")), client)

        # Then strip slide labels so text comparison only sees the intro
        if j_data.get("description"):
            j_data["description"] = _strip_slide_labels(j_data["description"])

        # Record in dashboard log
        st.session_state["validation_log"] = record_validation(
            ticket_key=t_id, client=client,
            status="pending", mode="single", issues=0,
            approved=bool(j_data.get("approval_status")),
            log=st.session_state.get("validation_log", []),
        )

        st.session_state.update({
            "valid_jira":     j_data,
            "valid_api":      a_data,
            "valid_temp":     t_data,
            "leaflet_data":   leaflet_data,
            "validation_run": True,
            "_current_client": client,
            "_current_t_id":   t_id,
        })
        st.rerun()


# ---------------------------------------------------------------------------
# Results — single HTML component (fixes carousel scroll bug)
# ---------------------------------------------------------------------------

def render_results(gemini_key, gemini_model, jira_server, jira_email, jira_token):
    jira         = st.session_state["valid_jira"]
    api          = st.session_state["valid_api"]
    tmpl         = st.session_state["valid_temp"]
    client       = st.session_state.get("_current_client", "")
    t_id         = st.session_state.get("_current_t_id", "")
    leaflet_data = st.session_state.get("leaflet_data", [])
    ai_result    = st.session_state.get("ai_result", "")
    ai_urls      = st.session_state.get("ai_urls")
    dma_img_urls = st.session_state.get("dma_image_urls_for_ai", [])

    # AI audit trigger
    col_ai, col_sp = st.columns([1, 3])
    with col_ai:
        if st.button("Run AI Audit", type="primary", width='stretch'):
            st.session_state["ai_trigger"] = True
            st.rerun()
    with col_sp:
        if ai_result and not _is_audit_error(ai_result):
            _status = "Passed" if "❌" not in ai_result else "Failed"
            _color = "green" if _status == "Passed" else "red"
            st.markdown(f"Last result: :{_color}[**{_status}**]")
    if st.session_state.get("ai_trigger"):
        if not gemini_key:
            st.error("Gemini API Key missing in sidebar.")
            st.session_state["ai_trigger"] = False
        else:
            _execute_ai_audit(gemini_key, gemini_model, jira, api, tmpl, leaflet_data, client, t_id, jira_server, jira_email, jira_token)

    # Attachment debug — shown only when carousel images are empty
    if not jira.get("carousel_images"):
        raw_atts = jira.get("_raw_fields", {}).get("attachment", [])
        if raw_atts:
            with st.expander(f"⚠️ {len(raw_atts)} attachment(s) found in JIRA but none downloaded — click to inspect", expanded=True):
                for a in raw_atts:
                    fname   = a.get("filename", "?")
                    mime    = a.get("mimeType", "?")
                    size    = a.get("size", 0)
                    dl_url  = a.get("content", "?")
                    st.write(f"**{fname}** — `{mime}` — {size:,} bytes")
                    st.caption(dl_url)

    dark_mode = st.session_state.get("dark_mode", True)

    # ── Quick Summary Panel ───────────────────────────────────────────────────
    from utils import check_tags
    _tag_result  = check_tags(jira, api, client)
    _date_result = validate_scheduled_date(jira, api)
    jira["_client_timezone"] = "Europe/Lisbon" if client == "ALDI Portugal" else "Europe/Berlin"

    _ai_ok = bool(ai_result) and not _is_audit_error(ai_result) and "❌" not in ai_result
    _ai_detail = "Not run yet" if not ai_result else ("Passed" if _ai_ok else "Failed — see AI tab")

    _checks_summary = [
        ("Scheduling",     _date_result["ok"],             _date_result.get("detail", "")),
        ("Include tags",   not bool(_tag_result["missing_incl"]),
                           f"{len(_tag_result['missing_incl'])} missing" if _tag_result["missing_incl"] else "OK"),
        ("Exclude tags",   not bool(_tag_result["missing_excl"]),
                           f"{len(_tag_result['missing_excl'])} missing" if _tag_result["missing_excl"] else "OK"),
        ("Client filters", not bool(_tag_result["missing_filters"]),
                           f"{len(_tag_result['missing_filters'])} missing" if _tag_result["missing_filters"] else "OK"),
    ]
    # Only add AI Audit to summary if it has actually been run
    if ai_result and not _is_audit_error(ai_result):
        _checks_summary.append(("AI Audit", _ai_ok, _ai_detail))
    _n_fail = sum(1 for _, ok, _ in _checks_summary if not ok)
    _overall_ok = _n_fail == 0
    _header_color = "#22c55e" if _overall_ok else "#ef4444"
    _header_text  = "Ready to approve" if _overall_ok else f"Issues found — {_n_fail} check(s) failed"

    st_components.html(f"""
    <style>
      body {{ margin:0; padding:0; background:transparent; }}
      .qs-wrap {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:transparent; }}
      .qs-header {{ font-size:15px; font-weight:700; color:{_header_color}; margin-bottom:10px; }}
      .qs-cards {{ display:flex; gap:10px; }}
      .qs-card {{ flex:1; background:transparent; border:1px solid #dee2e6; border-radius:10px;
                  padding:12px 16px; display:flex; flex-direction:column; gap:4px; min-width:0; }}
      .qs-label {{ font-size:10px; color:#6c757d; font-weight:600; text-transform:uppercase;
                   letter-spacing:.06em; white-space:nowrap; }}
      .qs-icon  {{ font-size:20px; font-weight:700; line-height:1.2; }}
      .qs-detail {{ font-size:10px; color:#6c757d; white-space:nowrap; overflow:hidden;
                    text-overflow:ellipsis; }}
      .qs-hint  {{ font-size:11px; color:#6c757d; margin-top:6px; }}
    </style>
    <div class="qs-wrap">
      <div class="qs-header">{_header_text}</div>
      <div class="qs-cards">
        {"".join(f'''
        <div class="qs-card">
          <div class="qs-label">{label}</div>
          <div class="qs-icon" style="color:{"#22c55e" if ok else "#ef4444"}">{"✓" if ok else "✗"}</div>
          <div class="qs-detail" title="{detail}">{detail[:35]}</div>
        </div>''' for label, ok, detail in _checks_summary)}
      </div>
      {"<div class='qs-hint'>Scroll down for detailed analysis →</div>" if not _overall_ok else ""}
    </div>
    """, height=120)

    # ── Ticket history (last 3 validations from audit log) ────────────────────
    try:
        if os.path.exists(_AUDIT_LOG_FILE):
            with open(_AUDIT_LOG_FILE, encoding="utf-8") as _hf:
                _hist_lines = [l.strip() for l in _hf.readlines()
                               if t_id in l and ("APPROVE" in l or "AI_AUDIT" in l)]
            if _hist_lines:
                with st.expander(f"History — last {min(3, len(_hist_lines))} action(s) on {t_id}",
                                 expanded=False):
                    for line in _hist_lines[-3:][::-1]:
                        parts = line.split("\t")
                        if len(parts) >= 4:
                            ts, user, action, detail = parts[0], parts[1], parts[2], parts[3]
                            st.caption(f"`{ts}` · **{user}** · {action} — {detail}")
    except Exception:
        pass

    # ── Inline approval when all checks pass ──────────────────────────────────
    if _overall_ok and t_id:
        _existing_approvals = jira.get("approval_status", []) or []
        if not isinstance(_existing_approvals, list):
            _existing_approvals = [_existing_approvals]
        _user_full_name = st.session_state.get("authenticated_name", "")
        _already_approved = any(
            _user_full_name.split()[0].lower() in str(a).lower() for a in _existing_approvals
        )

        if _already_approved:
            st.success(f"You already approved this ticket. Existing approvals: {', '.join(map(str, _existing_approvals))}")
        else:
            colq1, colq2, colq3, colq4 = st.columns([1, 1, 1, 2])
            _users = {
                "Gleb":    ("Gleb Approved",    colq1),
                "Alex":    ("Alex Approved",    colq2),
                "Martina": ("Martina Approved", colq3),
            }
            for short_name, (approver_value, col) in _users.items():
                with col:
                    if st.button(f"Approve ({short_name})", key=f"qs_approve_{short_name}",
                                 type="primary", width='stretch'):
                        ok, msg = approve_ticket_jira(jira_server, jira_email, jira_token,
                                                      t_id, approver_value)
                        if ok:
                            _audit("APPROVE", f"{t_id} as {approver_value}")
                            st.success(f"Approved as {approver_value}")
                            _send_slack_thread_reply(t_id, approver_value)
                            # Update local state
                            approval = st.session_state["valid_jira"].setdefault("approval_status", [])
                            if not isinstance(approval, list):
                                st.session_state["valid_jira"]["approval_status"] = [approver_value]
                            elif approver_value not in approval:
                                approval.append(approver_value)
                            st.rerun()
                        else:
                            st.error(f"Approval failed: {msg}")
            with colq4:
                st.caption(f"Existing approvals: {', '.join(map(str, _existing_approvals)) if _existing_approvals else 'none'}")

    html_str = build_results_html(
        jira=jira, api=api, tmpl=tmpl, leaflet_data=leaflet_data,
        client=client, ai_result=ai_result, ai_urls=ai_urls,
        dma_image_urls=dma_img_urls, dark=dark_mode,
    )
    n_slides = len((jira.get("parsed_carousel") or {}).get("cards", []))
    ai_len   = len(ai_result) if ai_result else 0
    _height  = 320 + max(ai_len // 3, 400) + n_slides * 420
    st_components.html(html_str, height=min(_height, 3000), scrolling=True)

    # Confidence score display
    _conf = st.session_state.get("ai_confidence", -1)
    _conf_reason = st.session_state.get("ai_confidence_reason", "")
    if _conf >= 0:
        _conf_color = "Good" if _conf >= 80 else ("Medium" if _conf >= 60 else "Low")
        st.caption(f"AI Confidence: **{_conf}%** ({_conf_color}) — {_conf_reason}")
        if _conf < 60 and "✅" in ai_result:
            st.warning(f"Low confidence ({_conf}%) — manual review recommended even though audit passed")

    # ── Scheduled date validation ──
    st.markdown("---")
    st.subheader("Scheduled Date Check")
    if _date_result["ok"]:
        st.success(f"✅ {_date_result['detail']}")
    else:
        st.error(f"Date mismatch — {_date_result['detail']}")
        col_d1, col_d2 = st.columns(2)
        col_d1.metric("JIRA date", _date_result["jira_raw"][:19] if _date_result["jira_raw"] else "—")
        col_d2.metric("API date",  _date_result["api_raw"][:19]  if _date_result["api_raw"]  else "—")

    # ── URL reachability ──
    st.markdown("---")
    st.subheader("🔗 URL Reachability")
    if st.button("Check all URLs", key="btn_url_reach"):
        all_urls = list({
            u for u in (
                extract_urls(str(jira.get("description", ""))) +
                extract_urls(str(jira.get("additional_comments", ""))) +
                ([jira.get("cta_link")] if jira.get("cta_link") else []) +
                extract_api_urls_advanced(api)
            )
            if not is_media_url(u) and u.startswith("http")
        })
        if not all_urls:
            st.info("No HTTP URLs to check.")
        else:
            with st.spinner(f"Checking {len(all_urls)} URL(s)..."):
                reach_results = check_url_reachability(all_urls)
            for r in reach_results:
                if r["ok"]:
                    st.success(f"✅ {r['status_code']} — {r['url']}")
                else:
                    detail = r["error"] or f"HTTP {r['status_code']}"
                    st.error(f"❌ {detail} — {r['url']}")

    # ── G-Sheet write-back ──
    st.markdown("---")
    st.subheader("📝 G-Sheet Write-Back")
    st.caption("Requires a Google Service Account JSON in the sidebar (not yet configured — see README).")
    _ai_res = st.session_state.get("ai_result", "")
    gsheet_status = "Passed" if not _ai_res or \
                    (not _is_audit_error(_ai_res) and "❌" not in _ai_res) \
                    else "Failed"
    st.info(f"Current validation status: **{gsheet_status}**")
    if st.button("Write status to G-Sheet", key="btn_gsheet_wb"):
        st.warning("G-Sheet write-back requires a service account key. See the README for setup instructions.")

    # ── Sign-off ──
    st.markdown("---")
    st.subheader("Sign Off")
    col1, col2, col3, _ = st.columns([1, 1, 1, 1])
    for col, approver in ((col1, "Gleb Approved"), (col2, "Alex Approved"), (col3, "Martina Approved")):
        name = approver.split()[0]
        with col:
            if st.button(f"Approve ({name})", type="primary", width='stretch'):
                ok, msg = approve_ticket_jira(jira_server, jira_email, jira_token, t_id, approver)
                if ok:
                    _audit("APPROVE", f"{t_id} as {approver}")
                    st.success("Approved!")
                    approval = st.session_state["valid_jira"].setdefault("approval_status", [])
                    if not isinstance(approval, list):
                        st.session_state["valid_jira"]["approval_status"] = [approver]
                    elif approver not in approval:
                        approval.append(approver)
                    # Record approval in log
                    for entry in st.session_state.get("validation_log", []):
                        if entry["ticket_key"] == t_id:
                            entry["approved"] = True
                    st.rerun()
                else:
                    st.error(msg)


# ---------------------------------------------------------------------------
# Individual tab renderers
# ---------------------------------------------------------------------------

_TAG_EMPTY = {"none", "-", "—", "n/a", ""}

def _norm_tags(s: str) -> str:
    """Normalise tag string: split on comma/newline/semicolon, strip spaces around =,
    ignore placeholder values (none, -, —, n/a)."""
    import re as _re
    parts = _re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p and p.lower() not in _TAG_EMPTY:
            cleaned.append(p)
    return ", ".join(cleaned)

def _norm_tags_list(s: str) -> list:
    """Same as _norm_tags but returns a list."""
    import re as _re
    parts = _re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p and p.lower() not in _TAG_EMPTY:
            cleaned.append(p)
    return cleaned



def _strip_slide_labels(text: str) -> str:
    """Remove everything from the first Slide N: marker onwards."""
    import re as _re
    m = _re.search(r'(?im)^[\s*]*(?:Slide|Slider)\s*\d+\s*:', text)
    if m:
        return text[:m.start()].strip()
    return text.strip()


def _collect_custom_carousel_images(api_data) -> list:
    """Return per-card custom image URLs from the raw DMA API response."""
    images = []
    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "carousel" and "cards" in obj:
                for card in obj["cards"]:
                    found = None
                    for cp in card.get("component_parameters", []):
                        if cp.get("type") == "header_image" and cp.get("value"):
                            found = cp["value"]
                    images.append(found)
                return
            for k, v in obj.items():
                if not (obj.get("type") == "carousel" and k == "cards"):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(api_data)
    return images


def _execute_ai_audit(gemini_key, gemini_model, jira, api, tmpl, leaflet_data, client, t_id, jira_server, jira_email, jira_token):
    with st.spinner("🤖 Gemini is analyzing JIRA, G-Sheet, and DMA API Data..."):
        tmpl_body, tmpl_footer, tmpl_buttons = "", "", []
        dma_carousel_texts: list[str] = []
        dma_image_urls: list[str] = []

        # ── Step 1: check component_parameters for a custom header image first.
        # This is the actual image set in the DMA sendout, not the WABA template default.
        for cp in api.get("component_parameters", []):
            if cp.get("type") == "header_image":
                url = cp.get("value")
                if url and str(url).startswith("http"):
                    dma_image_urls.append(url)
                elif cp.get("source") == "leaflet_image_url":
                    dma_image_urls.append("@leaflet_image_url")
                break  # only one header image per sendout

        # ── Step 2: carousel custom images from component_parameters cards
        api_custom_images = _collect_custom_carousel_images(api)
        if api_custom_images:
            # For carousels the per-card images replace the list
            dma_image_urls = [img for img in api_custom_images if img]

        # ── Step 2b: RCS carousel images from google_rcs_content
        rcs_cards = (api.get("google_rcs_content", {})
                        .get("richCard", {})
                        .get("carouselCard", {})
                        .get("cardContents", []))
        if rcs_cards and not dma_image_urls:
            # Build leaflet_type -> document_url from leaflet_data
            leaflet_by_type = {}
            for lf_item in (leaflet_data or []):
                lft = (lf_item.get("data") or {}).get("leaflet_type", "")
                if lft and lft not in leaflet_by_type:
                    leaflet_by_type[lft] = lf_item.get("document_url") or lf_item.get("image_url", "")
            for rcs_card in rcs_cards:
                img_url = (rcs_card.get("media", {})
                               .get("contentInfo", {})
                               .get("fileUrl", ""))
                if img_url and img_url.startswith("http"):
                    dma_image_urls.append(img_url)
                else:
                    # Dynamic leaflet image — resolve by card's leaflet_type
                    card_lf = rcs_card.get("leaflet_filter", {})
                    lft = next((t.get("value","") for t in card_lf.get("tags",[])
                               if t.get("name") == "leaflet_type"), "")
                    img_url = leaflet_by_type.get(lft) or leaflet_by_type.get(list(leaflet_by_type.keys())[0], "") if leaflet_by_type else ""
                    if img_url:
                        dma_image_urls.append(img_url)

            # Also build RCS carousel texts for AI comparison
            for ci, rcs_card in enumerate(rcs_cards):
                title = rcs_card.get("title", f"Card {ci+1}")
                desc  = rcs_card.get("description", "")
                btn   = next((s.get("action", {}).get("text", "")
                              for s in rcs_card.get("suggestions", [])), "")
                dma_carousel_texts.append(f"Card {ci+1} Title: '{title}' | Body: '{desc}' | Button: {btn}")

        if tmpl:
            for comp in tmpl.get("components", []):
                ctype = comp["type"]
                if ctype == "BODY":
                    tmpl_body = comp.get("text", "")
                elif ctype == "FOOTER":
                    tmpl_footer = comp.get("text", "")
                elif ctype == "BUTTONS":
                    tmpl_buttons = [
                        f"{b.get('text', '')} ({b.get('type', '')})"
                        for b in comp.get("buttons", [])
                    ]
                elif ctype == "HEADER" and comp.get("format") == "IMAGE" and not dma_image_urls:
                    # Only fall back to WABA template header_handle if we found nothing above
                    url = comp.get("example", {}).get("header_handle", [None])[0]
                    if url:
                        dma_image_urls.append(url)
                elif ctype == "CAROUSEL":
                    for ci, card in enumerate(comp.get("cards", [])):
                        body, btns = "", []
                        for cc in card.get("components", []):
                            if cc["type"] == "HEADER" and cc.get("format") == "IMAGE" and not api_custom_images:
                                url = cc.get("example", {}).get("header_handle", [None])[0]
                                if url:
                                    dma_image_urls.append(url)
                            elif cc["type"] == "BODY":
                                body = cc.get("text", "")
                            elif cc["type"] == "BUTTONS":
                                btns = [b.get("text", "") for b in cc.get("buttons", [])]
                        dma_carousel_texts.append(f"Card {ci+1} Body: '{body}' | Buttons: {btns}")

        # Resolve leaflet references
        if leaflet_data and isinstance(leaflet_data, list) and leaflet_data:
            first_leaflet = leaflet_data[0]
            l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
            l_img = first_leaflet.get("document_url") or first_leaflet.get("image_url")
            if l_url:
                dma_image_urls = [l_img if u == "@leaflet_image_url" else u for u in dma_image_urls]

        # Build tag summary string (normalised, no spaces around =)
        api_tags = extract_all_tags(api)
        tag_parts: list[str] = []
        for t in api_tags:
            key_name = t.get("name") or t.get("type") or "filter"
            raw_val = (t.get("value") or t.get("exclude_value") or t.get("values")
                       or t.get("exclude_values") or t.get("offset_days") or "Active")
            # Flatten list values (e.g. shop_number lists) to a short summary
            if isinstance(raw_val, list):
                val = f"[{len(raw_val)} values]"
            else:
                val = str(raw_val)
            mode = "Exclude" if ("exclude_value" in t or "exclude_values" in t or t.get("mode") == "exclude") else "Include"
            # Represent leaflet_tag offset_days in both forms for Gemini
            if t.get("type") == "leaflet_tag" and t.get("offset_days") is not None:
                tag_parts.append(f"[{mode}] leaflet_tag={t.get('offset_days')} (offset_days={t.get('offset_days')})")
            else:
                tag_parts.append(f"[{mode}] {_norm_tags(f'{key_name}={val}')}")

        api_urls = extract_api_urls_advanced(api)
        if tmpl:
            api_urls += extract_urls(str(tmpl))
        if leaflet_data and isinstance(leaflet_data, list) and leaflet_data:
            l_url = leaflet_data[0].get("public_url") or leaflet_data[0].get("url", "")
            if l_url:
                api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]

        # Resolve relative URLs to absolute using the domain from JIRA URLs
        # e.g. "angebote/{shop_id}/..." -> "https://rewe.de/angebote/{shop_id}/..."
        _jira_all_text = " ".join(filter(None, [
            str(jira.get("description", "")), str(jira.get("additional_comments", "")),
            str(jira.get("cta_link", "")),
        ]))
        _jira_urls = extract_urls(_jira_all_text)
        _base_domain = None
        for _u in _jira_urls:
            try:
                from urllib.parse import urlparse as _up
                _p = _up(_u)
                if _p.scheme and _p.netloc:
                    _base_domain = f"{_p.scheme}://{_p.netloc}"
                    break
            except Exception:
                pass
        if _base_domain:
            api_urls = [
                f"{_base_domain}/{u.lstrip('/')}" if not u.startswith("http") and not u.startswith("@") and u
                else u
                for u in api_urls
            ]

        jira_for_comparison = dict(jira)
        if jira_for_comparison.get("description"):
            jira_for_comparison["description"] = _strip_slide_labels(jira_for_comparison["description"])

        # Kaufland RCS Sunday: inject expected static card texts into comparison
        if client == "Kaufland RCS" and rcs_cards:
            from datetime import datetime as _dt_rcs
            try:
                _is_sun = _dt_rcs.fromisoformat(api.get("scheduled_date","").replace("Z","+00:00")).weekday() == 6
            except Exception:
                _is_sun = False
            if _is_sun:
                from config import CLIENT_CONFIGS as _CC
                static = _CC.get("Kaufland RCS", {}).get("sunday_rcs_cards", [])
                if static:
                    expected_texts = " | ".join(
                        f"Card {i+1}: Title='{c['title']}' Body='{c['body'][:80]}...' Button='{c['button']}'"
                        for i, c in enumerate(static)
                    )
                    jira_for_comparison["description"] = f"[STATIC RCS TEMPLATE] Expected card texts:\n{expected_texts}"

        # Kaufland WABA Sunday: inject expected static carousel card body text
        if client == "Kaufland WABA" and not jira_for_comparison.get("description"):
            _WABA_STATIC_BODY = (
                "Hier findest du unseren aktuellen Prospekt mit den Angeboten vom {{1}} \u2013 {{2}} "
                "f\u00fcr deine Filiale in {{3}} {{4}} \u2b07\ufe0f"
            )
            jira_for_comparison["description"] = (
                f"[STATIC WABA CAROUSEL TEMPLATE] Both carousel cards use this body text:\n"
                f"{_WABA_STATIC_BODY}\n"
                f"Card 1: leaflet_type=special, offset_days=1 | Card 2: leaflet_type=regular, offset_days=4"
            )

        comparison_data = build_comparison_data(
            jira=jira_for_comparison,
            tmpl_body=tmpl_body,
            tmpl_footer=tmpl_footer,
            tmpl_buttons=tmpl_buttons,
            dma_carousel_texts=dma_carousel_texts,
            api_tag_str=", ".join(tag_parts),
            api_urls=[u for u in api_urls if "{{" not in u],
            client_name=client,
            api_date=str(api.get("scheduled_date", "")),
        )

        dma_image_bytes = [fetch_dma_image_bytes(u) for u in dma_image_urls if u]
        st.session_state["dma_image_urls_for_ai"] = dma_image_urls

        result = run_ai_audit(
            gemini_key, gemini_model, comparison_data, client,
            jira_images=jira.get("carousel_images"),
            dma_images=dma_image_bytes,
        )

        st.session_state["ai_result"]     = result.get("audit_report", "Error extracting report")
        st.session_state["ai_confidence"] = int(result.get("confidence", -1))
        st.session_state["ai_confidence_reason"] = str(result.get("confidence_reason", ""))
        st.session_state["ai_urls"]   = {
            "jira": result.get("jira_extracted_urls", []),
            "api":  result.get("api_extracted_urls", []),
        }

        # Write result back to JIRA
        ai_result_text = st.session_state["ai_result"]
        if _is_audit_error(ai_result_text):
            st.error("⚠️ AI audit failed — JIRA status not updated.")
        else:
            status = "Rejected" if "❌" in ai_result_text else "Approved"
            _audit("AI_AUDIT", f"{t_id} → {status}")
            if status == "Rejected":
                import re as _re_slack
                # Extract section names that failed e.g. "**Audience / Tags: ❌ FAIL**"
                _raw = _re_slack.findall(
                    r'(?:#{1,3}\s*)?(?:\d+\.\s*)?\*{0,2}([A-Za-z][^*\n❌]{2,50}?)\*{0,2}[\s:]*❌',
                    ai_result_text
                )
                _failed = []
                for _m in _raw:
                    _m = _re_slack.sub(r'^\d+[\.)\s]+', '', _m.strip().rstrip(':').strip())
                    if _m and "overall" not in _m.lower() and "status" not in _m.lower() and len(_m) > 3:
                        _failed.append(_m)
                if not _failed:
                    _failed = [f"{ai_result_text.count('❌')} issue(s) found"]
                _send_slack_alert(t_id, client, "AI Single Check",
                                  ai_result_text.count("❌"), jira_server,
                                  failed_checks=_failed[:8],
                                  sendout_id=st.session_state.get("valid_sendout_id", ""))
        ok = write_ai_status_to_jira(jira_server, jira_email, jira_token, t_id, status)
        st.toast(f"✅ JIRA updated: AI Checked = {status}" if ok else "⚠️ Failed to update JIRA AI status field")

        st.session_state["ai_trigger"] = False
        st.rerun()



def render_bulk_validation(jira_server, jira_email, jira_token, api_token, gemini_key, gemini_model):
    """Run and display bulk validation (regular or AI mode)."""
    tickets   = st.session_state.get("bulk_tickets", [])
    bulk_mode = st.session_state.get("bulk_mode", "regular")
    if not tickets:
        return

    st.divider()
    mode_label = "Regular Check" if bulk_mode == "regular" else "AI Audit"
    st.subheader(f"Bulk {mode_label} — {len(tickets)} ticket(s)")

    if bulk_mode == "ai" and not gemini_key:
        st.error("Gemini API Key is required for AI audit. Add it in the sidebar.")
        return

    gsheet_data = st.session_state.get("gsheet_data") or []
    progress_bar = st.progress(0, text="Starting...")
    status_text  = st.empty()

    def on_progress(result, index, total):
        pct = int(((index + 1) / total) * 100)
        progress_bar.progress(pct, text=f"Processing {index + 1} of {total}: {result.ticket_key}")
        label = {
            "running": f"Checking {result.ticket_key} ({result.client})...",
            "passed":  f"{result.ticket_key} — Passed",
            "failed":  f"{result.ticket_key} — {result.issues_found} issue(s) found",
            "skipped": f"{result.ticket_key} — Skipped (no Sendout ID)",
            "error":   f"{result.ticket_key} — Error: {result.error_msg}",
        }.get(result.status, "")
        if result.status in ("running",):
            status_text.info(label)
        elif result.status == "passed":
            status_text.success(label)
        elif result.status in ("failed", "skipped"):
            status_text.warning(label)
        elif result.status == "error":
            status_text.error(label)

    if bulk_mode == "regular":
        results = run_bulk_regular_check(
            tickets=tickets,
            gsheet_data=gsheet_data,
            jira_server=jira_server,
            jira_email=jira_email,
            jira_token=jira_token,
            api_token=api_token,
            on_progress=on_progress,
        )
    else:
        results = run_bulk_validation(
            tickets=tickets,
            gsheet_data=gsheet_data,
            jira_server=jira_server,
            jira_email=jira_email,
            jira_token=jira_token,
            api_token=api_token,
            gemini_key=gemini_key,
            gemini_model=gemini_model,
            on_progress=on_progress,
        )

    progress_bar.progress(100, text="Done!")
    status_text.empty()

    # Fire Slack alerts for failed AI bulk results
    if bulk_mode == "ai":
        for r in results:
            if r.status == "failed":
                # Get failed check labels from checks list or parse report
                _failed_checks = [c["label"] for c in (r.checks or []) if not c.get("ok")]
                if not _failed_checks and r.report:
                    import re as _re_slack2
                    _raw2 = _re_slack2.findall(
                        r'(?:#{1,3}\s*)?(?:\d+\.\s*)?\*{0,2}([A-Za-z][^*\n❌]{2,50}?)\*{0,2}[\s:]*❌',
                        r.report
                    )
                    for _m2 in _raw2:
                        _m2 = _re_slack2.sub(r'^\d+[\.)\s]+', '', _m2.strip().rstrip(':').strip())
                        if _m2 and "overall" not in _m2.lower() and "status" not in _m2.lower() and len(_m2) > 3:
                            _failed_checks.append(_m2)
                    if not _failed_checks:
                        _failed_checks = [f"{r.issues_found} issue(s) found"]
                _send_slack_alert(r.ticket_key, r.client, "AI Bulk Check",
                                  r.issues_found, jira_server,
                                  failed_checks=_failed_checks[:8],
                                  sendout_id=r.sendout_id)

    # ── Summary table + export ──
    st.markdown("### Summary")
    _render_bulk_summary_table(results)

    col_exp, _ = st.columns([1, 3])
    with col_exp:
        csv_bytes = export_bulk_results_csv(results)
        st.download_button(
            label="📥 Export results CSV",
            data=csv_bytes,
            file_name=f"bulk_validation_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            width='stretch',
        )

    # Record bulk results in dashboard log
    for r in results:
        st.session_state["validation_log"] = record_validation(
            ticket_key=r.ticket_key, client=r.client,
            status=r.status, mode=getattr(r, "mode", "regular"),
            issues=r.issues_found, approved=False,
            log=st.session_state.get("validation_log", []),
        )

    # ── Approve-all passing ──
    passing = [r for r in results if r.status == "passed"]
    if passing:
        st.markdown("---")
        st.markdown(f"**Approve all {len(passing)} passing ticket(s):**")
        ba_col1, ba_col2, ba_col3, _ = st.columns([2, 2, 2, 1])
        if ba_col1.button("Approve (Gleb)",    key="bulk_approve_Gleb",    width="stretch"):
            st.session_state["_bulk_approve_action"] = ("Gleb Approved",    passing)
        if ba_col2.button("Approve (Alex)",    key="bulk_approve_Alex",    width="stretch"):
            st.session_state["_bulk_approve_action"] = ("Alex Approved",    passing)
        if ba_col3.button("Approve (Martina)", key="bulk_approve_Martina", width="stretch"):
            st.session_state["_bulk_approve_action"] = ("Martina Approved", passing)

    # Execute approval outside column context so st.success/error render correctly
    if "_bulk_approve_action" in st.session_state:
        approver, approve_list = st.session_state.pop("_bulk_approve_action")
        approved_count = 0
        failed_keys = []
        with st.spinner(f"Approving {len(approve_list)} ticket(s) as {approver}..."):
            for r in approve_list:
                ok, msg = approve_ticket_jira(jira_server, jira_email, jira_token, r.ticket_key, approver)
                if ok:
                    approved_count += 1
                    _audit("BULK_APPROVE", f"{r.ticket_key} as {approver}")
                else:
                    failed_keys.append(f"{r.ticket_key}: {msg}")
        if approved_count:
            st.success(f"✅ Approved {approved_count} ticket(s) as **{approver}**")
        for fail in failed_keys:
            st.error(f"❌ {fail}")

    # ── Detailed reports ──
    st.markdown("### Detailed Reports")
    for r in results:
        icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "error": "💥"}.get(r.status, "⏳")
        with st.expander(f"{icon} {r.ticket_key} — {r.client}", expanded=(r.status == "failed")):
            col1, col2, col3 = st.columns(3)
            col1.metric("Status",       r.status.capitalize())
            col2.metric("Issues found", r.issues_found)
            col3.metric("Sendout ID",   r.sendout_id or "—")

            # Confidence score
            if r.confidence >= 0:
                conf_color = "🟢" if r.confidence >= 80 else ("🟡" if r.confidence >= 60 else "🔴")
                st.caption(f"{conf_color} AI Confidence: **{r.confidence}%** — {r.confidence_reason}")
                if r.confidence < 60 and r.status == "passed":
                    st.warning(f"⚠️ Low confidence ({r.confidence}%) — manual review recommended despite PASS")

            # DMA sendout info
            if r.sendout_name or r.sendout_date:
                st.caption(f"DMA: **{r.sendout_name or '—'}** · {r.sendout_date or '—'}")

            # G-Sheet row summary
            if r.gsheet_row:
                gs_tags    = str(r.gsheet_row.get(GSHEET_COLS.get("include_tags",""), "")).replace("nan","").strip()
                gs_excl    = str(r.gsheet_row.get(GSHEET_COLS.get("exclude_tags",""), "")).replace("nan","").strip()
                gs_client  = str(r.gsheet_row.get(GSHEET_COLS.get("client",""), "")).replace("nan","").strip()
                gs_display = str(r.gsheet_row.get("_display_str", "")).strip()
                gs_parts = []
                if gs_display:
                    gs_parts.append(gs_display)
                elif gs_client:
                    gs_parts.append(f"Row: {gs_client}")
                if gs_tags:
                    gs_parts.append(f"Incl: {gs_tags[:80]}")
                if gs_excl:
                    gs_parts.append(f"Excl: {gs_excl[:80]}")
                if gs_parts:
                    st.caption(f"G-Sheet: {' · '.join(gs_parts)}")
            elif r.sendout_id:
                st.caption("G-Sheet: no matching row found")

            if r.error_msg:
                st.error(r.error_msg)

            if r.mode == "regular" and r.checks:
                # Show each check as a coloured row
                for chk in r.checks:
                    if chk["ok"]:
                        st.success(f"✅ **{chk['label']}** — {chk['detail']}")
                    else:
                        st.error(f"❌ **{chk['label']}** — {chk['detail']}")
            elif r.report:
                if r.issues_found > 0:
                    st.error(r.report)
                else:
                    st.success(r.report)
                # Show supplemental checks (date, URL) alongside AI report
                if r.checks:
                    st.markdown("**Supplemental checks:**")
                    for chk in r.checks:
                        if chk["ok"]:
                            st.success(f"✅ **{chk['label']}** — {chk['detail']}")
                        else:
                            st.error(f"❌ **{chk['label']}** — {chk['detail']}")

            if r.jira_urls or r.api_urls:
                url_col1, url_col2 = st.columns(2)
                with url_col1:
                    if r.jira_urls:
                        st.markdown("**JIRA URLs**")
                        for u in r.jira_urls:
                            st.write(u)
                with url_col2:
                    if r.api_urls:
                        st.markdown("**API URLs**")
                        for u in r.api_urls:
                            st.write(u)

            if r.api_payload:
                with st.expander("🔍 Raw API Payload", expanded=False):
                    st.json(r.api_payload)

    # ── Clear ──
    if st.button("Clear bulk results", width='stretch'):
        for k in ("bulk_tickets", "bulk_trigger", "bulk_mode"):
            st.session_state.pop(k, None)
        st.rerun()


def _render_bulk_summary_table(results: list):
    """Render a compact colour-coded summary table of bulk results."""
    rows = []
    for r in results:
        status_icon = {"passed": "✅ Passed", "failed": f"❌ Failed ({r.issues_found} issues)",
                       "skipped": "⏭️ Skipped", "error": "💥 Error", "running": "⏳"}.get(r.status, r.status)
        rows.append({
            "Ticket":     r.ticket_key,
            "Client":     r.client,
            "Sendout ID": r.sendout_id or "—",
            "Result":     status_icon,
        })
    df = pd.DataFrame(rows)
    # Sort descending by ticket key (MAS-4113 before MAS-4077)
    if "Ticket" in df.columns:
        df = df.sort_values("Ticket", ascending=False, ignore_index=True)
    st.dataframe(df, hide_index=True, width='stretch')

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_dashboard():
    """Simple dashboard showing validation history from session state."""
    log = st.session_state.get("validation_log", [])
    data = build_dashboard_data(log)

    if data["total"] == 0:
        st.info("No validations run yet this session. Validate some tickets to see stats here.")
    else:
        # ── Top metrics ──
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total Checked", data["total"])
        m2.metric("Passed", data["passed"])
        m3.metric("Failed", data["failed"])
        m4.metric("Errors", data["errors"])
        m5.metric("Pass Rate", f"{data['pass_rate']}%")

        st.markdown("---")

        # ── Per-client table ──
        st.subheader("By Client")
        if data["by_client"]:
            client_rows = []
            for client_name, stats in sorted(data["by_client"].items()):
                rate = round(stats["passed"] / stats["total"] * 100) if stats["total"] else 0
                client_rows.append({
                    "Client":       client_name,
                    "Total":        stats["total"],
                    "Passed":       stats["passed"],
                    "Failed":       stats["failed"],
                    "Issues":       stats["issues"],
                    "Pass Rate %":  rate,
                })
            st.dataframe(pd.DataFrame(client_rows), hide_index=True, width='stretch')

        # ── Daily activity ──
        if data["daily_counts"]:
            st.subheader("Daily Activity")
            daily_rows = []
            for day in sorted(data["daily_counts"].keys()):
                d = data["daily_counts"][day]
                daily_rows.append({"Date": day, "Passed": d["passed"], "Failed": d["failed"]})
            st.dataframe(pd.DataFrame(daily_rows), hide_index=True, width='stretch')

        # ── Recent validations ──
        st.subheader("Recent Validations")
        if data["recent"]:
            recent_rows = [
                {
                    "Ticket":    e["ticket_key"],
                    "Client":    e["client"],
                    "Status":    e["status"].capitalize(),
                    "Mode":      e.get("mode", "—"),
                    "Issues":    e.get("issues", 0),
                    "Approved":  "✅" if e.get("approved") else "—",
                    "Time":      e.get("timestamp", "")[:16].replace("T", " "),
                }
                for e in data["recent"]
            ]
            st.dataframe(pd.DataFrame(recent_rows), hide_index=True, width='stretch')

        # ── Export full log ──
        if log:
            import csv, io as _io
            buf = _io.StringIO()
            w = csv.DictWriter(buf, fieldnames=["ticket_key","client","status","mode","issues","approved","timestamp"])
            w.writeheader()
            w.writerows(log)
            st.download_button(
                "Export log CSV",
                data=buf.getvalue().encode("utf-8-sig"),
                file_name=f"validation_log_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

        if st.button("Clear session log", key="clear_log"):
            st.session_state["validation_log"] = []
            st.rerun()

    # ── Weekly Report ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Weekly Approval Report")
    st.caption("Summary of approvals and AI audits over a selected period")

    col_rep1, col_rep2 = st.columns([1, 3])
    with col_rep1:
        days_back = st.selectbox("Period", [7, 14, 30, 90], index=0, key="report_days")

    if os.path.exists(_AUDIT_LOG_FILE):
        try:
            from datetime import datetime as _dt_rep, timedelta as _td_rep
            cutoff = _dt_rep.utcnow() - _td_rep(days=days_back)
            with open(_AUDIT_LOG_FILE, encoding="utf-8") as _rf:
                rep_rows = []
                for line in _rf:
                    parts = line.strip().split("\t")
                    if len(parts) >= 4:
                        try:
                            ts = _dt_rep.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
                            if ts >= cutoff and parts[2] in ("APPROVE", "BULK_APPROVE", "AI_AUDIT"):
                                rep_rows.append({
                                    "Time":   parts[0],
                                    "User":   parts[1],
                                    "Action": parts[2],
                                    "Detail": parts[3],
                                })
                        except ValueError:
                            continue

            if rep_rows:
                # Stats by user
                from collections import Counter as _Cnt
                users_count = _Cnt(r["User"] for r in rep_rows)
                actions_count = _Cnt(r["Action"] for r in rep_rows)

                col_u, col_a = st.columns(2)
                with col_u:
                    st.caption("By user")
                    for u, c in users_count.most_common():
                        st.text(f"{u}: {c}")
                with col_a:
                    st.caption("By action")
                    for a, c in actions_count.most_common():
                        st.text(f"{a}: {c}")

                import io as _io_rep, csv as _csv_rep
                _buf_rep = _io_rep.StringIO()
                _w_rep = _csv_rep.DictWriter(_buf_rep, fieldnames=["Time","User","Action","Detail"])
                _w_rep.writeheader()
                _w_rep.writerows(rep_rows)
                st.download_button(
                    f"Download report (last {days_back} days)",
                    data=_buf_rep.getvalue().encode("utf-8-sig"),
                    file_name=f"approval_report_{days_back}d_{_dt_rep.utcnow().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )
            else:
                st.info(f"No approval activity in the last {days_back} days.")
        except Exception as _exc:
            st.warning(f"Could not generate report: {_exc}")

    # ── Audit Log ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Audit Log")
    st.caption("All user actions — logins, approvals, AI audits — logged to audit.log")

    if os.path.exists(_AUDIT_LOG_FILE):
        with open(_AUDIT_LOG_FILE, encoding="utf-8") as _f:
            lines = _f.readlines()

        if lines:
            audit_rows = []
            for line in reversed(lines[-200:]):  # last 200 entries, newest first
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    audit_rows.append({
                        "Time":   parts[0],
                        "User":   parts[1],
                        "Action": parts[2],
                        "Detail": parts[3] if len(parts) > 3 else "",
                    })
            if audit_rows:
                st.dataframe(pd.DataFrame(audit_rows), hide_index=True, use_container_width=True)
                st.download_button(
                    "Download audit log",
                    data=open(_AUDIT_LOG_FILE, encoding="utf-8").read(),
                    file_name="audit.log",
                    mime="text/plain",
                )
        else:
            st.info("No audit entries yet.")
    else:
        st.info("No audit log file found.")


def main():
    if not _render_login():
        return

    _handle_deep_link()
    _init_session()

    # Inject theme CSS into Streamlit chrome based on user preference
    dark_mode = st.session_state.get("dark_mode", True)
    theme_css = STREAMLIT_DARK_CSS if dark_mode else STREAMLIT_LIGHT_CSS
    st.markdown(theme_css, unsafe_allow_html=True)

    jira_server, jira_email, jira_token, api_token, gemini_key, gemini_model, show_inspector = render_sidebar()

    st.title("⚡ Sendout Validator Pro")

    tab_validator, tab_scanner, tab_dashboard = st.tabs(["Validator", "Orphan Scanner", "Dashboard"])

    with tab_validator:
        st.markdown("---")
        render_queue(jira_server, jira_email, jira_token, api_token)
        st.markdown("---")

        client, t_id, s_id, scan_ticket, auto_leaflet_url, auto_gsheet_tags, auto_exclude_tags = render_control_panel(
            jira_server, jira_email, jira_token, api_token
        )

        if show_inspector and scan_ticket:
            with st.sidebar.expander("Field Inspector", expanded=True):
                st.json(scan_ticket.get("_raw_fields", {}))

        st.markdown("<br>", unsafe_allow_html=True)

        # Auto-validate when a new ticket+sendout pair is detected (no manual click needed)
        _auto_key = f"{t_id}:{s_id}"
        _last_auto = st.session_state.get("_last_auto_validate", "")
        if t_id and s_id and _auto_key != _last_auto and jira_email and jira_token and api_token:
            st.session_state["_last_auto_validate"] = _auto_key
            with st.spinner(f"Auto-validating {t_id}..."):
                run_validation(
                    jira_server, jira_email, jira_token, api_token,
                    client, t_id, s_id,
                    auto_leaflet_url, auto_gsheet_tags, auto_exclude_tags,
                )
                st.rerun()

        _btn_label = "Re-run check" if (t_id and s_id) else "Select a ticket to validate"
        if st.button(_btn_label, type="secondary", width='stretch', disabled=not (t_id and s_id)):
            if jira_email and jira_token and api_token and t_id and s_id:
                # Clear the auto-validate marker so it re-runs
                st.session_state["_last_auto_validate"] = ""
                run_validation(
                    jira_server, jira_email, jira_token, api_token,
                    client, t_id, s_id,
                    auto_leaflet_url, auto_gsheet_tags, auto_exclude_tags,
                )
            else:
                st.error("Missing required fields!")

        if st.session_state.get("validation_run"):
            st.divider()
            render_results(gemini_key, gemini_model, jira_server, jira_email, jira_token)

        if st.session_state.get("bulk_trigger"):
            render_bulk_validation(
                jira_server, jira_email, jira_token,
                api_token, gemini_key, gemini_model,
            )
            st.session_state["bulk_trigger"] = False

    with tab_scanner:
        render_orphan_scanner(jira_server, jira_email, jira_token, api_token)

    with tab_dashboard:
        render_dashboard()


if __name__ == "__main__":
    main()

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
import dataclasses
from bulk_validator import BulkTicketResult, run_bulk_validation, run_bulk_regular_check
from features import build_dashboard_data, record_validation, validate_scheduled_date
from parsers import pick_carousel_parser
from schedule import fetch_gsheet_data_csv, get_client_schedule_wide
import tag_registry as _reg
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
GEMINI_KEY    = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL  = "gemini-2.5-pro"
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

_validation_log: list[dict] = []
_gsheet_cache: list[dict] = []
_gsheet_fetched_at: float = 0.0
_queue_cache: list[dict] = []
_queue_fetched_at: float = 0.0

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
        params = {"ticket": ticket_key}
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


def _collect_custom_carousel_images(api_data) -> list:
    """Return per-card custom image URLs from the raw DMA API response."""
    images = []

    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "carousel" and "cards" in obj:
                for card in obj["cards"]:
                    found = None
                    for comp in card.get("components", []):
                        if comp.get("type") == "HEADER" and comp.get("format") == "IMAGE":
                            ex = comp.get("example", {})
                            handles = ex.get("header_handle", [])
                            if handles:
                                found = handles[0]
                    images.append(found)
                return
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(api_data)
    return images


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


def _get_session(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    session = _sessions.get(token)
    if not session or session["expires"] < time.time():
        _sessions.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired")
    return session


def _cached_queue() -> list[dict]:
    global _queue_cache, _queue_fetched_at
    if not _queue_cache or (time.time() - _queue_fetched_at) > 120:
        try:
            _queue_cache = fetch_all_servicedesk_issues(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN)
            _queue_fetched_at = time.time()
        except Exception as exc:
            logger.warning("Queue cache refresh failed: %s", exc)
    return _queue_cache


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
    Extract template body/footer/buttons, DMA carousel texts, image URLs,
    and tag/URL lists needed for build_comparison_data and build_results_html.
    Returns: (tmpl_body, tmpl_footer, tmpl_buttons, dma_carousel_texts,
               dma_image_urls, tag_str, api_urls, rcs_cards)
    """
    tmpl_body: str = ""
    tmpl_footer: str = ""
    tmpl_buttons: list[str] = []
    dma_carousel_texts: list[str] = []
    dma_image_urls: list[str] = []

    # Header image from component_parameters
    api_custom_images: list = []
    for cp in api.get("component_parameters", []):
        if cp.get("type") == "header_image":
            url = cp.get("value")
            if url and str(url).startswith("http"):
                dma_image_urls.append(url)
            elif cp.get("source") == "leaflet_image_url":
                dma_image_urls.append("@leaflet_image_url")
            break

    # Carousel custom images from component_parameters
    api_custom_images = _collect_custom_carousel_images(api)
    if api_custom_images:
        dma_image_urls = [img for img in api_custom_images if img]

    # RCS carousel
    rcs_cards = (api.get("google_rcs_content", {})
                    .get("richCard", {})
                    .get("carouselCard", {})
                    .get("cardContents", []))
    if rcs_cards and not dma_image_urls:
        leaflet_by_type: dict = {}
        for lf_item in (leaflet_data or []):
            lft = (lf_item.get("data") or {}).get("leaflet_type", "")
            if lft and lft not in leaflet_by_type:
                leaflet_by_type[lft] = lf_item.get("document_url") or lf_item.get("image_url", "")
        for ci, rcs_card in enumerate(rcs_cards):
            img_url = (rcs_card.get("media", {})
                           .get("contentInfo", {})
                           .get("fileUrl", ""))
            if img_url and img_url.startswith("http"):
                dma_image_urls.append(img_url)
            else:
                card_lf = rcs_card.get("leaflet_filter", {})
                lft = next((tg.get("value", "") for tg in card_lf.get("tags", [])
                            if tg.get("name") == "leaflet_type"), "")
                img_url = (leaflet_by_type.get(lft) or
                           (leaflet_by_type.get(list(leaflet_by_type.keys())[0], ""))
                           if leaflet_by_type else "")
                if img_url:
                    dma_image_urls.append(img_url)
            title = rcs_card.get("title", f"Card {ci+1}")
            desc  = rcs_card.get("description", "")
            btn   = next((s.get("action", {}).get("text", "")
                          for s in rcs_card.get("suggestions", [])), "")
            dma_carousel_texts.append(f"Card {ci+1} Title: '{title}' | Body: '{desc}' | Button: {btn}")

    # Template components
    if tmpl:
        for comp in tmpl.get("components", []):
            ctype = comp.get("type", "")
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
    if leaflet_data:
        first_leaflet = leaflet_data[0]
        l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
        l_img = first_leaflet.get("document_url") or first_leaflet.get("image_url")
        if l_url:
            dma_image_urls = [l_img if u == "@leaflet_image_url" else u for u in dma_image_urls]

    # Build tag summary string
    api_tags = extract_all_tags(api)
    tag_parts: list[str] = []
    for tg in api_tags:
        key_name = tg.get("name") or tg.get("type") or "filter"
        raw_val  = (tg.get("value") or tg.get("exclude_value") or tg.get("values")
                    or tg.get("exclude_values") or tg.get("offset_days") or "Active")
        val = f"[{len(raw_val)} values]" if isinstance(raw_val, list) else str(raw_val)
        mode = ("Exclude" if ("exclude_value" in tg or "exclude_values" in tg
                              or tg.get("mode") == "exclude") else "Include")
        if tg.get("type") == "leaflet_tag" and tg.get("offset_days") is not None:
            tag_parts.append(
                f"[{mode}] leaflet_tag={tg.get('offset_days')} (offset_days={tg.get('offset_days')})"
            )
        else:
            tag_parts.append(f"[{mode}] {_norm_tags(f'{key_name}={val}')}")

    # Build URL list
    api_urls = extract_api_urls_advanced(api)
    if tmpl:
        api_urls += extract_urls(str(tmpl))
    if leaflet_data:
        l_url = leaflet_data[0].get("public_url") or leaflet_data[0].get("url", "")
        if l_url:
            api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]

    # Resolve relative URLs to absolute
    jira_all_text = " ".join(filter(None, [
        str(jira.get("description", "")),
        str(jira.get("additional_comments", "")),
        str(jira.get("cta_link", "")),
    ]))
    jira_urls = extract_urls(jira_all_text)
    base_domain = None
    for u in jira_urls:
        try:
            p = urlparse(u)
            if p.scheme and p.netloc:
                base_domain = f"{p.scheme}://{p.netloc}"
                break
        except Exception:
            pass
    if base_domain:
        api_urls = [
            f"{base_domain}/{u.lstrip('/')}"
            if not u.startswith("http") and not u.startswith("@") and u
            else u
            for u in api_urls
        ]

    tag_str = ", ".join(tag_parts)
    return tmpl_body, tmpl_footer, tmpl_buttons, dma_carousel_texts, dma_image_urls, tag_str, api_urls, rcs_cards


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

    j_data["parsed_carousel"] = pick_carousel_parser(str(j_data.get("description", "")), client)

    return j_data, a_data, t_data, leaflet_data


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Validator Pro API")

# Initialise tag-registry SQLite DB on startup (no-op if already exists)
_reg.init_db()

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
    return HTMLResponse(open(path, encoding="utf-8").read())


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
    entry = _USERS.get(username)
    if not entry or not hmac.compare_digest(_hash_pwd(req.password), entry[1]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_hex(32)
    _sessions[token] = {"user": username, "name": entry[0], "expires": time.time() + SESSION_TTL}
    logger.info("LOGIN\t%s", entry[0])
    return {"token": token, "name": entry[0]}


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
        rows.append({
            "key":     issue["key"],
            "summary": summary,
            "client":  client,
            "date":    str(fields.get("customfield_12665", ""))[:10],
            "status":  fields.get("status", {}).get("name", ""),
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
    result = []
    for t in tasks:
        # Only skip tasks explicitly marked inactive — treat None/missing as active
        if t.get("is_active") is False:
            continue
        task_id = str(t.get("id") or t.get("task_id") or t.get("sendout_id") or "")
        if not task_id:
            continue
        name = str(t.get("name") or t.get("campaign_name") or t.get("task_name")
                   or t.get("title") or t.get("sendout_name") or "")
        date = str(t.get("scheduled_date") or t.get("date") or t.get("send_date") or "")[:10]
        result.append({"id": task_id, "name": name, "date": date})
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

                date_matches = []
                for task in tasks:
                    if task.get("is_active") is False:
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
        # Match by JIRA ticket key first, then by date
        matched_row = None
        for row in schedule:
            jira_link = str(row.get(GSHEET_COLS.get("jira_link", ""), "")).strip()
            if req.ticket_key and (req.ticket_key == jira_link or req.ticket_key in jira_link):
                matched_row = row
                break
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
        raise HTTPException(status_code=502, detail=str(exc))

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
        raise HTTPException(status_code=502, detail=str(exc))

    # Prepare all data needed for build_comparison_data
    (tmpl_body, tmpl_footer, tmpl_buttons,
     dma_carousel_texts, dma_image_urls, tag_str, api_urls, rcs_cards) = _prepare_audit_data(
        a_data, t_data, leaflet_data, j_data, req.client
    )

    # Build jira_for_comparison with slide labels stripped
    jira_for_comparison = dict(j_data)
    if jira_for_comparison.get("description"):
        jira_for_comparison["description"] = _strip_slide_labels(jira_for_comparison["description"])

    # Kaufland RCS Sunday static cards
    if req.client == "Kaufland RCS" and rcs_cards:
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

    try:
        result = run_ai_audit(
            GEMINI_KEY, GEMINI_MODEL, comparison_data, req.client,
            jira_images=j_data.get("carousel_images"),
            dma_images=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI audit failed: {exc}")

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

    ai_result_text = result.get("audit_report", "Error extracting report")
    ai_urls = {
        "jira": result.get("jira_extracted_urls", []),
        "api":  result.get("api_extracted_urls", []),
    }
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
        confidence=ai_result.get("confidence") if isinstance(ai_result, dict) else None,
    )

    # Write AI status back to JIRA
    from ai_audit import _is_audit_error
    if not _is_audit_error(ai_result_text):
        jira_status = "Rejected" if issues > 0 else "Approved"
        write_ai_status_to_jira(JIRA_SERVER, JIRA_EMAIL, JIRA_TOKEN, req.ticket_key, jira_status)
        logger.info("JIRA AI status → %s for %s", jira_status, req.ticket_key)

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
        "html":       html_output,
        "ai_result":  ai_result_text,
        "issues":     issues,
        "confidence": result.get("confidence", -1),
        "ticket_key": req.ticket_key,
        "client":     req.client,
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
        queue = _cached_queue()
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


# ── Bulk validation ──────────────────────────────────────────────────────────

class BulkRequest(BaseModel):
    ticket_keys: list[str]


def _serialize_result(r: BulkTicketResult) -> dict:
    d = dataclasses.asdict(r)
    # keep only JSON-safe fields (drop large api_payload)
    d.pop("api_payload", None)
    return d


@app.post("/api/bulk-validate")
async def bulk_validate(req: BulkRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    key_set = set(req.ticket_keys)
    issues = [i for i in _cached_queue() if i["key"] in key_set]
    if not issues:
        raise HTTPException(status_code=404, detail="None of the requested tickets found in JIRA queue")

    results: list[BulkTicketResult] = run_bulk_regular_check(
        tickets=issues,
        gsheet_data=_gsheet(),
        jira_server=JIRA_SERVER,
        jira_email=JIRA_EMAIL,
        jira_token=JIRA_TOKEN,
        api_token=API_TOKEN,
        on_progress=lambda r, i, t: None,
    )

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

    return [_serialize_result(r) for r in results]


@app.post("/api/bulk-ai-audit")
async def bulk_ai_audit(req: BulkRequest, authorization: Optional[str] = Header(None)):
    _get_session(authorization)
    key_set = set(req.ticket_keys)
    issues = [i for i in _cached_queue() if i["key"] in key_set]
    if not issues:
        raise HTTPException(status_code=404, detail="None of the requested tickets found in JIRA queue")

    results: list[BulkTicketResult] = run_bulk_validation(
        tickets=issues,
        gsheet_data=_gsheet(),
        jira_server=JIRA_SERVER,
        jira_email=JIRA_EMAIL,
        jira_token=JIRA_TOKEN,
        api_token=API_TOKEN,
        gemini_key=GEMINI_KEY,
        gemini_model=GEMINI_MODEL,
        on_progress=lambda r, i, t: None,
    )

    session = _sessions.get((authorization or "").split(" ", 1)[-1], {})
    user_name = session.get("name", "Validator Pro")

    global _validation_log
    for r in results:
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
        # Send Slack alert for each failed ticket
        if r.status == "failed" and r.issues_found > 0:
            failed_checks = [c["label"] for c in (r.checks or []) if not c.get("ok")]
            if not failed_checks and r.report:
                failed_checks = _extract_failed_checks(r.report)
            _send_slack_alert(
                ticket_key=r.ticket_key,
                client=r.client,
                mode="AI Bulk Check",
                issues=r.issues_found,
                user_name=user_name,
                failed_checks=failed_checks[:8],
                sendout_id=r.sendout_id or "",
            )

    return [_serialize_result(r) for r in results]


# ── Orphan Scanner ────────────────────────────────────────────────────────────

@app.get("/api/orphan-scan")
async def orphan_scan(
    days_ahead: int = 7,
    days_back:  int = 5,          # also look at sendouts from N days ago
    authorization: Optional[str] = Header(None),
):
    """
    Scan all DMA accounts for sendouts not matched in the JIRA queue or G-Sheet.
    Window: [today - days_back  …  today + days_ahead]
    Returns a list of result objects classified as: ok | no_jira | no_gsheet | auto
    """
    import asyncio as _asyncio
    _get_session(authorization)

    # Run all blocking I/O in a thread pool so the async event loop is not blocked.
    # This prevents the scan (15+ sequential HTTP calls) from freezing the server.
    loop = _asyncio.get_running_loop()

    def _do_scan():
        return _orphan_scan_sync(days_ahead, days_back)

    try:
        return await loop.run_in_executor(None, _do_scan)
    except Exception as exc:
        logger.error("orphan_scan crashed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Orphan scan failed: {exc}")


def _orphan_scan_sync(days_ahead: int, days_back: int) -> dict:
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
                if task.get("is_active") is False:
                    continue
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


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8502, reload=True)

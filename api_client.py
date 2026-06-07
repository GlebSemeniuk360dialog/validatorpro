"""
api_client.py — All external HTTP / JIRA calls in one place.

Design rules:
- Every requests.get/post has an explicit timeout.
- Failures are logged, never silently swallowed.
- Return types are explicit: data on success, None / error dict on failure.
- No Streamlit imports — this module is UI-agnostic.
"""

import base64
import functools
import io
import logging
from datetime import datetime, timedelta

import pytz
import requests
from dateutil import parser as dateutil_parser
from jira import JIRA
from PIL import Image

from config import JIRA_AI_STATUS_FIELD, JIRA_FIELD_IDS

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15  # seconds — applied to every outbound request

# ---------------------------------------------------------------------------
# DMA API
# ---------------------------------------------------------------------------

def fetch_api_key_via_dma(token: str, account_id: int) -> str | None:
    """Return the WABA API key for *account_id*, or None on failure."""
    if not token:
        return None
    url = f"https://dma.360dialog.io/api/v2/accounts/{account_id}"
    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {token.strip()}"}, timeout=HTTP_TIMEOUT)
        res.raise_for_status()
        return res.json().get("d360_api_key")
    except requests.RequestException as exc:
        logger.warning("fetch_api_key_via_dma failed for account %s: %s", account_id, exc)
        return None


def fetch_api_data(token: str, sendout_id: str) -> dict | None:
    """
    Return the DMA sendout detail dict, an error dict, or None.
    Error dicts always have keys: error_code, error_msg.
    """
    if not token:
        return {"error_code": "NO_TOKEN", "error_msg": "DMA API token not provided."}
    url = f"https://dma.360dialog.io/api/v2/sendout/{sendout_id}/details"
    try:
        res = requests.get(url, headers={"Authorization": f"Bearer {token.strip()}"}, timeout=HTTP_TIMEOUT)
        if res.status_code == 200:
            return res.json()
        if res.status_code == 404:
            return {"error_code": 404, "error_msg": "Sendout ID not found or token lacks permission."}
        return {"error_code": res.status_code, "error_msg": res.text[:500]}
    except requests.RequestException as exc:
        logger.error("fetch_api_data failed for sendout %s: %s", sendout_id, exc)
        return {"error_code": "EXCEPTION", "error_msg": str(exc)}


def fetch_account_leaflets(token: str, account_id: int, sendout_date_str: str) -> list[dict]:
    """Return leaflets active around *sendout_date_str*, empty list on failure."""
    if not token:
        return []
    try:
        dt = dateutil_parser.parse(sendout_date_str)
        from datetime import datetime as _dt
        today = _dt.now().strftime("%Y-%m-%d")
        # Use today as floor so we don't fetch already-expired leaflets
        date_from = max(dt.strftime("%Y-%m-%d"), today)
        params = {
            "date_from": date_from,
            "date_to": (dt + timedelta(days=6)).strftime("%Y-%m-%d"),
            "size": 50,  # Fetch enough to get both leaflet_type=special and leaflet_type=regular
        }
        res = requests.get(
            f"https://dma.360dialog.io/api/v2/accounts/{account_id}/leaflets",
            headers={"Authorization": f"Bearer {token.strip()}"},
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict):
            return data.get("items") or data.get("leaflets") or ([data] if "url" in data else [])
        return data if isinstance(data, list) else []
    except requests.RequestException as exc:
        logger.warning("fetch_account_leaflets failed for account %s: %s", account_id, exc)
        return []
    except Exception as exc:
        logger.warning("fetch_account_leaflets parse error: %s", exc)
        return []



def fetch_pending_sendouts(token: str, account_id: int, days_ahead: int = 30, days_back: int = 0) -> list[dict]:
    """
    Fetch pending DMA sendouts for the next *days_ahead* days using the sage/get_tasks endpoint.
    Returns a list of task dicts, empty list on failure.

    NOTE: We intentionally do NOT filter by action_type. Different clients use
    different DMA action types (e.g. "dma_sendout" for RCS, "waba_sendout" or
    similar for Kaufland WABA). Passing action_type would silently exclude WABA
    tasks. Date-window + status filtering is sufficient.

    Strategy: try statuses in order, return on first non-empty result.
    Last-resort: no status filter at all.
    """
    if not token or not account_id:
        return []
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.utcnow()
    date_from = (now - _td(days=days_back)).strftime("%Y-%m-%d 00:00:00")
    date_to   = (now + _td(days=days_ahead)).strftime("%Y-%m-%d 00:00:00")

    def _parse_response(data) -> list[dict]:
        """Extract task list from any common DMA API response envelope."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Try all known envelope keys
            for key in ("tasks", "items", "results", "data", "sendouts", "records"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    return val
            # Some endpoints wrap a single list in an arbitrary key
            for val in data.values():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    return val
        return []

    base_url = f"https://dma.360dialog.io/api/v2/accounts/{account_id}/sage/get_tasks"
    headers  = {"Authorization": f"Bearer {token.strip()}"}
    base_params = {"date_from": date_from, "date_to": date_to, "size": 200}

    # Try "pending" first (most common), then "scheduled", then "approved"
    for status in ("pending", "scheduled", "approved"):
        try:
            res = requests.get(
                base_url,
                headers=headers,
                params={**base_params, "status": status},
                timeout=HTTP_TIMEOUT,
            )
            res.raise_for_status()
            tasks = _parse_response(res.json())
            if tasks:
                logger.info(
                    "fetch_pending_sendouts: account %s status=%s → %d task(s)",
                    account_id, status, len(tasks)
                )
                # Log keys of first task to help identify disabled/filtered fields
                if tasks:
                    logger.info("fetch_pending_sendouts: sample task keys=%s sample=%s",
                                list(tasks[0].keys())[:20],
                                {k: tasks[0].get(k) for k in ("name","status","enabled","active","is_active","is_enabled","type","action_type","task_type") if k in tasks[0]})
                return tasks
        except requests.RequestException as exc:
            logger.warning("fetch_pending_sendouts failed for account %s status=%s: %s",
                           account_id, status, exc)
        except Exception as exc:
            logger.warning("fetch_pending_sendouts parse error account %s: %s", account_id, exc)

    # Last resort: no status filter — but strip disabled/cancelled/draft tasks
    _INACTIVE = {"disabled", "cancelled", "canceled", "draft", "inactive", "deleted", "archived"}
    try:
        res = requests.get(base_url, headers=headers, params=base_params, timeout=HTTP_TIMEOUT)
        res.raise_for_status()
        tasks = _parse_response(res.json())
        before = len(tasks)
        tasks = [
            t for t in tasks
            if str(t.get("status") or t.get("task_status") or t.get("state") or "").lower()
               not in _INACTIVE
        ]
        logger.info("fetch_pending_sendouts: account %s no-status-filter → %d task(s) (%d removed as inactive)",
                    account_id, len(tasks), before - len(tasks))
        return tasks
    except Exception as exc:
        logger.warning("fetch_pending_sendouts fallback failed account %s: %s", account_id, exc)
        return []

def fetch_dma_image_bytes(img_url: str) -> bytes | None:
    """Download image bytes from *img_url*, returning None on failure."""
    if not img_url or not str(img_url).startswith("http"):
        return None
    try:
        res = requests.get(img_url, timeout=HTTP_TIMEOUT)
        res.raise_for_status()
        return res.content
    except requests.RequestException as exc:
        logger.warning("fetch_dma_image_bytes failed for %s: %s", img_url, exc)
        return None


# ---------------------------------------------------------------------------
# WABA template API
# ---------------------------------------------------------------------------

_template_cache: dict[tuple, tuple] = {}   # (waba_key, name) → (timestamp, result)
_TEMPLATE_TTL = 600  # 10 minutes


def fetch_template_data(waba_key: str, template_name: str) -> dict | None:
    """Return the named WABA template dict, or None.

    Results are cached for _TEMPLATE_TTL seconds so stale templates don't
    persist until restart (the old lru_cache had no expiry).
    """
    import time as _time
    key = (waba_key, template_name)
    cached = _template_cache.get(key)
    if cached and (_time.monotonic() - cached[0]) < _TEMPLATE_TTL:
        return cached[1]
    if not waba_key:
        return None
    result = None
    try:
        res = requests.get(
            "https://waba-v2.360dialog.io/v1/configs/templates",
            headers={"D360-API-KEY": waba_key},
            timeout=HTTP_TIMEOUT,
        )
        res.raise_for_status()
        for t in res.json().get("waba_templates", []):
            if t.get("name") == template_name:
                result = t
                break
        if result is None:
            logger.info("Template '%s' not found in WABA response.", template_name)
    except requests.RequestException as exc:
        logger.warning("fetch_template_data failed for '%s': %s", template_name, exc)
        return None
    _template_cache[key] = (_time.monotonic(), result)
    return result


# ---------------------------------------------------------------------------
# JIRA
# ---------------------------------------------------------------------------

def _jira_client(server: str, email: str, token: str) -> JIRA:
    return JIRA({"server": server}, basic_auth=(email, token.strip()))


def fetch_service_desk_issues_paginated(
    base_url: str,
    email: str,
    token: str,
    project_key: str = "MAS",
    queue_id: str = "734",
    start_at: int = 0,
    max_results: int = 50,
) -> list[dict]:
    """Return a page of service desk issues. Returns [] on any failure."""
    if not token:
        return []
    headers = {"Accept": "application/json"}
    auth = (email, token.strip())
    try:
        sd_res = requests.get(
            f"{base_url}/rest/servicedeskapi/servicedesk",
            auth=auth,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        sd_res.raise_for_status()
        sd_id = next(
            (sd["id"] for sd in sd_res.json().get("values", []) if sd.get("projectKey") == project_key),
            None,
        )
        if not sd_id:
            logger.warning("Service desk for project '%s' not found.", project_key)
            return []

        res = requests.get(
            f"{base_url}/rest/servicedeskapi/servicedesk/{sd_id}/queue/{queue_id}/issue",
            params={"start": start_at, "limit": max_results},
            auth=auth,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        res.raise_for_status()
        issues = res.json().get("values", [])

        # Enrich with customfield_16417 (AI Checked) via standard REST search
        # Service desk queue API may not return all custom fields
        if issues:
            try:
                keys = [iss["key"] for iss in issues]
                jql = f"key in ({','.join(keys[:50])})"
                enrich_res = requests.get(
                    f"{base_url}/rest/api/2/search",
                    params={"jql": jql, "fields": "customfield_16417", "maxResults": 50},
                    auth=auth,
                    headers=headers,
                    timeout=HTTP_TIMEOUT,
                )
                if enrich_res.status_code == 200:
                    enrich_map = {
                        iss["key"]: iss["fields"].get("customfield_16417")
                        for iss in enrich_res.json().get("issues", [])
                    }
                    for iss in issues:
                        iss.setdefault("fields", {})
                        val = enrich_map.get(iss["key"])
                        if val is not None:
                            iss["fields"]["customfield_16417"] = val
                    sample = next(((k,v) for k,v in enrich_map.items() if v), None)
                    if sample:
                        logger.info("AI Checked sample %s: %r", sample[0], sample[1])
            except Exception as enrich_exc:
                logger.warning("Could not enrich AI Checked field: %s", enrich_exc)

        return issues
    except requests.RequestException as exc:
        logger.error("fetch_service_desk_issues_paginated failed: %s", exc)
        return []


def fetch_all_servicedesk_issues(
    base_url: str,
    email: str,
    token: str,
    project_key: str = "MAS",
    queue_id: str = "734",
) -> list[dict]:
    """
    Paginate through ALL pages of a service-desk queue and return every issue.

    The service desk queue endpoint only returns a limited set of fields — notably
    it omits customfield_16693 ("WABA or RCS").  After the bulk fetch we enrich
    any Kaufland tickets (identified by reporter email domain) with a single
    per-issue REST call to backfill that field.
    """
    if not token:
        return []
    headers = {"Accept": "application/json"}
    auth = (email, token.strip())

    # ── Step 1: resolve service desk ID ──────────────────────────────────────
    try:
        sd_res = requests.get(
            f"{base_url}/rest/servicedeskapi/servicedesk",
            auth=auth, headers=headers, timeout=HTTP_TIMEOUT,
        )
        sd_res.raise_for_status()
        sd_id = next(
            (sd["id"] for sd in sd_res.json().get("values", []) if sd.get("projectKey") == project_key),
            None,
        )
    except Exception as exc:
        logger.warning("fetch_all_servicedesk_issues: could not resolve sd_id: %s", exc)
        return []

    if not sd_id:
        logger.warning("fetch_all_servicedesk_issues: service desk for '%s' not found", project_key)
        return []

    # ── Step 2: paginate through queue endpoint ───────────────────────────────
    all_issues: list[dict] = []
    start = 0
    page_size = 100
    while True:
        try:
            res = requests.get(
                f"{base_url}/rest/servicedeskapi/servicedesk/{sd_id}/queue/{queue_id}/issue",
                params={"start": start, "limit": page_size},
                auth=auth, headers=headers, timeout=HTTP_TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
            batch = data.get("values", [])
            all_issues.extend(batch)
            if data.get("isLastPage", True) or not batch:
                break
            start += len(batch)
        except Exception as exc:
            logger.warning("fetch_all_servicedesk_issues: page start=%d failed: %s", start, exc)
            break

    logger.info("fetch_all_servicedesk_issues: fetched %d issues from queue %s", len(all_issues), queue_id)

    # ── Step 3: enrich Kaufland issues with customfield_16693 (WABA or RCS) ──
    # The queue endpoint omits this field; fetch it per-issue via the REST API.
    _ENRICH_FIELDS = "customfield_16693,customfield_14287"
    for issue in all_issues:
        reporter_email = (
            (issue.get("fields", {}).get("reporter") or {}).get("emailAddress") or ""
        ).lower()
        if "kaufland.de" not in reporter_email:
            continue
        issue_key = issue.get("key", "")
        if not issue_key:
            continue
        try:
            enrich_res = requests.get(
                f"{base_url}/rest/api/2/issue/{issue_key}",
                params={"fields": _ENRICH_FIELDS},
                auth=auth, headers=headers, timeout=HTTP_TIMEOUT,
            )
            if enrich_res.status_code == 200:
                enrich_fields = enrich_res.json().get("fields", {})
                issue["fields"]["customfield_16693"] = enrich_fields.get("customfield_16693")
                # Also backfill segment field if missing
                if not issue["fields"].get("customfield_14287"):
                    issue["fields"]["customfield_14287"] = enrich_fields.get("customfield_14287")
        except Exception as exc:
            logger.warning("fetch_all_servicedesk_issues: enrich %s failed: %s", issue_key, exc)

    return all_issues


def fetch_jira_tickets_jql(
    base_url: str,
    email: str,
    token: str,
    jql: str,
    fields: list[str] | None = None,
    page_size: int = 100,
) -> list[dict]:
    """
    Fetch ALL JIRA issues matching *jql*, paginating until exhausted.
    Returns a list of raw issue dicts (same shape as the REST /search response).
    Empty list on failure.
    """
    if not token:
        return []
    fields = fields or ["summary", "description", "reporter", "customfield_12665", "status"]
    headers = {"Accept": "application/json"}
    auth = (email, token.strip())
    all_issues: list[dict] = []
    start = 0
    while True:
        try:
            res = requests.get(
                f"{base_url}/rest/api/2/search",
                params={
                    "jql": jql,
                    "fields": ",".join(fields),
                    "maxResults": page_size,
                    "startAt": start,
                },
                auth=auth,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
            batch = data.get("issues", [])
            all_issues.extend(batch)
            total = data.get("total", 0)
            start += len(batch)
            if not batch or start >= total:
                break
        except requests.RequestException as exc:
            logger.warning("fetch_jira_tickets_jql failed at start=%d: %s", start, exc)
            break
        except Exception as exc:
            logger.warning("fetch_jira_tickets_jql parse error at start=%d: %s", start, exc)
            break
    logger.info("fetch_jira_tickets_jql: fetched %d issues for JQL: %s", len(all_issues), jql[:120])
    return all_issues


def approve_ticket_jira(
    server: str,
    email: str,
    token: str,
    ticket_key: str,
    approver_name: str = "Gleb Approved",
) -> tuple[bool, str]:
    """Add *approver_name* to the approval_status field. Returns (success, message)."""
    try:
        jira = _jira_client(server, email, token)
        issue = jira.issue(ticket_key)
        current = getattr(issue.fields, "customfield_15654", []) or []
        existing = [i.value for i in current if hasattr(i, "value")]
        if approver_name not in existing:
            issue.update(
                fields={"customfield_15654": [{"value": v} for v in existing + [approver_name]]}
            )
        return True, "Success"
    except Exception as exc:
        logger.error("approve_ticket_jira failed for %s: %s", ticket_key, exc)
        return False, str(exc)


def write_ai_status_to_jira(
    server: str,
    email: str,
    token: str,
    ticket_key: str,
    status: str,
) -> bool:
    """Write the AI audit status field. Returns True on success."""
    try:
        jira = _jira_client(server, email, token)
        issue = jira.issue(ticket_key)
        issue.update(fields={JIRA_AI_STATUS_FIELD: [{"value": status}]})
        return True
    except Exception as exc:
        logger.warning("write_ai_status_to_jira failed for %s: %s", ticket_key, exc)
        return False


def fetch_jira_form_answers(server: str, email: str, token: str, issue_key: str) -> str | None:
    """
    Fetch form answers for a JIRA issue via the Atlassian Forms REST API.
    Returns the form content as a structured text string (same format as
    parse_jira_carousel_form expects), or None if no form / fetch fails.

    Requires the X-ExperimentalApi: opt-in header.
    API: GET https://api.atlassian.com/jira/forms/cloud/{cloudId}/issue/{issueKey}/form
    """
    try:
        # Get cloud ID (cached after first call)
        cloud_resp = requests.get(
            f"{server.rstrip('/')}/_edge/tenant_info",
            timeout=HTTP_TIMEOUT,
        )
        cloud_id = cloud_resp.json().get("cloudId", "") if cloud_resp.ok else ""
        if not cloud_id:
            logger.warning("fetch_jira_form_answers: could not get cloudId for %s", issue_key)
            return None

        hdrs = {
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",
        }
        auth = (email, token)

        # 1. List forms on this issue
        forms_resp = requests.get(
            f"https://api.atlassian.com/jira/forms/cloud/{cloud_id}/issue/{issue_key}/form",
            auth=auth, headers=hdrs, timeout=HTTP_TIMEOUT,
        )
        if not forms_resp.ok:
            logger.debug("fetch_jira_form_answers: no forms on %s (HTTP %s)", issue_key, forms_resp.status_code)
            return None

        forms = forms_resp.json()
        if not forms:
            return None

        # Use the first submitted form (there's typically only one)
        form = next((f for f in forms if f.get("submitted")), forms[0])
        form_id = form.get("id", "")
        if not form_id:
            return None

        # 2. Get simplified answers
        ans_resp = requests.get(
            f"https://api.atlassian.com/jira/forms/cloud/{cloud_id}/issue/{issue_key}/form/{form_id}/format/answers",
            auth=auth, headers=hdrs, timeout=HTTP_TIMEOUT,
        )
        if not ans_resp.ok:
            logger.warning("fetch_jira_form_answers: answers fetch failed for %s form %s (HTTP %s)",
                           issue_key, form_id, ans_resp.status_code)
            return None

        answers = ans_resp.json()  # list of {label, answer}
        if not answers:
            return None

        # Build a normalised dict with the same shape as parse_jira_carousel_form
        # so callers can set data["parsed_carousel"] directly — no regex needed.
        def _get(label_kws: list[str]) -> str:
            for item in answers:
                lbl = item.get("label", "").lower()
                if any(kw in lbl for kw in label_kws):
                    return str(item.get("answer", "")).strip()
            return ""

        # Log all labels so we can debug new form layouts
        all_labels = [item.get("label", "") for item in answers]
        logger.info("fetch_jira_form_answers: %s form labels: %s", issue_key, all_labels)

        intro = _get(["main body text", "body text", "intro", "message", "text"])

        # Parse per-card sections from "Card N: text" format
        def _parse_cards(raw: str) -> list[str]:
            import re as _re
            if not raw:
                return []
            parts = _re.split(r'(?:Card|Karte|Slide)\s*\d+\s*[:\-]', raw, flags=_re.IGNORECASE)
            return [p.strip() for p in parts if p.strip()]

        bodies_raw = _get(["card body texts", "card bodies", "card text", "body", "text", "copy", "content"])
        btns_raw   = _get(["card button texts", "button texts", "button text", "cta text", "button", "cta", "call to action"])
        urls_raw   = _get(["card button urls", "button urls", "card urls", "url", "link", "cta url", "cta link"])

        bodies = _parse_cards(bodies_raw)
        btns   = _parse_cards(btns_raw)
        # URLs may be on one line (space-separated "Card 1: url Card 2: url") — split properly
        urls   = _parse_cards(urls_raw)

        n = max(len(bodies), len(btns), len(urls))
        if n == 0:
            # Last resort: try to find any answer that looks like it has multiple card sections
            import re as _re
            for item in answers:
                raw = str(item.get("answer", ""))
                card_sections = _re.split(r'(?:Card|Karte|Slide)\s*\d+\s*[:\-]', raw, flags=_re.IGNORECASE)
                card_sections = [s.strip() for s in card_sections if s.strip()]
                if len(card_sections) > 1:
                    bodies = card_sections
                    n = len(bodies)
                    logger.info("fetch_jira_form_answers: %s fallback card parse on label '%s' → %d cards",
                                issue_key, item.get("label",""), n)
                    break
        if n == 0:
            logger.warning("fetch_jira_form_answers: %s — could not parse any cards from labels %s", issue_key, all_labels)
            return None

        cards = [
            {
                "body": bodies[i] if i < len(bodies) else "",
                "btn":  btns[i]   if i < len(btns)   else "",
                "url":  urls[i]   if i < len(urls)    else "",
            }
            for i in range(n)
        ]

        result = {"intro": intro, "cards": cards, "urls": [c["url"] for c in cards if c["url"]]}
        logger.info("fetch_jira_form_answers: parsed form for %s — intro=%d chars, %d cards",
                    issue_key, len(intro), len(cards))
        return result

    except Exception as exc:
        logger.warning("fetch_jira_form_answers: failed for %s: %s", issue_key, exc)
        return None


def fetch_ticket_data(server: str, email: str, token: str, ticket_id: str, fetch_images: bool = True, max_images: int = 10) -> dict | None:
    """
    Return a normalised dict of JIRA ticket data including attachments.
    Returns None on fatal error.
    """
    try:
        jira = _jira_client(server, email, token)
        issue = jira.issue(ticket_id)
    except Exception as exc:
        logger.error("fetch_ticket_data — could not fetch issue %s: %s", ticket_id, exc)
        return None

    data: dict = {"key": issue.key, "_raw_fields": {}}
    if hasattr(issue, "raw"):
        data["_raw_fields"] = issue.raw.get("fields", {})

    # --- Standard field extraction ---
    for field_key, field_id in JIRA_FIELD_IDS.items():
        raw = getattr(issue.fields, field_id, None)
        data[field_key] = _extract_field_value(field_key, field_id, raw)

    # Log all non-null raw fields to help discover carousel form field IDs
    raw_fields = data.get("_raw_fields", {})
    if not data.get("description"):
        logger.info("=== RAW FIELDS for %s (description empty) ===", ticket_id)
        for k, v in sorted(raw_fields.items()):
            if v is not None and str(v).strip() not in ("", "None", "[]", "{}"):
                logger.info("  %s = %r", k, str(v)[:120])

    # If description is empty, try to reconstruct from various sources
    if not data.get("description"):
        # Priority 1: Atlassian Forms API (ProForma / JSM native forms)
        # Returns a parsed dict {intro, cards, urls} — set parsed_carousel directly,
        # no regex needed. Also set description to the intro so copy checks have text.
        form_data = fetch_jira_form_answers(server, email, token, issue.key)
        if form_data and isinstance(form_data, dict):
            data["parsed_carousel"] = form_data
            data["description"] = form_data.get("intro", "")
            logger.info("fetch_ticket_data: carousel form data from Forms API for %s", ticket_id)
        # Priority 2: additional_comments field (cover note — least reliable)
        elif data.get("additional_comments"):
            data["description"] = str(data["additional_comments"])
        else:
            # Priority 3: raw description field
            raw_desc = raw_fields.get("description")
            if raw_desc:
                data["description"] = str(raw_desc)
            else:
                # Priority 4: scan all string fields for carousel keywords
                carousel_keys = []
                for k, v in raw_fields.items():
                    if isinstance(v, str) and any(
                        kw in v.lower() for kw in ("card", "slide", "cta", "flugblatt", "prospekt")
                    ):
                        carousel_keys.append(v)
                if carousel_keys:
                    data["description"] = "\n\n".join(carousel_keys)
                    logger.info("Built description from raw fields for %s", ticket_id)

    # --- Comments ---
    data["comments"] = []
    comment_obj = getattr(issue.fields, "comment", None)
    if comment_obj and hasattr(comment_obj, "comments"):
        for c in comment_obj.comments:
            data["comments"].append(
                f"[{c.created[:10]}] {c.author.displayName}: {c.body}"
            )

    # --- Attachments / images ---
    data["carousel_images"] = []
    data["attachment_bytes"] = None
    data["attachment_name"] = None

    attachments = list(getattr(issue.fields, "attachment", None) or [])
    logger.info("Ticket %s has %d attachment(s) on ticket", ticket_id, len(attachments))

    # Also collect attachments added in comments (JIRA stores them separately)
    try:
        comments = getattr(issue.fields, "comment", None)
        comment_list = getattr(comments, "comments", []) if comments else []
        for comment in comment_list:
            for cat in getattr(comment, "attachment", []) or []:
                attachments.append(cat)
        # Alternative: some JIRA versions embed attachment info in comment body URLs
        # Fetch comment attachments via REST as a fallback
        if not any(getattr(c, "attachment", None) for c in comment_list):
            import requests as _rq
            import base64 as _b64c
            _creds_c = _b64c.b64encode(f"{email}:{token.strip()}".encode()).decode()
            _hdrs_c = {"Authorization": f"Basic {_creds_c}"}
            _url = f"{server.rstrip('/')}/rest/api/2/issue/{ticket_id}?fields=attachment,comment"
            _resp = _rq.get(_url, headers=_hdrs_c, timeout=HTTP_TIMEOUT)
            if _resp.status_code == 200:
                _issue_json = _resp.json()
                _comment_atts = []
                for _c in _issue_json.get("fields", {}).get("comment", {}).get("comments", []):
                    for _a in _c.get("attachments", []):
                        _comment_atts.append(type("Att", (), {
                            "filename": _a.get("filename", ""),
                            "mimeType": _a.get("mimeType", ""),
                            "content":  _a.get("content", ""),
                            "id":       _a.get("id", ""),
                        })())
                if _comment_atts:
                    logger.info("Ticket %s: found %d comment attachment(s) via REST",
                                ticket_id, len(_comment_atts))
                    attachments.extend(_comment_atts)
    except Exception as exc:
        logger.warning("Could not fetch comment attachments for %s: %s", ticket_id, exc)

    logger.info("Ticket %s has %d attachment(s) total (ticket + comments)", ticket_id, len(attachments))

    # Accept any image attachment — drop the size floor (was 12KB, too aggressive for
    # optimised carousel images). Filter only obvious non-images by extension.
    _IMG_MIMES = ("image/",)
    _IMG_EXTS  = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".avif")

    def _is_image(att) -> bool:
        mime = getattr(att, "mimeType", "") or ""
        name = getattr(att, "filename", "") or ""
        if mime.lower().startswith("image/"):
            return True
        # Fall back to extension check when MIME is missing or octet-stream
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return ext in _IMG_EXTS

    img_atts = [a for a in attachments if _is_image(a)]
    logger.info("Ticket %s: %d image attachment(s) after filter: %s",
                ticket_id, len(img_atts),
                [getattr(a, "filename", "?") for a in img_atts])

    sorted_atts = _sort_attachments(img_atts)

    # Always store sorted attachment metadata (no bytes) so callers can
    # selectively download later (e.g. bulk mode detects card count first).
    data["_img_attachments"] = sorted_atts

    # Collect non-image document attachments for freestyle AI audit
    _DOC_EXTS = (".xlsx", ".xls", ".pdf", ".csv", ".docx", ".doc")
    doc_atts = [
        a for a in attachments
        if not _is_image(a) and any(
            getattr(a, "filename", "").lower().endswith(ext) for ext in _DOC_EXTS
        )
    ]
    data["_doc_attachments"] = []  # will be filled with {"name", "bytes", "mime"} dicts

    # Download attachments sequentially using requests with basic auth.
    # The jira session causes "multiple values for timeout" on some attachments,
    # so we use requests directly with explicit basic auth.
    import base64 as _b64
    _creds  = _b64.b64encode(f"{email}:{token.strip()}".encode()).decode()
    _headers = {"Authorization": f"Basic {_creds}"}

    if not fetch_images:
        logger.info("Ticket %s: skipping image downloads (fetch_images=False)", ticket_id)
    else:
        for att in sorted_atts[:max_images]:
            att_url = getattr(att, "content", None)
            if not att_url:
                logger.warning("Attachment '%s' has no content URL", att.filename)
                continue
            logger.info("Downloading attachment '%s' from %s", att.filename, att_url)
            try:
                r = requests.get(att_url, headers=_headers,
                                 timeout=HTTP_TIMEOUT, allow_redirects=True)
                logger.info("  -> HTTP %d, %d bytes, content-type: %s",
                            r.status_code, len(r.content),
                            r.headers.get("Content-Type", "?"))
                if r.status_code == 200 and len(r.content) > 100:
                    data["carousel_images"].append({"name": att.filename, "bytes": r.content})
                else:
                    logger.warning("  -> Failed: HTTP %d body: %s",
                                   r.status_code, r.text[:200])
            except Exception as exc:
                logger.error("  -> Exception downloading '%s': %s", att.filename, exc)

    if data["carousel_images"]:
        data["attachment_bytes"] = data["carousel_images"][0]["bytes"]
        data["attachment_name"] = data["carousel_images"][0]["name"]

    # Download document attachments (always, regardless of fetch_images flag)
    for att in doc_atts[:5]:  # max 5 docs to avoid runaway downloads
        att_url = getattr(att, "content", None)
        if not att_url:
            continue
        logger.info("Downloading doc attachment '%s' from %s", att.filename, att_url)
        try:
            r = requests.get(att_url, headers=_headers,
                             timeout=HTTP_TIMEOUT, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 0:
                data["_doc_attachments"].append({
                    "name": att.filename,
                    "bytes": r.content,
                    "mime": getattr(att, "mimeType", "") or "",
                })
                logger.info("  -> Stored doc '%s' (%d bytes)", att.filename, len(r.content))
            else:
                logger.warning("  -> Doc download failed: HTTP %d", r.status_code)
        except Exception as exc:
            logger.error("  -> Exception downloading doc '%s': %s", att.filename, exc)

    return data


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_field_value(field_key: str, field_id: str, raw):
    """Normalise a raw JIRA field value to a Python primitive."""
    if field_id == JIRA_FIELD_IDS["request_type"]:
        if hasattr(raw, "value"):
            return raw.value
        if hasattr(raw, "requestType"):
            return getattr(raw.requestType, "name", str(raw))
        if hasattr(raw, "currentRequestType"):
            return getattr(raw.currentRequestType, "name", str(raw))
        if isinstance(raw, dict) and "value" in raw:
            return raw["value"]
        return str(raw)

    if raw is None:
        return None
    if isinstance(raw, list):
        return [i.value if hasattr(i, "value") else str(i) for i in raw]
    if hasattr(raw, "value"):
        return raw.value
    if hasattr(raw, "name"):
        return raw.name
    if isinstance(raw, dict):
        return raw.get("value") or raw.get("name") or str(raw)
    return str(raw)


def _slide_number(filename: str) -> int:
    """
    Extract slide ordering number from an attachment filename.
    Takes the LAST small (_01.._20) trailing segment — handles filenames like
    AD_REWE_ZK_Vorschaubild_16-2026_001_03.jpg -> 3
    """
    stem = re.sub(r"\.[a-z0-9]+$", "", filename.lower())

    # 1. Explicit keyword as standalone word + number (slide, card, img, carousel)
    #    'bild' excluded — it appears mid-word in German e.g. 'Vorschaubild'
    m = re.search(r"(?<![a-z])(?:slide|card|pic|img|carousel)[-_\s]*0*(\d+)", stem)
    if m:
        n = int(m.group(1))
        if 0 < n <= 50:
            return n

    # 2. All _NN / -NN segments; take the last one that is a plausible slide (1-20)
    all_segs = re.findall(r"[-_]0*(\d{1,2})(?=[-_]|$)", stem)
    for seg in reversed(all_segs):
        n = int(seg)
        if 0 < n <= 20:
            return n

    # 3. Trailing digits fallback
    m = re.search(r"(\d+)$", stem)
    if m:
        n = int(m.group(1))
        if 0 < n <= 50:
            return n

    return 9999


def _sort_attachments(img_atts: list) -> list:
    """
    Sort attachment objects so the most recent version of each numbered slot
    comes first; unnumbered attachments follow in creation order.
    """
    import re
    from dateutil import parser as dp

    _MIN_DT = datetime.min.replace(tzinfo=pytz.UTC)

    def _created(att):
        try:
            return dp.parse(att.created) if hasattr(att, "created") else _MIN_DT
        except Exception:
            return _MIN_DT

    latest_per_slot: dict[int, object] = {}
    unnumbered: list = []

    for att in img_atts:
        num = _slide_number(att.filename)
        if num == 9999:
            unnumbered.append(att)
            continue
        existing = latest_per_slot.get(num)
        if existing is None or _created(att) > _created(existing):
            latest_per_slot[num] = att

    sorted_atts = [latest_per_slot[k] for k in sorted(latest_per_slot)]

    unnumbered.sort(key=_created)
    sorted_atts.extend(unnumbered)

    if not sorted_atts and img_atts:
        img_atts.sort(key=_created, reverse=True)
        sorted_atts = [img_atts[0]]

    return sorted_atts


import re  # noqa: E402 — needed by _slide_number, placed after function defs to avoid circular

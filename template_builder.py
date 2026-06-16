"""
template_builder.py — Phase 0 (read-only) proposal generator.

Takes the structured v2 form data already on a ticket (jira dict from
fetch_ticket_data: parsed_carousel + date/timezone/footer/cta/channel) and
produces a *proposed* DMA/WhatsApp template payload + sendout schedule, purely
deterministically. NO network writes — this only assembles and previews what a
human would otherwise type into the DMA UI, plus deterministic validation
warnings (WhatsApp/RCS field limits, missing media, approval needs).

The template payload mirrors the real 360dialog/WhatsApp schema returned by
fetch_template_data:
  basic    : [HEADER?, BODY, FOOTER?, BUTTONS?]
  carousel : [BODY(intro), CAROUSEL{cards:[{components:[HEADER?, BODY, BUTTONS?]}]}]
RCS uses the google_rcs_content richCard.carouselCard shape.

This is a sketch for human review; nothing here submits to Meta or schedules.
"""

import re
from typing import Optional

# WhatsApp / RCS field limits (deterministic validation, not AI)
_WA_BODY_MAX   = 1024
_CARD_BODY_MAX = 160   # carousel card body (Meta limit, stricter than top-level body)
_WA_FOOTER_MAX = 60
_BTN_TEXT_MAX  = 25
_CARD_MIN      = 2
_CARD_MAX      = 10
_RCS_TITLE_MAX = 200
_RCS_DESC_MAX  = 2000


def _placeholder_count(text: str) -> int:
    return len(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", text or "")))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _split_schedule(jira: dict) -> dict:
    """Pull sendout date/time/timezone from the standard JIRA fields."""
    raw = str(jira.get("date", "") or "")
    tz = jira.get("timezone", "")
    if isinstance(tz, dict):
        tz = tz.get("value", "")
    date_part, time_part = "", ""
    if raw:
        # ISO like 2026-06-19T20:00:00.000+0200
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", raw)
        if m:
            date_part, time_part = m.group(1), m.group(2)
    return {
        "date": date_part,
        "time": time_part,
        "timezone": str(tz or ""),
        "raw": raw,
    }


def _wa_buttons(name: str, url: str) -> Optional[dict]:
    name = (name or "").strip()
    url = (url or "").strip()
    if not name and not url:
        return None
    btn = {"type": "URL", "text": name or "Open"}
    if url:
        btn["url"] = url
    return {"type": "BUTTONS", "buttons": [btn]}


def _wa_header(media: str) -> Optional[dict]:
    media = (media or "").strip()
    comp = {"type": "HEADER", "format": "IMAGE"}
    if media:
        comp["example"] = {"header_handle": [media]}
    return comp


def _build_waba(parsed: dict, jira: dict, warnings: list, notes: list) -> dict:
    intro = (parsed.get("intro") or "").strip()
    footer = (jira.get("footer_text") or parsed.get("footer") or "").strip()
    cards = parsed.get("cards") or []
    is_carousel = "carousel" in str(parsed.get("sendout_format", "")).lower() or len(cards) > 1

    components: list = []

    if not is_carousel:
        # ── Basic single-message template ──
        media = jira.get("_basic_media", "")  # rarely populated; placeholder
        if media:
            components.append(_wa_header(media))
        body = {"type": "BODY", "text": intro}
        nph = _placeholder_count(intro)
        if nph:
            body["example"] = {"body_text": [["Example"] * nph]}
            notes.append(f"Body has {nph} placeholder(s) {{1}}… — example value(s) auto-filled, confirm before submit.")
        components.append(body)
        if footer:
            components.append({"type": "FOOTER", "text": footer})
        btn = _wa_buttons(jira.get("cta_button", ""), jira.get("cta_link", ""))
        if btn:
            components.append(btn)
        # validation
        if len(intro) > _WA_BODY_MAX:
            warnings.append(f"Body is {len(intro)} chars (max {_WA_BODY_MAX}).")
        if not intro:
            warnings.append("Body text is empty — WhatsApp requires a BODY component.")
        if footer and len(footer) > _WA_FOOTER_MAX:
            warnings.append(f"Footer is {len(footer)} chars (max {_WA_FOOTER_MAX}).")
    else:
        # ── Carousel template ──
        intro_body = {"type": "BODY", "text": intro}
        nph = _placeholder_count(intro)
        if nph:
            intro_body["example"] = {"body_text": [["Example"] * nph]}
        components.append(intro_body)

        # Meta rule: every card must share the SAME component structure (same
        # components, order, and number/type of buttons). So if any card has a
        # button, every card gets a BUTTONS component.
        any_button = any((c.get("btn") or c.get("url")) for c in cards)
        card_comps = []
        for i, c in enumerate(cards):
            cc = []
            cc.append(_wa_header(c.get("media", "")))
            cbody = (c.get("body") or "").strip()
            cc.append({"type": "BODY", "text": cbody})
            if any_button:
                btn = _wa_buttons(c.get("btn", ""), c.get("url", ""))
                if btn:
                    cc.append(btn)
                else:
                    warnings.append(f"Card {i+1} has no button while others do — carousel cards must all share the same buttons.")
            card_comps.append({"components": cc})
            # per-card validation
            if c.get("btn") and len(c["btn"]) > _BTN_TEXT_MAX:
                warnings.append(f"Card {i+1} button text '{c['btn']}' is {len(c['btn'])} chars (max {_BTN_TEXT_MAX}).")
            if not cbody:
                warnings.append(f"Card {i+1} has no body text — required on every carousel card.")
            elif len(cbody) > _CARD_BODY_MAX:
                warnings.append(f"Card {i+1} body is {len(cbody)} chars (carousel card max {_CARD_BODY_MAX}).")
            if not c.get("media"):
                warnings.append(f"Card {i+1} has no media — a carousel card HEADER (IMAGE/VIDEO) is required; upload the asset.")
            elif str(c.get("media")).startswith("form-file:"):
                warnings.append(f"Card {i+1} media is a form upload — POST the file to DMA (/api/v2/media) and use the returned `url` as the header example before creating the template.")

        # Consistency: all cards must have the same number of components.
        if len({len(cc["components"]) for cc in card_comps}) > 1:
            warnings.append("Carousel cards have inconsistent structure — every card must have the same components (HEADER + BODY + matching buttons).")
        components.append({"type": "CAROUSEL", "cards": card_comps})

        n = len(cards)
        if n < _CARD_MIN or n > _CARD_MAX:
            warnings.append(f"Carousel has {n} card(s); WhatsApp allows {_CARD_MIN}-{_CARD_MAX}.")

    return {"components": components}


def _rcs_suggestion(btn: str, url: str) -> Optional[dict]:
    """A single RCS suggestion in the documented shape (action with openUrlAction)."""
    if not (btn or url):
        return None
    act = {"text": (btn or "Open")[:_BTN_TEXT_MAX]}
    if url:
        act["openUrlAction"] = {"url": url}
    return {"action": act}


def _build_rcs(parsed: dict, warnings: list, notes: list) -> dict:
    """
    Return google_rcs_content. Per the docs:
      - single message → {text, suggestions:[{reply|action}]}
      - carousel       → {richCard:{carouselCard:{cardWidth, cardContents:[…]}}}
    """
    cards = parsed.get("cards") or []
    is_carousel = ("carousel" in str(parsed.get("sendout_format", "")).lower()) or len(cards) > 1

    if not is_carousel:
        c = cards[0] if cards else {}
        text = (parsed.get("intro") or c.get("body") or "").strip()
        out: dict = {"text": text}
        sug = _rcs_suggestion(c.get("btn", ""), c.get("url", ""))
        if sug:
            out["suggestions"] = [sug]
        if not text:
            warnings.append("RCS message text is empty.")
        return out

    contents = []
    for i, c in enumerate(cards):
        title = (c.get("title") or "").strip()
        desc = (c.get("body") or "").strip()
        media = (c.get("media") or "").strip()
        card = {"title": title, "description": desc}
        if media:
            card["media"] = {"height": "MEDIUM", "contentInfo": {"fileUrl": media}}
        sug = _rcs_suggestion(c.get("btn", ""), c.get("url", ""))
        if sug:
            card["suggestions"] = [sug]
        contents.append(card)
        if len(title) > _RCS_TITLE_MAX:
            warnings.append(f"RCS card {i+1} title is {len(title)} chars (max {_RCS_TITLE_MAX}).")
        if len(desc) > _RCS_DESC_MAX:
            warnings.append(f"RCS card {i+1} description is {len(desc)} chars (max {_RCS_DESC_MAX}).")
        if not media:
            warnings.append(f"RCS card {i+1} has no media — upload the asset.")
    n = len(cards)
    if n and (n < _CARD_MIN or n > _CARD_MAX):
        warnings.append(f"RCS carousel has {n} card(s); allowed {_CARD_MIN}-{_CARD_MAX}.")
    return {"richCard": {"carouselCard": {"cardWidth": "MEDIUM", "cardContents": contents}}}


def build_sendout_proposal(
    jira: dict,
    *,
    client: str = "",
    language: str = "de",
    category: str = "MARKETING",
    template_name: Optional[str] = None,
) -> dict:
    """
    Build a read-only proposal {channel, template, schedule, recipients,
    warnings, notes} from the v2-form-enriched JIRA dict. Deterministic;
    performs no network calls.
    """
    parsed = jira.get("parsed_carousel") or {}
    warnings: list = []
    notes: list = []

    channel_raw = str(jira.get("waba_or_rcs") or parsed.get("platform") or "")
    if isinstance(jira.get("waba_or_rcs"), list) and jira["waba_or_rcs"]:
        channel_raw = jira["waba_or_rcs"][0]
    is_rcs = "rcs" in channel_raw.lower()
    channel = "RCS" if is_rcs else "WABA"

    sendout_type = str(parsed.get("sendout_type") or jira.get("request_type") or "")
    is_new_template = "special" in sendout_type.lower() or "create" in sendout_type.lower()

    schedule = _split_schedule(jira)
    if not schedule["date"]:
        warnings.append("No sendout date found on the ticket.")

    # Suggested template name (new) or reuse note (regular update)
    fmt = "carousel" if (("carousel" in str(parsed.get("sendout_format", "")).lower())
                         or len(parsed.get("cards") or []) > 1) else "basic"
    if not template_name:
        ymd = (schedule["date"] or "").replace("-", "")
        template_name = f"{_slug(client) or 'sendout'}_{fmt}_{ymd}"

    if is_new_template:
        notes.append("Sendout Type = special/new → a NEW template must be created and APPROVED by Meta before scheduling (async, can take up to ~24h).")
    else:
        notes.append("Sendout Type = regular update → reuse the existing APPROVED template; only the schedule/content changes. No Meta approval wait.")

    if is_rcs:
        notes.append("RCS uses Google's pipeline (separate from WhatsApp/Meta).")
        template = {
            "name": template_name,
            "language": language,
            "channel": "RCS",
            "content": _build_rcs(parsed, warnings, notes),
        }
    else:
        wa = _build_waba(parsed, jira, warnings, notes)
        template = {
            "name": template_name,
            "language": language,
            "category": category,
            "components": wa["components"],
        }
        notes.append(f"language='{language}' and category='{category}' are defaults — confirm before submit.")

    return {
        "ticket": jira.get("key", ""),
        "channel": channel,
        "format": fmt,
        "sendout_type": sendout_type,
        "new_template_required": is_new_template,
        "template": template,
        "schedule": schedule,
        "recipients": {
            "segment": str(jira.get("segment", "") or "(none specified)"),
            "preview_numbers": parsed.get("preview_numbers", ""),
        },
        "warnings": warnings,
        "notes": notes,
    }


# ── Sendout payload (campaigns API: /sendout/simulate | /schedule | /execute) ──
# The campaigns API body (Api_v2_SendoutRequest) is the INVERSE of what
# fetch_api_data reads: a template_name + component_parameters that BIND the
# template's slots (header_image→custom URL, body_text→first_name, …) + filters
# (tags / shop_number / locale …) + google_rcs_content for RCS.
#
# Real examples observed:
#   basic    : [{value:<img>, type:header_image, source:custom},
#               {type:body_text, source:first_name}]
#   carousel : [{type:carousel, source:custom_cards, cards:[{component_parameters:[…]}]}]
#   filters  : [{tags:[{name:leaflet_accepted, value:true}, …]}] | [{shop_number:"3691"}]
#
# NOTE: body_text bindings (first_name / shop_address / …) are template-specific
# and cannot be fully inferred from the form. For RECURRING sendouts the robust
# path is clone-and-patch: take last week's sendout (fetch_api_data) and update
# only the deltas (this week's media + date). This builder reconstructs a
# best-effort payload from the form for review/simulate; it flags what needs the
# template's real variable map.

_SENDOUT_ACTION = "weekly_notifications"  # ActionEnum value used for notification campaigns


def build_sendout_payload(
    jira: dict,
    *,
    template_name: str = "",
    body_binding: str = "first_name",
) -> dict:
    """
    Build a campaigns-API sendout payload (Api_v2_SendoutRequest) from the
    v2-form-enriched JIRA dict. Deterministic; performs no network calls.
    Suitable as the body for POST /sendout/simulate (dry-run).

    Returns {payload, warnings, notes, account_hint}. `template_name` should be
    the client's approved template (known for recurring sendouts).
    """
    parsed = jira.get("parsed_carousel") or {}
    warnings: list = []
    notes: list = []

    channel_raw = str(jira.get("waba_or_rcs") or parsed.get("platform") or "")
    if isinstance(jira.get("waba_or_rcs"), list) and jira["waba_or_rcs"]:
        channel_raw = jira["waba_or_rcs"][0]
    is_rcs = "rcs" in channel_raw.lower()

    cards = parsed.get("cards") or []
    is_carousel = ("carousel" in str(parsed.get("sendout_format", "")).lower()) or len(cards) > 1

    schedule = _split_schedule(jira)
    payload: dict = {
        "action": _SENDOUT_ACTION,
        "sendout_type": "google_rcs" if is_rcs else "meta_waba",
    }
    if template_name:
        payload["template_name"] = template_name
    elif not is_rcs:
        # RCS carries content inline (google_rcs_content) and needs no template.
        warnings.append("No template_name — WABA sendouts must reference an existing approved template (from the client's config or last week's sendout); the form doesn't carry it.")
    if schedule["raw"]:
        payload["sendout_date"] = schedule["raw"]
    else:
        warnings.append("No sendout_date on the ticket.")

    if is_rcs:
        payload["google_rcs_content"] = _build_rcs(parsed, warnings, notes)
        notes.append("RCS sendout — content carried in google_rcs_content (no component_parameters).")
    elif is_carousel:
        card_objs = []
        for i, c in enumerate(cards):
            cp = []
            media = c.get("media") or ""
            if media.startswith("form-file:"):
                cp.append({"type": "header_image", "source": "custom"})  # value resolved later
                notes.append(f"Card {i+1} media is a form upload ({media}) — POST the file to DMA (/api/v2/media); use the returned `url` as this header_image value before scheduling.")
            elif media:
                cp.append({"value": media, "type": "header_image", "source": "custom"})
            else:
                warnings.append(f"Card {i+1}: no media — header_image binding will be missing.")
            cp.append({"type": "body_text", "source": body_binding})
            if c.get("url"):
                cp.append({"value": c["url"], "type": "button_cta", "source": "custom"})
            card_objs.append({"component_parameters": cp})
        payload["component_parameters"] = [
            {"type": "carousel", "source": "custom_cards", "cards": card_objs}
        ]
    else:
        cp = []
        media = jira.get("_basic_media", "") or ""
        if media:
            cp.append({"value": media, "type": "header_image", "source": "custom"})
        cp.append({"type": "body_text", "source": body_binding})
        if jira.get("cta_link"):
            cp.append({"value": jira["cta_link"], "type": "button_cta", "source": "custom"})
        payload["component_parameters"] = cp

    # Audience filters are not in the form — they come from config / G-Sheet.
    payload["filters"] = []
    notes.append("filters[] is empty — attach audience tags/shop filters from client config / G-Sheet before scheduling.")
    notes.append(f"body_text bound to source='{body_binding}' by default — verify against the template's real variable map (clone-and-patch from last week's sendout is more reliable for recurring).")

    return {
        "payload": payload,
        "warnings": warnings,
        "notes": notes,
    }


_WEEKDAY_NAME = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def build_recurrence_pattern(jira: dict, recurrence: str = "one_off") -> dict:
    """
    Build a recurrence_pattern for sage/events/add.
      recurrence='one_off' → {recurrence_type: ONE_OFF, start_date, timezone}
      recurrence='weekly'  → {recurrence_type: WEEK, days_of_week, recurrence_interval, start_date, timezone}
    start_date is naive ISO (no offset); timezone is carried separately, matching
    the documented example.

    NOTE: days_of_week index convention is assumed Monday=0 (Python weekday()).
    Confirm against the API before scheduling recurring events.
    """
    sch = _split_schedule(jira)
    raw = sch["raw"]
    # Naive ISO: strip any timezone offset / trailing Z
    start_naive = re.sub(r"(?:Z|[+-]\d{2}:?\d{2})$", "", raw).split(".")[0] if raw else ""
    tz = sch["timezone"] or "CET"

    if recurrence == "weekly":
        wd = None
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            import datetime as _d
            wd = _d.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).weekday()
        return {
            "recurrence_type": "WEEK",
            "days_of_week": [str(wd)] if wd is not None else [],
            "recurrence_interval": "1",
            "start_date": start_naive,
            "timezone": tz,
        }
    return {
        "recurrence_type": "ONE_OFF",
        "start_date": start_naive,
        "timezone": tz,
    }


def build_event_payload(
    jira: dict,
    *,
    template_name: str = "",
    campaign_name: str = "",
    recurrence: str = "one_off",
    body_binding: str = "first_name",
) -> dict:
    """
    Build the full POST /sage/events/add body that wraps a sendout in an event
    action. Returns {payload, warnings, notes}. No network calls.
    """
    inner = build_sendout_payload(jira, template_name=template_name, body_binding=body_binding)
    body = inner["payload"]
    warnings = list(inner["warnings"])
    notes = list(inner["notes"])

    name = campaign_name or (str(jira.get("key", "")) + " sendout").strip()
    rec = build_recurrence_pattern(jira, recurrence)
    if recurrence == "weekly":
        wd = rec.get("days_of_week") or []
        day = _WEEKDAY_NAME[int(wd[0])] if wd and wd[0].isdigit() else "?"
        notes.append(f"Recurring WEEKLY on {day} (days_of_week index assumes Monday=0 — confirm with API).")

    event = {
        "name": name,
        "event_actions": [{
            "name": str(jira.get("key", "")) or "Sendout",
            "action_type": "dma_sendout",
            "data": {"body": body},
        }],
        "recurrence_pattern": rec,
    }
    return {"payload": event, "warnings": warnings, "notes": notes}


_HEADER_MEDIA_TYPES = ("header_image", "header_video", "header_document")


def _patch_media_in_params(params: list, media: list, changed: list, path: str = "") -> None:
    """Replace custom header-media `value`s positionally with `media`, recording diffs."""
    idx = 0
    for cp in params:
        t = cp.get("type", "")
        if t == "carousel":
            for ci, card in enumerate(cp.get("cards", []) or []):
                _patch_media_in_params(
                    card.get("component_parameters", []) or [], media, changed,
                    path=f"{path}card[{ci}].",
                )
        elif t in _HEADER_MEDIA_TYPES and cp.get("source") == "custom":
            if idx < len(media) and media[idx]:
                old = cp.get("value", "")
                if media[idx] != old:
                    cp["value"] = media[idx]
                    changed.append(f"{path}{t}: {old or '(none)'} → {media[idx]}")
            idx += 1


def clone_and_patch_event(
    prev_sendout: dict,
    *,
    new_date: str,
    timezone: str = "CET",
    media: Optional[list] = None,
    tag_overrides: Optional[dict] = None,
    campaign_name: str = "",
    action_name: str = "Sendout",
    recurrence: str = "one_off",
) -> dict:
    """
    Build a fresh /sage/events/add body by cloning a previous executed sendout
    (dict from fetch_api_data) and patching only the deltas: sendout_date and,
    optionally, custom header-media URLs (positional). Keeps the template,
    component_parameters bindings and audience filters intact — the reliable
    path for recurring sendouts. Pure; no network calls.

    Defensively drops credential / bot_id fields so nothing sensitive is copied.
    Returns {payload, changed, warnings, notes}.
    """
    import copy
    warnings: list = []
    notes: list = []
    changed: list = []

    sendout_type = prev_sendout.get("sendout_type") or (
        "google_rcs" if prev_sendout.get("google_rcs_content") else "meta_waba"
    )
    body: dict = {"action": _SENDOUT_ACTION, "sendout_type": sendout_type}

    tmpl = prev_sendout.get("template_name")
    if tmpl:
        body["template_name"] = tmpl

    # Clone the content (component_parameters or RCS), never the credentials.
    if sendout_type == "google_rcs":
        if prev_sendout.get("google_rcs_content"):
            body["google_rcs_content"] = copy.deepcopy(prev_sendout["google_rcs_content"])
    else:
        cp = copy.deepcopy(prev_sendout.get("component_parameters", []) or [])
        if media:
            _patch_media_in_params(cp, media, changed)
        body["component_parameters"] = cp

    body["filters"] = copy.deepcopy(prev_sendout.get("filters", []) or [])
    # Patch weekly-drifting tag values (e.g. this week's topic) by tag name.
    if tag_overrides:
        for f in body["filters"]:
            for tag in f.get("tags", []) or []:
                nm = tag.get("name")
                if nm in tag_overrides and "value" in tag:
                    old = tag.get("value", "")
                    new = tag_overrides[nm]
                    if new != old:
                        tag["value"] = new
                        changed.append(f"tag {nm}: {old or '(none)'} → {new}")
        seen = {t.get("name") for f in body["filters"] for t in (f.get("tags") or [])}
        for nm in tag_overrides:
            if nm not in seen:
                warnings.append(f"tag_override '{nm}' not present in cloned filters — not applied.")
    body["sendout_date"] = new_date
    if (prev_sendout.get("sendout_date") or "") != new_date:
        changed.append(f"sendout_date: {prev_sendout.get('sendout_date','(none)')} → {new_date}")

    # Safety: never carry credentials/bot ids forward
    for k in ("credential", "bot_id", "credential_value", "auth_token"):
        body.pop(k, None)

    if not tmpl and sendout_type != "google_rcs":
        warnings.append("Previous sendout had no template_name — cannot clone a WABA sendout without it.")
    if media and not changed:
        notes.append("Media supplied but no custom header-media slots matched — nothing patched.")

    jira_like = {"date": new_date, "timezone": timezone, "key": campaign_name}
    rec = build_recurrence_pattern(jira_like, recurrence)
    event = {
        "name": campaign_name or "Sendout",
        "event_actions": [{
            "name": action_name,
            "action_type": "dma_sendout",
            "data": {"body": body},
        }],
        "recurrence_pattern": rec,
    }
    notes.append("Cloned from last sendout — template, bindings and filters reused; only date/media patched.")
    return {"payload": event, "changed": changed, "warnings": warnings, "notes": notes}


def validate_sendout_payload(payload: dict) -> list:
    """Offline schema sanity-check (required fields). Returns list of problems."""
    problems = []
    if not payload.get("action"):
        problems.append("missing required: action")
    for i, cp in enumerate(payload.get("component_parameters", []) or []):
        if not cp.get("type"):
            problems.append(f"component_parameters[{i}] missing required: type")
        if not cp.get("source"):
            problems.append(f"component_parameters[{i}] missing required: source")
        for j, card in enumerate(cp.get("cards", []) or []):
            for k, ccp in enumerate(card.get("component_parameters", []) or []):
                if not ccp.get("type") or not ccp.get("source"):
                    problems.append(f"component_parameters[{i}].cards[{j}].component_parameters[{k}] missing type/source")
    for i, f in enumerate(payload.get("filters", []) or []):
        for j, tag in enumerate(f.get("tags", []) or []):
            if not tag.get("name"):
                problems.append(f"filters[{i}].tags[{j}] missing required: name")
    return problems


def render_proposal_text(p: dict) -> str:
    """Human-readable preview for review."""
    import json
    lines = []
    lines.append(f"=== PROPOSAL · {p['ticket']} ===")
    lines.append(f"Channel: {p['channel']} | Format: {p['format']} | Sendout type: {p['sendout_type'] or '?'}")
    s = p["schedule"]
    lines.append(f"Schedule: {s['date']} {s['time']} {s['timezone']}".rstrip())
    lines.append(f"Recipients: segment={p['recipients']['segment']}")
    lines.append(f"New template needed: {'YES (Meta approval)' if p['new_template_required'] else 'no — reuse approved template'}")
    lines.append("")
    lines.append("--- Proposed template payload ---")
    lines.append(json.dumps(p["template"], indent=2, ensure_ascii=False))
    if p["warnings"]:
        lines.append("")
        lines.append("⚠️  WARNINGS (fix before submit):")
        for w in p["warnings"]:
            lines.append(f"   • {w}")
    if p["notes"]:
        lines.append("")
        lines.append("ℹ️  NOTES:")
        for n in p["notes"]:
            lines.append(f"   • {n}")
    return "\n".join(lines)

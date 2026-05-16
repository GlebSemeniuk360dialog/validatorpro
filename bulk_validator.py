"""
bulk_validator.py — Core logic for running AI audits across multiple tickets.
No Streamlit UI calls — returns plain data so the UI layer can render it.
"""

import logging
import time
from dataclasses import dataclass, field

import difflib

def _strip_slide_labels(text: str) -> str:
    """Remove everything from the first Slide N: marker onwards, keeping only the intro."""
    import re as _re
    m = _re.search(r'(?im)^[\s*]*(?:Slide|Slider)\s*\d+\s*:', text)
    if m:
        return text[:m.start()].strip()
    return text.strip()

from ai_audit import build_comparison_data, run_ai_audit, _is_audit_error
from api_client import (
    fetch_account_leaflets,
    fetch_api_data,
    fetch_api_key_via_dma,
    fetch_dma_image_bytes,
    fetch_pending_sendouts,
    fetch_template_data,
    fetch_ticket_data,
    write_ai_status_to_jira,
)
from config import CLIENT_CONFIGS, GSHEET_COLS
from features import validate_scheduled_date, check_url_reachability
from parsers import pick_carousel_parser
from schedule import get_client_schedule
from utils import (
    clean_button_text,
    compare_urls_smart,
    detect_client_from_text,
    extract_all_tags,
    extract_api_urls_advanced,
    extract_urls,
    is_media_url,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 3  # seconds between Gemini calls


@dataclass
class BulkTicketResult:
    ticket_key: str
    client: str
    sendout_id: str
    status: str = "pending"        # pending | running | passed | failed | skipped | error
    mode: str = "ai"               # ai | regular
    issues_found: int = 0
    report: str = ""
    error_msg: str = ""
    jira_urls: list = field(default_factory=list)
    api_urls: list  = field(default_factory=list)
    checks: list = field(default_factory=list)   # list of {"label","ok","detail"} dicts
    api_payload: dict = field(default_factory=dict)  # raw DMA API response for debugging
    sendout_name: str = ""         # DMA task name for display
    sendout_date: str = ""         # DMA scheduled_date for display
    gsheet_row: dict = field(default_factory=dict)  # matched G-Sheet row for display
    confidence: int = -1           # AI confidence score 0-100 (-1 = not set)
    confidence_reason: str = ""    # AI explanation of confidence


def _detect_client(issue: dict) -> str:
    """Best-effort client detection from a queue issue dict."""
    summary = issue["fields"].get("summary", "")
    desc    = issue["fields"].get("description") or ""
    text    = f"{summary} {desc}".strip()
    text_lower = text.lower()

    # ALDI Sued: sonntag/reminder are special cases
    if any(kw in text_lower for kw in ("sonntag", "reminder")):
        return "ALDI Sued"
    # ALDI Portugal is a single client — segment detected from sendout name
    if "aldi portugal" in text_lower or "aldi pt" in text_lower:
        return "ALDI Portugal"

    return detect_client_from_text(text, list(CLIENT_CONFIGS.keys())) or "Unknown"


def _find_sendout_id(ticket_key: str, client: str, gsheet_data: list[dict],
                     api_token: str = "", jira_date: str = "",
                     jira_summary: str = "") -> str:
    """Return the sendout ID by matching pending DMA tasks.
    Matches by date first; if multiple tasks share the same date,
    picks the one whose name best matches the JIRA summary.
    """
    if not api_token or not jira_date or client not in CLIENT_CONFIGS:
        return ""
    account_id = CLIENT_CONFIGS[client].get("account_id")
    if not account_id:
        return ""
    from datetime import datetime as _dt
    import difflib as _dl
    try:
        target_date = _dt.fromisoformat(jira_date[:10]).date()
        tasks = fetch_pending_sendouts(api_token, account_id)
        # Collect all active tasks matching the date
        date_matches = []
        for task in tasks:
            if not task.get("is_active", True):
                continue
            try:
                task_date = _dt.fromisoformat(
                    str(task.get("scheduled_date", ""))[:10]
                ).date()
                if task_date == target_date:
                    date_matches.append(task)
            except Exception:
                continue

        if not date_matches:
            return ""
        if len(date_matches) == 1:
            return str(date_matches[0].get("id") or date_matches[0].get("task_id", ""))

        # Multiple matches on same date — use keyword + segment-aware scoring
        client_lower = client.lower()

        # ALDI Sued: match "Reminder" keyword across JIRA summary and DMA task name
        if "aldi sued" in client_lower or "aldi süd" in client_lower or "aldi sud" in client_lower:
            import re as _re_sued
            summary_lower = jira_summary.lower()

            # "Reminder" sendout — match task that also has "reminder" in its name
            if "reminder" in summary_lower:
                for task in date_matches:
                    task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                    if "reminder" in task_name:
                        return str(task.get("id") or task.get("task_id", ""))

            # Resolve JIRA segment to canonical DMA keyword via config mappings
            from config import CLIENT_CONFIGS as _CC2
            _mappings = _CC2.get("ALDI Sued", {}).get("mappings", {})

            # Build lookup: display value / key -> canonical DMA keyword
            _seg_lookup: dict[str, str] = {}
            for mapping_dict in _mappings.values():
                for display, dma_kw in mapping_dict.items():
                    _seg_lookup[display.lower()] = dma_kw.lower()
                    _seg_lookup[dma_kw.lower()]  = dma_kw.lower()

            # Find which segment keyword appears in JIRA summary
            canonical_kw = None
            for display, dma_kw in _seg_lookup.items():
                if display in summary_lower:
                    canonical_kw = dma_kw
                    break

            if canonical_kw:
                def _task_has_segment_positively(task_name: str, kw: str) -> bool:
                    """Return True if kw appears in task name OUTSIDE any (excl ...) clause."""
                    # Remove exclusion clauses first
                    clean = _re_sued.sub(r'\(excl[^)]*\)', '', task_name).strip()
                    return kw in clean

                for task in date_matches:
                    task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                    if _task_has_segment_positively(task_name, canonical_kw):
                        return str(task.get("id") or task.get("task_id", ""))

                # No task with positive segment match — fall back to the Standard/Regular task
                for task in date_matches:
                    task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                    clean = _re_sued.sub(r'\(excl[^)]*\)', '', task_name).strip()
                    if any(w in clean for w in ("standard", "regular")):
                        return str(task.get("id") or task.get("task_id", ""))

            else:
                # No segment found — this is a Regular/Standard sendout
                for task in date_matches:
                    task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                    clean = _re_sued.sub(r'\(excl[^)]*\)', '', task_name).strip()
                    if any(w in clean for w in ("standard", "regular")):
                        return str(task.get("id") or task.get("task_id", ""))

        # ALDI Portugal: use JIRA segment field to match Northern vs Regular DMA sendout
        if "aldi portugal" in client_lower:
            # jira_summary already includes the segment value (appended in _fetch_and_enrich)
            # But also check j_data directly for clarity
            combined_lower = jira_summary.lower()
            is_northern = any(kw in combined_lower for kw in ("northern", "norte", "north"))
            for task in date_matches:
                task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                task_is_northern = any(kw in task_name for kw in ("northern", "norte", "north"))
                if is_northern == task_is_northern:
                    return str(task.get("id") or task.get("task_id", ""))

        # Step 3: word-level scoring against JIRA summary
        if jira_summary:
            summary_words = set(jira_summary.lower().split())

            def _score(task):
                task_name = (task.get("name") or task.get("campaign_name") or "").lower()
                word_hits = sum(1 for w in summary_words if len(w) > 3 and w in task_name)
                sim = _dl.SequenceMatcher(None, jira_summary.lower(), task_name).ratio()
                return word_hits * 10 + sim

            best = max(date_matches, key=_score)
            return str(best.get("id") or best.get("task_id", ""))

        # Step 4: No summary — return first match
        return str(date_matches[0].get("id") or date_matches[0].get("task_id", ""))
    except Exception:
        pass
    return ""


def _build_audit_payload(
    jira: dict,
    api: dict,
    tmpl: dict | None,
    leaflet_data: list[dict],
    client: str,
) -> tuple[dict, list[str], list[bytes | None]]:
    """
    Extract template components, resolve leaflet references, and build
    the comparison_data dict ready for run_ai_audit.
    Returns (comparison_data, dma_image_urls, dma_image_bytes_list).
    """
    tmpl_body, tmpl_footer, tmpl_buttons = "", "", []
    dma_carousel_texts: list[str] = []
    dma_image_urls: list[str] = []

    # Step 1: check component_parameters for custom header image first
    for cp in api.get("component_parameters", []):
        if cp.get("type") == "header_image":
            url = cp.get("value")
            if url and str(url).startswith("http"):
                dma_image_urls.append(url)
            elif cp.get("source") == "leaflet_image_url":
                dma_image_urls.append("@leaflet_image_url")
            break

    # Step 2: carousel custom images
    api_custom_images = _collect_custom_carousel_images(api)
    if api_custom_images:
        dma_image_urls = [img for img in api_custom_images if img]

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

    # Resolve leaflet placeholders
    first_leaflet = leaflet_data[0] if leaflet_data else None
    if first_leaflet:
        l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
        l_img = first_leaflet.get("document_url") or first_leaflet.get("image_url")
        if l_url:
            dma_image_urls = [l_img if u == "@leaflet_image_url" else u for u in dma_image_urls]

    # Tag summary
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
            tag_parts.append(f"[{mode}] {key_name}={val}")

    api_urls = extract_api_urls_advanced(api)
    if tmpl:
        api_urls += extract_urls(str(tmpl))
    if first_leaflet:
        l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
        if l_url:
            api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]

    # Kaufland RCS Sunday: add RCS card texts and expected static texts
    rcs_cards_bv = (api.get("google_rcs_content", {})
                       .get("richCard", {})
                       .get("carouselCard", {})
                       .get("cardContents", []))
    if rcs_cards_bv:
        for ci, rcs_card in enumerate(rcs_cards_bv):
            title = rcs_card.get("title", f"Card {ci+1}")
            desc  = rcs_card.get("description", "")
            btn   = next((s.get("action", {}).get("text", "")
                          for s in rcs_card.get("suggestions", [])), "")
            dma_carousel_texts.append(f"Card {ci+1} Title: '{title}' | Body: '{desc}' | Button: {btn}")

        # Inject expected static texts for Sunday sendouts
        from datetime import datetime as _dt_bv
        try:
            _is_sun_bv = _dt_bv.fromisoformat(
                api.get("scheduled_date","").replace("Z","+00:00")
            ).weekday() == 6
        except Exception:
            _is_sun_bv = False
        if _is_sun_bv and client == "Kaufland RCS":
            static_bv = CLIENT_CONFIGS.get("Kaufland RCS", {}).get("sunday_rcs_cards", [])
            if static_bv:
                expected_texts = " | ".join(
                    f"Card {i+1}: Title='{c['title']}' Body='{c['body'][:80]}...' Button='{c['button']}'"
                    for i, c in enumerate(static_bv)
                )
                jira = dict(jira)
                jira["description"] = f"[STATIC RCS TEMPLATE] Expected card texts:\n{expected_texts}"

        # Kaufland WABA Sunday: inject expected static carousel card body text
        if client == "Kaufland WABA" and not jira.get("description"):
            _WABA_BODY = (
                "Hier findest du unseren aktuellen Prospekt mit den Angeboten vom {{1}} \u2013 {{2}} "
                "f\u00fcr deine Filiale in {{3}} {{4}} \u2b07\ufe0f"
            )
            jira = dict(jira)
            jira["description"] = (
                f"[STATIC WABA CAROUSEL TEMPLATE] Both carousel cards use this body text:\n"
                f"{_WABA_BODY}\n"
                f"Card 1: leaflet_type=special, offset_days=1 | Card 2: leaflet_type=regular, offset_days=4"
            )

    comparison_data = build_comparison_data(
        jira=jira,
        tmpl_body=tmpl_body,
        tmpl_footer=tmpl_footer,
        tmpl_buttons=tmpl_buttons,
        dma_carousel_texts=dma_carousel_texts,
        api_tag_str=", ".join(tag_parts),
        api_urls=[u for u in api_urls if "{{" not in u],  # strip template placeholders
        client_name=client,
        api_date=str(api.get("scheduled_date", "")),
    )

    dma_image_bytes = [fetch_dma_image_bytes(u) for u in dma_image_urls if u]
    return comparison_data, dma_image_urls, dma_image_bytes


def _collect_custom_carousel_images(api_data) -> list[str | None]:
    images: list[str | None] = []

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



def _run_regular_check(
    j_data: dict,
    a_data: dict,
    t_data: dict | None,
    leaflet_data: list,
    client: str,
) -> tuple[list[dict], int]:
    """
    Run the same deterministic checks shown in the individual validator
    (account routing, text similarity, footer, button, URLs, tags, filters).
    Returns (checks, issues_count) where checks is a list of
    {"label": str, "ok": bool, "detail": str} dicts.
    """
    checks: list[dict] = []

    def _chk(label: str, ok: bool, detail: str = "") -> None:
        checks.append({"label": label, "ok": ok, "detail": detail})

    # ── Account routing ──
    expected_acc = CLIENT_CONFIGS.get(client, {}).get("account_id")
    actual_acc   = a_data.get("account_id")
    if expected_acc is not None:
        acc_ok = int(expected_acc) == int(actual_acc) if actual_acc is not None else False
        _chk("Account routing", acc_ok,
             f"Expected {expected_acc} → Got {actual_acc}")

    # ── Text similarity ──
    # Use parsed carousel intro if available (avoids comparing slide structure)
    _raw_desc = str(j_data.get("description", "")).replace("\r", "").strip()
    _parsed_carousel = j_data.get("parsed_carousel")
    if _parsed_carousel and _parsed_carousel.get("intro"):
        jira_desc = _parsed_carousel["intro"].strip()
    else:
        jira_desc = _strip_slide_labels(_raw_desc)
    tmpl_body = ""
    tmpl_footer = ""
    tmpl_buttons: list[str] = []
    if t_data:
        for comp in t_data.get("components", []):
            if comp["type"] == "BODY":
                tmpl_body = comp.get("text", "")
            elif comp["type"] == "FOOTER":
                tmpl_footer = comp.get("text", "")
            elif comp["type"] == "BUTTONS":
                tmpl_buttons = [b.get("text", "") for b in comp.get("buttons", [])]

    if tmpl_body:
        # Kaufland RCS: Sunday = fully static, Wednesday = card 2 has JIRA-specific text
        if client == "Kaufland RCS":
            from datetime import datetime as _dt_rcs
            try:
                _rcs_date = str(a_data.get("scheduled_date","")).replace("Z","+00:00")
                _is_sun_rcs = _dt_rcs.fromisoformat(_rcs_date).weekday() == 6
            except Exception:
                _is_sun_rcs = False

            if _is_sun_rcs or not jira_desc:
                _chk("Text similarity", True, "Static RCS template — no JIRA description required")
            else:
                # Wednesday: Card 2 has ticket-specific promotional text from JIRA
                rcs_cards = (a_data.get("google_rcs_content", {})
                               .get("richCard", {})
                               .get("carouselCard", {})
                               .get("cardContents", []))
                if len(rcs_cards) >= 2:
                    card2_desc = rcs_cards[1].get("description", "")
                    if card2_desc and jira_desc:
                        sim = difflib.SequenceMatcher(None, jira_desc, card2_desc).ratio()
                        _chk("Card 2 text (JIRA vs RCS)",
                             sim > 0.85,
                             f"{int(sim*100)}% match")
                    else:
                        _chk("Text similarity", True, "Card 1 is static leaflet card — Card 2 checked separately")
        # Kaufland WABA: carousel body text is per-card dynamic (no top-level body to compare)
        elif client == "Kaufland WABA":
            _chk("Text similarity", True, "Carousel template — per-card dynamic body, no comparison needed")
            # If 3 cards: Card 3 has a custom image and optional body text from JIRA
            api_cards = []
            for cp in a_data.get("component_parameters", []):
                if isinstance(cp, dict) and cp.get("source") == "custom_cards":
                    api_cards = cp.get("cards", [])
                    break
            if len(api_cards) == 3 and t_data:
                # Get template card 3 body
                tmpl_cards = next(
                    (c.get("cards", []) for c in t_data.get("components", [])
                     if c.get("type") == "CAROUSEL"), []
                )
                tmpl_card3_body = ""
                if len(tmpl_cards) >= 3:
                    for cc in tmpl_cards[2].get("components", []):
                        if cc.get("type") == "BODY":
                            tmpl_card3_body = cc.get("text", "")
                            break
                # Get JIRA card 3 body from parsed carousel
                jira_card3_body = ""
                pc = j_data.get("parsed_carousel") or {}
                if pc.get("cards") and len(pc["cards"]) >= 3:
                    jira_card3_body = pc["cards"][2].get("body", "")
                if tmpl_card3_body and jira_card3_body:
                    sim3 = difflib.SequenceMatcher(None, jira_card3_body, tmpl_card3_body).ratio()
                    _chk("Card 3 text",
                         sim3 > 0.85,
                         f"{int(sim3*100)}% match")
        # Custom-cards carousel (Netto etc): no top-level body to compare
        elif any(
            cp.get("source") == "custom_cards"
            for cp in a_data.get("component_parameters", [])
            if isinstance(cp, dict)
        ):
            _chk("Text similarity", True, "Custom-cards carousel — per-card body, no text comparison")
            # Check card count: JIRA attachments (carousel images) vs API custom cards
            # Check card count: count slide labels in JIRA description vs API custom cards
            api_custom_cards = []
            for cp in a_data.get("component_parameters", []):
                if isinstance(cp, dict) and cp.get("source") == "custom_cards":
                    api_custom_cards = cp.get("cards", [])
                    break
            api_custom_img_cards = [
                card for card in api_custom_cards
                if any(
                    p.get("type") == "header_image" and p.get("source") == "custom"
                    for p in card.get("component_parameters", [])
                )
            ]
            if api_custom_img_cards:
                import re as _re2
                # Count slide labels in JIRA description e.g. "1. Slide:", "* 2. Slide:", "Slide 3:"
                slide_matches = _re2.findall(
                    r'(?im)(?:^[\s*]*\d+[\.\)]\s*Slide[:\s]|^[\s*]*Slide\s*\d+\s*:)',
                    str(j_data.get("description", ""))
                )
                # Also count from parsed carousel (Penny AT uses Card N: format)
                parsed_cards = (j_data.get("parsed_carousel") or {}).get("cards", [])
                jira_slide_count = len(slide_matches) or len(parsed_cards)
                api_card_count = len(api_custom_img_cards)
                if jira_slide_count > 0:
                    card_ok = jira_slide_count == api_card_count
                    _chk("Card count",
                         card_ok,
                         f"JIRA has {jira_slide_count} card(s), API has {api_card_count} custom card(s)")
                else:
                    # Fall back to attachment count if no slide labels found
                    jira_images = j_data.get("carousel_images") or []
                    card_ok = len(jira_images) == api_card_count
                    _chk("Card count",
                         card_ok,
                         f"JIRA has {len(jira_images)} attachment(s), API has {api_card_count} custom card(s)")
        elif not jira_desc:
            _chk("Text similarity", True, "No JIRA description — skipped")
        else:
            sim = difflib.SequenceMatcher(None, jira_desc, tmpl_body).ratio()
            _chk("Text similarity",
                 sim > 0.85,
                 f"{int(sim * 100)}% match")

    # ── Footer ──
    if t_data:
        jira_footer = str(j_data.get("footer_text", "") or "")
        # PASS if JIRA has no footer (DMA may add a default)
        # FAIL only if JIRA specifies footer but DMA is missing it
        if not jira_footer.strip():
            footer_ok = True
        else:
            footer_ok = jira_footer == tmpl_footer
        _chk("Footer", footer_ok,
             f'JIRA: "{jira_footer[:60]}" → API: "{tmpl_footer[:60]}"')

    # ── CTA button ──
    if tmpl_buttons:
        jira_btn = clean_button_text(str(j_data.get("cta_button", "") or ""))
        api_btns = [clean_button_text(b) for b in tmpl_buttons]
        btn_ok = jira_btn in api_btns
        _chk("CTA button", btn_ok,
             f'JIRA: "{j_data.get("cta_button", "")}" | API: {tmpl_buttons}')

    # ── URL matching ──
    # Use full raw description for URL extraction (not just intro)
    jira_all_text = " ".join(filter(None, [
        _raw_desc,  # full description including card sections for URLs
        str(j_data.get("additional_comments", "") or ""),
        str(j_data.get("cta_link", "") or ""),
    ]))
    jira_urls = [u for u in extract_urls(jira_all_text) if not is_media_url(u)]
    api_urls  = [u for u in (
        extract_api_urls_advanced(a_data) + (extract_urls(str(t_data)) if t_data else [])
    ) if not is_media_url(u) and "{{" not in u]

    # resolve leaflet
    if leaflet_data:
        l_url = leaflet_data[0].get("public_url") or leaflet_data[0].get("url", "")
        if l_url:
            api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]

    missing_urls = [u for u in jira_urls if not any(compare_urls_smart(u, a) for a in api_urls)]
    _chk("URLs present", len(missing_urls) == 0,
         f"Missing: {missing_urls}" if missing_urls else f"{len(jira_urls)} URL(s) matched")

    # ── Tags / filters — using shared check_tags logic ──
    from utils import check_tags as _check_tags
    tag_result = _check_tags(j_data, a_data, client)

    if tag_result["expected_excl"]:
        _chk("Exclude tags", len(tag_result["missing_excl"]) == 0,
             f"Missing: {tag_result['missing_excl']}" if tag_result["missing_excl"] else "All excludes present")

    if tag_result["expected_incl"]:
        _chk("Include tags", len(tag_result["missing_incl"]) == 0,
             f"Missing: {tag_result['missing_incl']}" if tag_result["missing_incl"] else "All includes present")

    # ── Client-specific filters ──
    if tag_result["expected_filters"]:
        _chk("Client filters", len(tag_result["missing_filters"]) == 0,
             f"Missing: {tag_result['missing_filters']}" if tag_result["missing_filters"] else "All filters present")

    issues = sum(1 for c in checks if not c["ok"])
    return checks, issues


def _run_date_check(j_data: dict, a_data: dict) -> dict:
    """Run scheduled date validation — same as single check."""
    return validate_scheduled_date(j_data, a_data)


def _run_url_reachability(j_data: dict, a_data: dict, leaflet_data: list) -> list[dict]:
    """Run URL reachability check — same as single check."""
    jira_urls = extract_urls(str(j_data.get("description", "")) + " " +
                             str(j_data.get("cta_link", "") or "") + " " +
                             str(j_data.get("additional_comments", "") or ""))
    api_urls  = extract_api_urls_advanced(a_data)
    if leaflet_data:
        l_url = leaflet_data[0].get("public_url") or leaflet_data[0].get("url", "")
        if l_url:
            api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]
    all_urls = list(dict.fromkeys([u for u in jira_urls + api_urls
                                   if u.startswith("http") and not is_media_url(u)]))
    if not all_urls:
        return []
    return check_url_reachability(all_urls)


def _filter_matches_bulk(expected: dict, actual: dict) -> bool:
    """Match expected filter against actual API filter dict.
    Handles tag-style {"name":"leaflet_type","value":"regular"} as well as
    type-style {"type":"tag","name":"leaflet_type","value":"regular"}.
    The "type"="tag" field in expected is metadata about filter kind,
    not a field that must exist in the actual API dict.
    """
    # Fast path: name+value match (works for both tag styles)
    exp_name = expected.get("name")
    exp_val  = str(expected.get("value", ""))
    if exp_name and exp_val and expected.get("mode") != "exclude":
        if actual.get("name") == exp_name and str(actual.get("value", "")) == exp_val:
            return True

    # leaflet_tag offset_days match
    if expected.get("type") == "leaflet_tag" and expected.get("offset_days") is not None:
        if (actual.get("type") == "leaflet_tag" and
                str(actual.get("offset_days", "")) == str(expected["offset_days"])):
            return True

    for k, v in expected.items():
        if k == "mode":
            if v == "exclude":
                if actual.get("exclude_value") != expected.get("value"):
                    return False
            # "include" mode — presence check done above
        elif k == "type" and v == "tag":
            # "type":"tag" is a category label, not a field in the actual dict
            pass
        elif k == "type" and v == "leaflet_tag":
            pass  # handled above
        elif k in actual:
            if str(actual.get(k, "")) != str(v):
                return False
        elif k == "values":
            actual_val = actual.get("value") or actual.get("shop_number") or ""
            if isinstance(v, list) and str(actual_val) not in [str(x) for x in v]:
                return False
        elif k not in {"name", "value", "values", "shop_number", "locale", "type", "mode", "offset_days"}:
            return False
    return True


def _fetch_and_enrich(
    ticket_key: str,
    client: str,
    gsheet_data: list[dict],
    jira_server: str,
    jira_email: str,
    jira_token: str,
    api_token: str,
) -> tuple[dict, dict, dict | None, list]:
    """Shared fetch logic for both bulk modes. Raises RuntimeError on failure."""
    j_data = fetch_ticket_data(jira_server, jira_email, jira_token, ticket_key)
    if not j_data:
        raise RuntimeError("JIRA fetch returned no data.")

    jira_date    = str(j_data.get("date", ""))
    # Combine summary + segment for ALDI Sued segment-aware matching
    jira_summary = str(j_data.get("summary", ""))
    jira_segment = str(j_data.get("segment", ""))
    if jira_segment and jira_segment.lower() not in jira_summary.lower():
        jira_summary = f"{jira_summary} {jira_segment}".strip()

    # Also extract segment from "WhatsApp Chat Prospekt X" ticket naming
    import re as _re_seg
    _prospekt_m = _re_seg.search(r'(?i)chat prospekt\s+(\w+)', jira_summary)
    if _prospekt_m and not jira_segment:
        jira_segment = _prospekt_m.group(1)
        j_data["segment"] = jira_segment
    sendout_id   = _find_sendout_id(ticket_key, client, gsheet_data,
                                     api_token=api_token, jira_date=jira_date,
                                     jira_summary=jira_summary)
    if not sendout_id:
        raise RuntimeError("No matching Sendout ID found (DMA API or G-Sheet).")

    a_data = fetch_api_data(api_token, sendout_id)
    if not a_data or "error_code" in a_data:
        err = a_data or {}
        raise RuntimeError(f"API fetch failed ({err.get('error_code')}): {err.get('error_msg')}")

    # Enrich from G-Sheet — match by JIRA link AND date
    # Use the DMA API scheduled_date (authoritative) for date matching
    matched_gsheet_row: dict = {}
    schedule = get_client_schedule(gsheet_data, client)
    api_date_short  = str(a_data.get("scheduled_date", ""))[:10]   # from DMA API (authoritative)
    jira_date_short = str(j_data.get("date", ""))[:10]             # from JIRA ticket

    def _row_matches_date(row, date_str):
        """Compare row date (DD/MM/YYYY or YYYY-MM-DD) against date_str (YYYY-MM-DD)."""
        if not date_str:
            return False
        raw = str(row.get(GSHEET_COLS["date"], "")).strip()[:10]
        if not raw:
            return False
        # Normalise DD/MM/YYYY -> YYYY-MM-DD
        if len(raw) == 10 and raw[2] == "/" and raw[5] == "/":
            raw = f"{raw[6:10]}-{raw[3:5]}-{raw[0:2]}"
        return raw == date_str[:10]

    # Collect all candidate rows (ticket key + date match)
    candidate_rows = []
    for row in schedule:
        if ticket_key in str(row.get(GSHEET_COLS["jira_link"], "")) and \
                _row_matches_date(row, api_date_short):
            candidate_rows.append(row)
    if not candidate_rows and jira_date_short != api_date_short:
        for row in schedule:
            if ticket_key in str(row.get(GSHEET_COLS["jira_link"], "")) and \
                    _row_matches_date(row, jira_date_short):
                candidate_rows.append(row)
    if not candidate_rows:
        for row in schedule:
            if ticket_key in str(row.get(GSHEET_COLS["jira_link"], "")):
                candidate_rows.append(row)

    def _best_gsheet_row(rows, jira_segment=""):
        """Pick the correct G-Sheet row using JIRA segment field (primary) for ALDI Sued.
        
        G-Sheet rows: ALDI Sud Regular Sendout | Familien Segment | Elektronik Segment | Garten Segment
        JIRA segment field drives which row to use — DMA task name is NOT used for this.
        """
        if not rows:
            return None
        import re as _re_gs

        if jira_segment:
            from config import CLIENT_CONFIGS as _CC_gs
            _maps = _CC_gs.get("ALDI Sued", {}).get("mappings", {})

            # Resolve JIRA segment display name → canonical DMA keyword
            canonical = None
            seg_lower = jira_segment.lower()
            for md in _maps.values():
                for display, kw in md.items():
                    if display.lower() in seg_lower or kw.lower() in seg_lower:
                        canonical = kw.lower()
                        break
                if canonical:
                    break

            # Also try matching raw segment words directly against G-Sheet row client name
            seg_words = {w.lower() for w in _re_gs.split(r'[\s/(),]+', jira_segment) if len(w) > 3}

            if canonical:
                for row in rows:
                    if canonical in str(row.get(GSHEET_COLS["client"], "")).lower():
                        return row

            if seg_words:
                for row in rows:
                    row_client = str(row.get(GSHEET_COLS["client"], "")).lower()
                    if any(w in row_client for w in seg_words):
                        return row

        # No segment or no match → Regular Sendout row
        for row in rows:
            if any(w in str(row.get(GSHEET_COLS["client"], "")).lower()
                   for w in ("regular", "standard")):
                return row

        return rows[0]

    # For multi-segment clients (ALDI Sued), G-Sheet row is driven by JIRA segment only
    _jira_segment  = str(j_data.get("segment", "") or "")
    _is_multi_segment = client in ("ALDI Sued",)

    if len(candidate_rows) == 1 and not _is_multi_segment:
        matched_gsheet_row = dict(candidate_rows[0])
    elif candidate_rows:
        best = _best_gsheet_row(candidate_rows, _jira_segment)
        matched_gsheet_row = dict(best) if best else dict(candidate_rows[0])

    if matched_gsheet_row:
        for key, col in (("leaflet_url", GSHEET_COLS["leaflet"]),
                         ("gsheet_tags", GSHEET_COLS["include_tags"]),
                         ("gsheet_exclude_tags", GSHEET_COLS["exclude_tags"])):
            val = str(matched_gsheet_row.get(col, "")).replace("nan", "").strip()
            if val:
                j_data[key] = val

    j_data["parsed_carousel"] = pick_carousel_parser(
        str(j_data.get("description", "")), client
    )

    # Ensure timezone is set — use JIRA field if available, otherwise client config
    if not j_data.get("timezone"):
        j_data["timezone"] = CLIENT_CONFIGS.get(client, {}).get("timezone_name", "Europe/Berlin")
    # DMA stores times in client's local timezone (labeled as Z)
    # ALDI Portugal: Europe/Lisbon. All others: Europe/Berlin (CET)
    j_data["_client_timezone"] = "Europe/Lisbon" if client == "ALDI Portugal" else "Europe/Berlin"

    t_name   = a_data.get("template_name") or (a_data.get("template") or {}).get("name")
    waba_key = fetch_api_key_via_dma(api_token, a_data.get("account_id"))
    t_data   = fetch_template_data(waba_key, t_name) if (t_name and waba_key) else None

    leaflet_data: list[dict] = []
    has_leaflet = (
        "leaflet" in str(a_data.get("component_parameters", []))
        or isinstance(a_data.get("leaflet_filter"), dict)
        or "leaflet" in str(a_data.get("google_rcs_content", ""))
    )
    if has_leaflet:
        leaflet_data = fetch_account_leaflets(
            api_token, a_data.get("account_id"), a_data.get("scheduled_date", "")
        )

    return j_data, a_data, t_data, leaflet_data, matched_gsheet_row


def _validate_single_ticket_regular(
    issue, gsheet_data, jira_server, jira_email, jira_token, api_token,
) -> BulkTicketResult:
    """Validate one ticket in regular (non-AI) mode — thread-safe."""
    ticket_key   = issue["key"]
    client       = _detect_client(issue)
    jira_date    = str(issue["fields"].get("customfield_12665", ""))
    jira_summary = str(issue["fields"].get("summary", ""))

    # Append ALDI Sued segment field (customfield_14287) for segment-aware task matching
    _raw_seg = issue["fields"].get("customfield_14287")
    if _raw_seg:
        jira_segment = _raw_seg.get("value", "") if isinstance(_raw_seg, dict) else str(_raw_seg)
        if jira_segment and jira_segment.lower() not in jira_summary.lower():
            jira_summary = f"{jira_summary} {jira_segment}".strip()

    sendout_id   = _find_sendout_id(ticket_key, client, gsheet_data,
                                     api_token=api_token, jira_date=jira_date,
                                     jira_summary=jira_summary)

    result = BulkTicketResult(
        ticket_key=ticket_key,
        client=client,
        sendout_id=sendout_id,
        mode="regular",
    )

    if not sendout_id:
        result.status    = "skipped"
        result.error_msg = "No matching Sendout ID found (DMA API or G-Sheet)."
        return result

    try:
        j_data, a_data, t_data, leaflet_data, gsheet_row = _fetch_and_enrich(
            ticket_key, client, gsheet_data,
            jira_server, jira_email, jira_token, api_token
        )
        result.sendout_name = str(a_data.get("name") or a_data.get("campaign_name") or "")
        result.sendout_date = str(a_data.get("scheduled_date", ""))[:16]
        result.gsheet_row   = gsheet_row

        checks, issues = _run_regular_check(j_data, a_data, t_data, leaflet_data, client)

        date_result = _run_date_check(j_data, a_data)
        date_ok = date_result.get("ok", False) or not date_result.get("jira_raw")
        checks.append({"label": "Scheduled date", "ok": date_ok,
                       "detail": date_result.get("detail", "")})
        if not date_ok:
            issues += 1

        result.checks       = checks
        result.issues_found = issues
        result.status       = "failed" if issues > 0 else "passed"
        result.api_payload  = a_data
        result.report       = "\n".join(
            f"{'✅' if c['ok'] else '❌'} {c['label']}: {c['detail']}"
            for c in checks
        )

    except Exception as exc:
        logger.error("Bulk regular check error for %s: %s", ticket_key, exc)
        result.status    = "error"
        result.error_msg = str(exc)

    return result


def run_bulk_regular_check(
    tickets: list[dict],
    gsheet_data: list[dict],
    jira_server: str,
    jira_email: str,
    jira_token: str,
    api_token: str,
    on_progress,
    max_workers: int = 10,
) -> list[BulkTicketResult]:
    """
    Run deterministic (non-AI) checks in parallel.
    Higher worker count than AI mode — no rate limits on internal APIs.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[BulkTicketResult] = []
    total = len(tickets)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _validate_single_ticket_regular,
                issue, gsheet_data, jira_server, jira_email, jira_token, api_token,
            ): issue["key"]
            for issue in tickets
        }

        completed = 0
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                ticket_key = futures[future]
                logger.error("Regular worker failed for %s: %s", ticket_key, exc)
                result = BulkTicketResult(
                    ticket_key=ticket_key, mode="regular", status="error",
                    error_msg=str(exc),
                )
            results.append(result)
            on_progress(result, completed, total)
            completed += 1

    return results

def _validate_single_ticket_ai(
    issue, gsheet_data, jira_server, jira_email, jira_token, api_token,
    gemini_key, gemini_model,
) -> BulkTicketResult:
    """Validate one ticket in AI mode — thread-safe, returns result."""
    ticket_key   = issue["key"]
    client       = _detect_client(issue)
    jira_date    = str(issue["fields"].get("customfield_12665", ""))
    jira_summary = str(issue["fields"].get("summary", ""))

    # Append ALDI Sued segment field (customfield_14287) for segment-aware task matching
    _raw_seg = issue["fields"].get("customfield_14287")
    if _raw_seg:
        jira_segment = _raw_seg.get("value", "") if isinstance(_raw_seg, dict) else str(_raw_seg)
        if jira_segment and jira_segment.lower() not in jira_summary.lower():
            jira_summary = f"{jira_summary} {jira_segment}".strip()

    sendout_id   = _find_sendout_id(ticket_key, client, gsheet_data,
                                     api_token=api_token, jira_date=jira_date,
                                     jira_summary=jira_summary)

    result = BulkTicketResult(
        ticket_key=ticket_key,
        client=client,
        sendout_id=sendout_id,
        mode="ai",
    )

    if not sendout_id:
        result.status    = "skipped"
        result.error_msg = "No matching Sendout ID found (DMA API or G-Sheet)."
        return result

    result.status = "running"

    try:
        j_data, a_data, t_data, leaflet_data, gsheet_row = _fetch_and_enrich(
            ticket_key, client, gsheet_data,
            jira_server, jira_email, jira_token, api_token
        )
        result.sendout_name = str(a_data.get("name") or a_data.get("campaign_name") or "")
        result.sendout_date = str(a_data.get("scheduled_date", ""))[:16]
        result.gsheet_row   = gsheet_row

        comparison_data, _dma_urls, dma_bytes = _build_audit_payload(
            j_data, a_data, t_data, leaflet_data, client
        )

        audit = run_ai_audit(
            gemini_key, gemini_model, comparison_data, client,
            jira_images=None,
            dma_images=None,
        )

        report = audit.get("audit_report", "")
        result.report    = report
        result.jira_urls = audit.get("jira_extracted_urls", [])
        result.api_urls  = audit.get("api_extracted_urls", [])
        result.api_payload = a_data

        if audit.get("error") or _is_audit_error(report):
            result.status    = "error"
            result.error_msg = report
        else:
            result.issues_found = report.count("❌")
            result.confidence   = int(audit.get("confidence", -1))
            result.confidence_reason = str(audit.get("confidence_reason", ""))
            result.status = "failed" if result.issues_found > 0 else "passed"

            jira_status = "Rejected" if result.issues_found > 0 else "Approved"
            write_ai_status_to_jira(jira_server, jira_email, jira_token, ticket_key, jira_status)

    except Exception as exc:
        logger.error("Bulk validation error for %s: %s", ticket_key, exc)
        result.status    = "error"
        result.error_msg = str(exc)

    return result


def run_bulk_validation(
    tickets: list[dict],
    gsheet_data: list[dict],
    jira_server: str,
    jira_email: str,
    jira_token: str,
    api_token: str,
    gemini_key: str,
    gemini_model: str,
    on_progress,
    max_workers: int = 5,
) -> list[BulkTicketResult]:
    """
    Validate tickets in parallel using a thread pool.
    Calls on_progress(result, i, total) as each ticket completes.
    Default 5 workers respects Gemini rate limits (~60 req/min).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[BulkTicketResult] = []
    total = len(tickets)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _validate_single_ticket_ai,
                issue, gsheet_data, jira_server, jira_email, jira_token,
                api_token, gemini_key, gemini_model,
            ): issue["key"]
            for issue in tickets
        }

        completed = 0
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                ticket_key = futures[future]
                logger.error("Worker failed for %s: %s", ticket_key, exc)
                result = BulkTicketResult(
                    ticket_key=ticket_key, mode="ai", status="error",
                    error_msg=str(exc),
                )
            results.append(result)
            on_progress(result, completed, total)
            completed += 1

    return results

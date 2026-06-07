"""
audit_prep.py — Shared DMA component extractor
================================================
Single authoritative function for pulling template body/footer/buttons,
carousel texts, image URLs, tag strings, and API URLs out of the raw
DMA API payload + WABA template.

Previously this logic was duplicated between:
  • server.py  :: _prepare_audit_data()   (single-ticket check)
  • bulk_validator.py :: _build_audit_payload()  (bulk AI check)

Any new DMA structure support belongs HERE only.  Both callers are thin
wrappers that pass the returned dict to build_comparison_data().
"""

import logging
import re
from urllib.parse import urlparse

from config import CLIENT_CONFIGS
from utils import extract_all_tags, extract_urls, extract_api_urls_advanced

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_tag_str(s: str) -> str:
    """Normalise a tag k=v string: strip extra spaces around '='."""
    _EMPTY = {"none", "n/a", "-", "", "null"}
    parts = re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p and p.lower() not in _EMPTY:
            cleaned.append(p)
    return ", ".join(cleaned)


def _collect_custom_carousel_images(api_data: dict) -> list:
    """
    Walk the DMA API payload and return one image URL (or None) per carousel card.
    Handles both API-style (component_parameters / header_image) and
    template-style (components / HEADER) card structures.
    """
    images: list = []

    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "carousel" and "cards" in obj:
                for card in obj["cards"]:
                    found = None
                    # API-style: component_parameters → header_image
                    for cp in card.get("component_parameters", []):
                        if cp.get("type") == "header_image" and cp.get("value"):
                            found = cp["value"]
                            break
                    # Template-style fallback: components → HEADER IMAGE
                    if not found:
                        for comp in card.get("components", []):
                            if comp.get("type") == "HEADER" and comp.get("format") == "IMAGE":
                                handles = comp.get("example", {}).get("header_handle", [])
                                if handles:
                                    found = handles[0]
                                    break
                    images.append(found)
                return  # don't recurse into cards we already processed
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(api_data)
    return images


def _normalise_api_urls(api_urls: list[str]) -> list[str]:
    """Replace {{N}} template-variable URLs with their base path; drop pure-variable ones."""
    try:
        from ai_audit import _tmpl_url_base as _tub
    except ImportError:
        return api_urls

    out: list[str] = []
    for u in api_urls:
        if "{{" in u:
            base = _tub(u)
            if base:
                out.append(base)
        else:
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_dma_components(
    api: dict,
    tmpl: dict | None,
    leaflet_data: list[dict],
    jira: dict,
    client: str,
) -> dict:
    """
    Extract all DMA payload components needed for an AI audit.

    Parameters
    ----------
    api         : raw DMA API task dict
    tmpl        : WABA template dict (or None for RCS / no-template sendouts)
    leaflet_data: list of leaflet dicts from fetch_account_leaflets
    jira        : enriched JIRA ticket dict from fetch_ticket_data
    client      : display client name (e.g. "Kaufland RCS")

    Returns
    -------
    dict with keys:
        tmpl_body, tmpl_footer, tmpl_buttons   – strings / list[str]
        dma_carousel_texts                      – list[str]  (one entry per card)
        dma_image_urls                          – list[str]  (one URL per card)
        tag_str                                 – comma-separated tag summary
        api_urls                                – list[str]  (normalised)
        rcs_cards                               – raw list of RCS cardContent dicts
        jira                                    – may be modified (static templates)
        api_custom_images                       – raw result of _collect_custom_carousel_images
        leaflet_img_url                         – first leaflet image URL (or "")
    """
    tmpl_body: str = ""
    tmpl_footer: str = ""
    tmpl_buttons: list[str] = []
    dma_carousel_texts: list[str] = []
    dma_image_urls: list[str] = []
    api_urls: list[str] = []  # initialised early so standalone-card section can append

    # ── Debug logging ──────────────────────────────────────────────────────
    _cp_types   = [cp.get("type") for cp in (api.get("component_parameters") or [])]
    _tmpl_types = [c.get("type")  for c in  (tmpl.get("components") or [])] if tmpl else []
    logger.info(
        "extract_dma_components [%s]: cp_types=%s  tmpl_types=%s",
        client, _cp_types, _tmpl_types,
    )

    # ── 1. Single top-level header image ──────────────────────────────────
    for cp in api.get("component_parameters", []):
        if cp.get("type") == "header_image":
            url = cp.get("value")
            if url and str(url).startswith("http"):
                dma_image_urls.append(url)
            elif cp.get("source") == "leaflet_image_url":
                dma_image_urls.append("@leaflet_image_url")
            break  # only one top-level header

    # ── 2. Carousel custom images (overrides single header if present) ────
    api_custom_images = _collect_custom_carousel_images(api)
    if api_custom_images:
        dma_image_urls = [img for img in api_custom_images if img]

    # ── 3. RCS standaloneCard ─────────────────────────────────────────────
    _rcs_rich   = api.get("google_rcs_content", {}).get("richCard", {})
    _standalone = _rcs_rich.get("standaloneCard", {}).get("cardContent", {})
    if _standalone:
        _sc_title = _standalone.get("title", "")
        _sc_desc  = _standalone.get("description", "")
        _sc_img   = (
            _standalone.get("media", {})
                       .get("contentInfo", {})
                       .get("fileUrl", "")
        )
        _sc_btn = next(
            (s.get("action", {}).get("text", "")
             for s in _standalone.get("suggestions", [])), ""
        )
        _sc_url = next(
            (s.get("action", {}).get("openUrlAction", {}).get("url", "")
             for s in _standalone.get("suggestions", [])), ""
        )
        if not tmpl_body:
            tmpl_body = "\n".join(filter(None, [_sc_title, _sc_desc]))
        if _sc_img and not dma_image_urls:
            dma_image_urls.append(_sc_img)
        if _sc_btn:
            tmpl_buttons.append(f"{_sc_btn} ({_sc_url})" if _sc_url else _sc_btn)
        if _sc_url and _sc_url not in api_urls:
            api_urls.append(_sc_url)

    # ── 4. RCS carouselCard ───────────────────────────────────────────────
    rcs_cards = _rcs_rich.get("carouselCard", {}).get("cardContents", [])
    if rcs_cards:
        # Build a leaflet-type → image-URL lookup for cards that reference leaflets
        leaflet_by_type: dict = {}
        for lf in (leaflet_data or []):
            lft = (lf.get("data") or {}).get("leaflet_type", "")
            if lft and lft not in leaflet_by_type:
                leaflet_by_type[lft] = lf.get("document_url") or lf.get("image_url", "")

        if not dma_image_urls:
            for ci, rcs_card in enumerate(rcs_cards):
                img_url = (
                    rcs_card.get("media", {})
                            .get("contentInfo", {})
                            .get("fileUrl", "")
                )
                if img_url and img_url.startswith("http"):
                    dma_image_urls.append(img_url)
                else:
                    card_lf = rcs_card.get("leaflet_filter", {})
                    lft = next(
                        (tg.get("value", "") for tg in card_lf.get("tags", [])
                         if tg.get("name") == "leaflet_type"), ""
                    )
                    fallback = (
                        leaflet_by_type.get(lft)
                        or (leaflet_by_type.get(list(leaflet_by_type.keys())[0], "")
                            if leaflet_by_type else "")
                    )
                    if fallback:
                        dma_image_urls.append(fallback)

        for ci, rcs_card in enumerate(rcs_cards):
            title = rcs_card.get("title", f"Card {ci+1}")
            desc  = rcs_card.get("description", "")
            btn   = next(
                (s.get("action", {}).get("text", "")
                 for s in rcs_card.get("suggestions", [])), ""
            )
            dma_carousel_texts.append(
                f"Card {ci+1} Title: '{title}' | Body: '{desc}' | Button: {btn}"
            )

    # ── 5. WABA template components ───────────────────────────────────────
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
                        if (cc.get("type") == "HEADER"
                                and cc.get("format") == "IMAGE"
                                and not api_custom_images):
                            url = cc.get("example", {}).get("header_handle", [None])[0]
                            if url:
                                dma_image_urls.append(url)
                        elif cc.get("type") == "BODY":
                            body = cc.get("text", "")
                        elif cc.get("type") == "BUTTONS":
                            btns = [b.get("text", "") for b in cc.get("buttons", [])]
                    dma_carousel_texts.append(
                        f"Card {ci+1} Body: '{body}' | Buttons: {btns}"
                    )

    # ── 6. Resolve leaflet placeholders ───────────────────────────────────
    first_leaflet = leaflet_data[0] if leaflet_data else None
    leaflet_img_url: str = ""
    if first_leaflet:
        l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
        l_img = first_leaflet.get("document_url") or first_leaflet.get("image_url") or ""
        leaflet_img_url = l_img
        if l_url:
            dma_image_urls = [l_img if u == "@leaflet_image_url" else u
                              for u in dma_image_urls]

    # ── 7. first_card_is_leaflet — prepend leaflet as DMA card 1 ─────────
    _cfg = CLIENT_CONFIGS.get(client, {})
    if _cfg.get("first_card_is_leaflet") and leaflet_img_url:
        dma_image_urls = [leaflet_img_url] + dma_image_urls

    # ── 8. Tag summary ────────────────────────────────────────────────────
    api_tags   = extract_all_tags(api)
    tag_parts: list[str] = []
    for tg in api_tags:
        key_name = tg.get("name") or tg.get("type") or "filter"
        raw_val  = (tg.get("value") or tg.get("exclude_value")
                    or tg.get("values") or tg.get("exclude_values")
                    or tg.get("offset_days") or "Active")
        val  = f"[{len(raw_val)} values]" if isinstance(raw_val, list) else str(raw_val)
        mode = ("Exclude"
                if ("exclude_value" in tg or "exclude_values" in tg
                    or tg.get("mode") == "exclude")
                else "Include")
        if tg.get("type") == "leaflet_tag" and tg.get("offset_days") is not None:
            od = tg.get("offset_days")
            tag_parts.append(f"[{mode}] leaflet_tag={od} (offset_days={od})")
        else:
            tag_parts.append(f"[{mode}] {_norm_tag_str(f'{key_name}={val}')}")

    # ── 9. URL list ───────────────────────────────────────────────────────
    api_urls = extract_api_urls_advanced(api)
    if tmpl:
        api_urls += extract_urls(str(tmpl))
    if first_leaflet:
        l_url = first_leaflet.get("public_url") or first_leaflet.get("url", "")
        if l_url:
            api_urls = [u.replace("@leaflet_url_path", l_url) for u in api_urls]

    # Resolve relative URLs to absolute using the JIRA-side base domain
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
            if (u and not u.startswith("http") and not u.startswith("@"))
            else u
            for u in api_urls
        ]

    # Normalise template-variable URLs ({{1}} → base path)
    api_urls = _normalise_api_urls(api_urls)

    # ── 10. JIRA carousel fallback ────────────────────────────────────────
    # Clients like Penny AT / ALDI Italy use DMA carousel structures our
    # detectors don't yet recognise.  When nothing was extracted, inject the
    # JIRA form cards as a reference so the AI knows it's auditing a carousel.
    if not dma_carousel_texts:
        _jc    = jira.get("parsed_carousel") or {}
        _cards = _jc.get("cards") if isinstance(_jc, dict) else None
        if _cards:
            logger.info(
                "extract_dma_components [%s]: DMA carousel not detected — "
                "using %d JIRA form cards as reference",
                client, len(_cards),
            )
            for i, card in enumerate(_cards):
                body = card.get("body") or card.get("text") or ""
                btns = card.get("buttons") or card.get("button") or ""
                dma_carousel_texts.append(
                    f"Card {i+1} [from JIRA form — DMA structure undetected]: '{body}'"
                    + (f" | Button: {btns}" if btns else "")
                )

    # ── 11. Client-specific static text injection ─────────────────────────
    # Kaufland RCS Sunday — override JIRA description with expected card texts
    if rcs_cards and client == "Kaufland RCS":
        from datetime import datetime as _dt
        try:
            _is_sun = _dt.fromisoformat(
                api.get("scheduled_date", "").replace("Z", "+00:00")
            ).weekday() == 6
        except Exception:
            _is_sun = False
        if _is_sun:
            static = _cfg.get("sunday_rcs_cards", [])
            if static:
                expected_texts = " | ".join(
                    f"Card {i+1}: Title='{c['title']}' Body='{c['body'][:80]}...' "
                    f"Button='{c['button']}'"
                    for i, c in enumerate(static)
                )
                jira = dict(jira)
                jira["description"] = (
                    f"[STATIC RCS TEMPLATE] Expected card texts:\n{expected_texts}"
                )

    # Kaufland WABA — inject static carousel body when JIRA has no description
    if client == "Kaufland WABA" and not jira.get("description"):
        _waba_body = _cfg.get("static_carousel_body", "")
        _waba_note = _cfg.get("static_carousel_note", "")
        if _waba_body:
            jira = dict(jira)
            jira["description"] = (
                "[STATIC WABA CAROUSEL TEMPLATE] Both carousel cards use this body text:\n"
                + _waba_body
                + (f"\n{_waba_note}" if _waba_note else "")
            )

    return {
        "tmpl_body":          tmpl_body,
        "tmpl_footer":        tmpl_footer,
        "tmpl_buttons":       tmpl_buttons,
        "dma_carousel_texts": dma_carousel_texts,
        "dma_image_urls":     dma_image_urls,
        "tag_str":            ", ".join(tag_parts),
        "api_urls":           api_urls,
        "rcs_cards":          rcs_cards,
        "jira":               jira,          # may be modified by static text injection
        "api_custom_images":  api_custom_images,
        "leaflet_img_url":    leaflet_img_url,
    }

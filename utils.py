"""
utils.py — Pure helper functions.
No Streamlit, no HTTP, no JIRA imports — fully unit-testable.
"""

import difflib
import json
import logging
import re
import string
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def clean_jira_markdown(text: str) -> str:
    """Strip basic Jira markdown decorators from a string."""
    if not text:
        return ""
    return text.replace("*", "").replace("_", "").strip()


def clean_button_text(text: str) -> str:
    """Normalise button labels for fuzzy comparison."""
    if not text:
        return ""
    return text.translate(str.maketrans("", "", string.punctuation)).strip().lower()


def normalize_nahkauf_placeholders(text: str) -> str:
    """Replace Nahkauf address placeholders with template tokens.
    XY-Straße, XY-Hausnr. -> {{1}}, {{2}}.  (dot preserved)
    """
    if not text:
        return ""
    def _rep(m):
        return "{{1}}, {{2}}" + (m.group(1) or "")
    return re.sub(
        r"XY-?_?Stra\u00dfe,\s*XY-Hausnr(\.?)",
        _rep,
        text,
        flags=re.IGNORECASE,
    )


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(https?://[^\s,\]\>]+)")
_MEDIA_EXTS = frozenset([".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"])

def _smart_rstrip(url: str) -> str:
    stripped = url.rstrip("'\")}.,;")
    # Restore }} if we broke a {{placeholder}}
    if "{{" in stripped and stripped.count("{{" ) > stripped.count("}}"):
        stripped = url.rstrip("'\".,:;")
    return stripped

def extract_urls(text: str) -> list[str]:
    """Return all HTTP(S) URLs found in *text*, trailing punctuation stripped."""
    if not text:
        return []
    return [_smart_rstrip(u) for u in _URL_RE.findall(str(text))]


def is_media_url(url: str) -> bool:
    """Return True when the URL clearly points to a media asset."""
    lower = url.lower()
    return any(ext in lower for ext in _MEDIA_EXTS) or "storage.googleapis" in lower


def normalize_nahkauf_url(url: str) -> str:
    """Canonicalise Nahkauf store-specific URLs to their template form."""
    if "bonialcampaigns.com" in url and "store_id" in url:
        return "https://bonialcampaigns.com/{{1}}"
    if "[Insert-Store-Id]" in url:
        return "https://bonialcampaigns.com/{{1}}"
    return url


def _canon_url(url: str) -> str:
    """Strip placeholder segments and query params for comparison."""
    from urllib.parse import urlparse, urlunparse
    u = url.strip()
    # Normalise all placeholder variants including {shop_number}
    for token in ("{{1}}", "%7B%7B1%7D%7D", "{shop_id}", "%7Bshop_id%7D",
                  "{{shop_id}}", "{shop_number}", "%7Bshop_number%7D"):
        u = u.replace(token, "__P__")
    u = re.sub(r"/__P__(?=/|$)", "", u)
    u = re.sub(r"__P__[^/]*", "", u)
    # Handle relative URLs (no scheme) - strip query string too
    if not u.startswith("http") and not u.startswith("//"):
        u = u.split("?")[0].split("#")[0].rstrip("/")
        return "//rel/" + u

    # Strip query string (ecid, utm params etc don't affect URL identity)
    try:
        parsed = urlparse(u)
        u = urlunparse(parsed._replace(query="", fragment=""))
    except Exception:
        pass
    return u.rstrip("/")


def compare_urls_smart(jira_url: str, api_url: str) -> bool:
    """
    Return True when jira_url and api_url refer to the same resource,
    accounting for {{1}} / {shop_id} placeholder variants and split URLs.
    """
    j = str(jira_url).strip()
    a = str(api_url).strip()

    if a == "@leaflet_url_path":
        return True

    if j == a:
        return True

    j_c = _canon_url(j)
    a_c = _canon_url(a)

    if j_c and a_c and j_c == a_c:
        return True

    if j_c and a_c and (j_c in a_c or a_c in j_c):
        return True

    # Match relative URL path against absolute URL path
    # e.g. "angebote/{shop_id}/?ecid=..." canon -> "//rel/angebote"
    # vs "https://rewe.de/angebote/" canon -> "https://rewe.de/angebote"
    try:
        j_is_rel = j_c.startswith("//rel/")
        a_is_rel = a_c.startswith("//rel/")
        if j_is_rel or a_is_rel:
            rel = (j_c if j_is_rel else a_c).replace("//rel/", "").strip("/")
            abs_path = urlparse(j_c if a_is_rel else a_c).path.strip("/")
            if rel and abs_path and (rel == abs_path or abs_path.endswith(rel) or rel.endswith(abs_path)):
                return True
    except Exception:
        pass

    try:
        j_p, a_p = urlparse(j), urlparse(a)
        if j_p.netloc and a_p.netloc and j_p.netloc != a_p.netloc:
            return False
        jpath = urlparse(j_c).path.rstrip("/")
        apath = urlparse(a_c).path.rstrip("/")
        if jpath and apath and jpath == apath:
            return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Deep-search helpers (shared traversal, used by api_client.py)
# ---------------------------------------------------------------------------

def deep_collect(obj, *, visitor) -> None:
    """
    Walk a nested dict/list structure, calling *visitor(node)* on every dict.
    Avoids re-implementing the traversal in four places.
    """
    if isinstance(obj, dict):
        visitor(obj)
        for v in obj.values():
            deep_collect(v, visitor=visitor)
    elif isinstance(obj, list):
        for item in obj:
            deep_collect(item, visitor=visitor)


def extract_api_urls_advanced(api_data) -> list[str]:
    """
    Extract all actionable URLs from a raw DMA API response,
    including button_cta values and leaflet source references.
    """
    from config import SOURCE_LEAFLET_URL, TYPE_BUTTON_CTA  # local import avoids circular deps

    urls: list[str] = extract_urls(str(api_data))

    def _visit(node: dict) -> None:
        if node.get("type") == TYPE_BUTTON_CTA:
            val = node.get("value")
            if isinstance(val, str) and val:
                # Keep both absolute and relative URLs
                urls.append(val)
            src = node.get("source")
            if isinstance(src, str):
                if src == SOURCE_LEAFLET_URL:
                    urls.append("@leaflet_url_path")
                elif src not in {"custom", "first_name", "shop_address", "shop_city"}:
                    urls.append(src)
        elif node.get("source") == SOURCE_LEAFLET_URL:
            urls.append("@leaflet_url_path")

    deep_collect(api_data, visitor=_visit)

    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        cleaned = str(u).rstrip("'\")}.,;")
        if cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    return sorted(unique)


def extract_all_tags(api_data) -> list[dict]:
    """Return a deduplicated list of all filter/tag dicts found in *api_data*."""
    tags: list[dict] = []

    def _visit(node: dict) -> None:
        # Country codes
        if node.get("country_code"):
            tags.append({"type": "country_code", "value": str(node["country_code"]), "mode": "include"})
        if node.get("country_codes"):
            tags.append({"type": "country_codes", "values": node["country_codes"], "mode": "include"})
        if node.get("exclude_country_code"):
            tags.append({"type": "country_code", "exclude_value": str(node["exclude_country_code"]), "mode": "exclude"})
        if node.get("exclude_country_codes"):
            tags.append({"type": "country_codes", "exclude_values": node["exclude_country_codes"], "mode": "exclude"})
        # Shop numbers (may be a comma-separated string or a single value)
        if node.get("shop_number"):
            raw_sn = str(node["shop_number"])
            for sn in raw_sn.split(","):
                sn = sn.strip()
                if sn:
                    tags.append({"type": "shop_number", "value": sn, "mode": "include"})
        if node.get("exclude_shop_number"):
            tags.append({"type": "shop_number", "exclude_value": str(node["exclude_shop_number"]), "mode": "exclude"})
        # Generic tag list (e.g. leaflet_filter.tags, filters[].tags)
        for t in node.get("tags", []):
            if isinstance(t, dict):
                tags.append(t)
        # Leaflet filter
        if isinstance(node.get("leaflet_filter"), dict):
            lf = {**node["leaflet_filter"], "type": "leaflet_tag"}
            tags.append(lf)
        # Filter items that ARE themselves tags (e.g. filters[].name/value/exclude_value)
        # These cover segment tags like aldithemen_042025=garten
        if node.get("name") and ("value" in node or "exclude_value" in node or
                                  "values" in node or "exclude_values" in node):
            # Only if this looks like a filter/tag node (not a carousel card etc.)
            if not any(k in node for k in ("component_parameters", "cards", "components",
                                            "scheduled_date", "task_id", "id", "bot_id")):
                tags.append(node)

    deep_collect(api_data, visitor=_visit)

    seen: set[str] = set()
    unique: list[dict] = []
    for t in tags:
        key = json.dumps(t, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique



# ---------------------------------------------------------------------------
# Shared tag checking logic (used by both single and bulk checks)
# ---------------------------------------------------------------------------

def check_tags(j_data: dict, a_data: dict, client: str) -> dict:
    """
    Run include/exclude/client-filter tag checks.
    Returns dict with missing_excl, missing_incl, missing_filters etc.
    """
    import re as _re
    from config import CLIENT_CONFIGS

    def _norm(s):
        return s.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")

    _EMPTY = {"none", "-", "\u2014", "n/a", ""}

    # Carousel form section headers — not real tags
    _CAROUSEL_NOISE = {
        "card leaflet filters", "1st card", "2nd card", "3rd card",
        "card body texts", "card button texts", "card images",
        "main body text", "number of cards", "intro text",
    }

    def _split(s):
        parts = [_norm(p) for p in _re.split(r"[,\n;]+", str(s or "")) if p.strip()]
        result = []
        for p in parts:
            pl = p.lower()
            if pl in _EMPTY:
                continue
            # Skip carousel form structural labels
            if any(noise in pl for noise in _CAROUSEL_NOISE):
                continue
            result.append(p)
        return result

    def _normalise_gsheet_tag(tag):
        t = _norm(tag)
        m = _re.match(r"offset[\s_]+days\s*=\s*(\d+)", t, _re.IGNORECASE)
        if m: return f"leaflet_tag={m.group(1)}"
        m = _re.match(r"shop[\s_]+number[\s=]+(\S+)", t, _re.IGNORECASE)
        if m: return f"shop_number={m.group(1)}"
        m = _re.match(r"leaflet[\s_]+accepted\s*=\s*(\S+)", t, _re.IGNORECASE)
        if m: return f"leaflet_accepted={m.group(1).lower()}"
        m = _re.search(r"leaflet[\s_]+accepted.*?=\s*(\S+)", t, _re.IGNORECASE)
        if m: return f"leaflet_accepted={m.group(1).lower()}"
        return t

    all_api_tags = extract_all_tags(a_data)

    # ── Exclude ──
    expected_excl = _split(str(j_data.get("gsheet_exclude_tags", "") or ""))
    api_excl: list = []
    for t in all_api_tags:
        is_excl = "exclude_value" in t or "exclude_values" in t or t.get("mode") == "exclude"
        if is_excl:
            key = t.get("name") or t.get("type") or ""
            val = t.get("exclude_value") or t.get("value") or ""
            if key and val:
                api_excl.append(_norm(f"{key}={val}"))
                api_excl.append(_norm(f"{key}={str(val).lower()}"))
            elif key:
                api_excl.append(_norm(key))
        elif t.get("exclude") is True:
            key = t.get("name") or ""
            val = t.get("value") or ""
            if key and val:
                api_excl.append(_norm(f"{key}={val}"))
    excl_lower = [s.lower() for s in api_excl]
    missing_excl = [e for e in expected_excl if e.lower() not in excl_lower]

    # ── Include ──
    # For ALDI Portugal and Kaufland RCS/WABA, tag validation is via config filters only
    # G-Sheet include tags are not reliable for these clients
    if client in ("ALDI Portugal", "Kaufland RCS", "Kaufland WABA"):
        raw_incl = ""
    else:
        raw_incl = str(j_data.get("gsheet_tags", "") or "")
    expected_incl = [_normalise_gsheet_tag(t) for t in _split(raw_incl)]
    api_incl: list = []
    for t in all_api_tags:
        is_excl = ("exclude_value" in t or "exclude_values" in t or
                   t.get("mode") == "exclude" or t.get("exclude") is True)
        if not is_excl:
            key = t.get("name") or t.get("type") or ""
            val = t.get("value") or str(t.get("offset_days", "")) or ""
            if key and val:
                api_incl.append(_norm(f"{key}={val}"))
                api_incl.append(_norm(f"{key}={str(val).lower()}"))
            if key == "shop_number" and t.get("value"):
                api_incl.append(f"shop number={t['value']}")
            if key == "leaflet_tag" and t.get("offset_days") is not None:
                api_incl.append(f"leaflet_tag={t['offset_days']}")
                api_incl.append(f"offset days={t['offset_days']}")
                api_incl.append(f"offset_days={t['offset_days']}")
            if key == "leaflet_accepted" and val:
                api_incl.append(f"leaflet accepted={val.lower()}")
                api_incl.append(f"leaflet_accepted={val.lower()}")

    def _collect_lf(obj):
        if isinstance(obj, dict):
            lf = obj.get("leaflet_filter")
            if isinstance(lf, dict):
                od = lf.get("offset_days")
                if od is not None:
                    api_incl.append(f"leaflet_tag={od}")
                for t in lf.get("tags", []):
                    n, v = t.get("name", ""), t.get("value", "")
                    if n and v:
                        api_incl.append(f"{n}={v}")
            for v2 in obj.values():
                _collect_lf(v2)
        elif isinstance(obj, list):
            for item in obj:
                _collect_lf(item)
    _collect_lf(a_data)

    incl_lower = [s.lower() for s in api_incl]
    missing_incl = [e for e in expected_incl if e.lower() not in incl_lower]

    # ── Client-specific config filters ──
    all_client_filters = CLIENT_CONFIGS.get(client, {}).get("filters", {})
    if client in ("Kaufland RCS", "Kaufland WABA"):
        from datetime import datetime as _dt
        try:
            dt = _dt.fromisoformat(str(a_data.get("scheduled_date","")).replace("Z","+00:00"))
            is_sun = dt.weekday() == 6
        except Exception:
            is_sun = False
        expected_filters = all_client_filters.get(
            "Sunday" if is_sun else "Wednesday", all_client_filters.get("Standard", []))
    elif client == "ALDI Portugal":
        # Primary: JIRA segment field (most reliable — set by the team on the ticket)
        # Fallback: DMA sendout name or template name
        jira_segment = str(j_data.get("segment", "") or "").lower()
        sendout_name = (a_data.get("name") or a_data.get("campaign_name") or
                        a_data.get("task_name") or "").lower()
        tmpl_name    = str(a_data.get("template_name", "")).lower()
        combined     = f"{jira_segment} {sendout_name} {tmpl_name}"
        if any(kw in combined for kw in ("northern", "norte", "north")):
            expected_filters = all_client_filters.get("Northern", all_client_filters.get("Standard", []))
        else:
            expected_filters = all_client_filters.get("Regular", all_client_filters.get("Standard", []))
    elif client == "ALDI Suisse":
        # Pick filter variant by sendout/task name — DE/FR/IT locale variants + test sendouts
        task_name = (a_data.get("name") or a_data.get("task_name") or
                     j_data.get("request_type", "")).lower()
        matched_variant = None
        for variant_key in all_client_filters:
            if variant_key.lower() in task_name or task_name in variant_key.lower():
                matched_variant = variant_key
                break
        if not matched_variant:
            # Fallback: detect locale from leaflet_filter tags
            lf_tags = a_data.get("leaflet_filter", {}).get("tags", [])
            lf_locale = next((t.get("value","") for t in lf_tags if t.get("name") == "locale"), "")
            for variant_key in all_client_filters:
                if lf_locale and lf_locale in variant_key.lower():
                    matched_variant = variant_key
                    break
        expected_filters = all_client_filters.get(matched_variant or "Standard", [])
    elif client == "ALDI Italy":
        # Carousel sendouts don't use leaflet_tag filter
        _is_carousel = any(
            cp.get("source") == "custom_cards" or cp.get("type") == "carousel"
            for cp in a_data.get("component_parameters", [])
            if isinstance(cp, dict)
        )
        expected_filters = all_client_filters.get(
            "Carousel" if _is_carousel else "Standard", []
        )
    else:
        expected_filters = all_client_filters.get("Standard", [])

    if client == "Toom":
        if "special" in str(j_data.get("request_type", "")).lower():
            expected_filters = [f for f in expected_filters if f.get("type") != "leaflet_tag"]

    # Build api_filter_objs
    api_filter_objs: list = list(a_data.get("filters", []))
    for f in a_data.get("filters", []):
        api_filter_objs.extend(f.get("tags", []))
    if isinstance(a_data.get("leaflet_filter"), dict):
        lf = a_data["leaflet_filter"]
        api_filter_objs.append({"type": "leaflet_tag", "offset_days": lf.get("offset_days"), "mode": "include"})
        for t in lf.get("tags", []):
            api_filter_objs.append({**t, "mode": "include"})
    rcs_cards = (a_data.get("google_rcs_content", {})
                       .get("richCard", {}).get("carouselCard", {}).get("cardContents", []))
    for card in (rcs_cards or []):
        card_lf = card.get("leaflet_filter", {})
        if card_lf:
            od = card_lf.get("offset_days")
            if od is not None:
                api_filter_objs.append({"type": "leaflet_tag", "offset_days": od, "mode": "include"})
            for t in card_lf.get("tags", []):
                api_filter_objs.append({**t, "mode": "include"})
    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "carousel" and "cards" in obj:
                for wcard in obj["cards"]:
                    card_lf = wcard.get("leaflet_filter", {})
                    if card_lf:
                        od = card_lf.get("offset_days")
                        if od is not None:
                            api_filter_objs.append({"type": "leaflet_tag", "offset_days": od, "mode": "include"})
                        for t in card_lf.get("tags", []):
                            api_filter_objs.append({**t, "mode": "include"})
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(a_data)

    def _fmatch(expected, actual):
        exp_name = expected.get("name")
        exp_val  = str(expected.get("value", ""))
        if exp_name and exp_val and expected.get("mode") != "exclude":
            if actual.get("name") == exp_name and str(actual.get("value", "")) == exp_val:
                return True
        if expected.get("type") == "leaflet_tag" and expected.get("offset_days") is not None:
            if (actual.get("type") == "leaflet_tag" and
                    str(actual.get("offset_days", "")) == str(expected["offset_days"])):
                return True
        # For shop_number type with values list: check if actual shop_number string
        # contains all expected values (handles comma-separated shop_number strings)
        if expected.get("type") == "shop_number" and "values" in expected:
            # Normalise: strip all whitespace from each shop number for comparison
            def _norm_sn(s): return s.replace(" ", "").strip()
            v_norm = {_norm_sn(str(x)) for x in expected["values"]}
            av_raw = str(actual.get("value") or actual.get("shop_number") or "").strip()
            if av_raw:
                if "," in av_raw:
                    actual_set = {_norm_sn(s) for s in av_raw.split(",") if s.strip()}
                    return v_norm.issubset(actual_set)
                else:
                    return _norm_sn(av_raw) in v_norm
            return False
        for k, v in expected.items():
            if k == "mode":
                if v == "exclude":
                    if actual.get("exclude_value") != expected.get("value"):
                        return False
            elif k == "type" and v in ("tag", "leaflet_tag", "shop_number", "locale"):
                pass  # type is a category label, handled above or via name/value
            elif k in actual:
                if str(actual.get(k, "")) != str(v):
                    return False
            elif k == "values":
                av = str(actual.get("value") or actual.get("shop_number") or "").strip()
                if isinstance(v, list):
                    v_stripped = [str(x).strip() for x in v]
                    if not av or av not in v_stripped:
                        return False
            elif k not in {"name","value","values","shop_number","locale","type","mode","offset_days"}:
                return False
        return True

    missing_filters = [
        str(exp_f) for exp_f in expected_filters
        if not any(_fmatch(exp_f, act) for act in api_filter_objs)
    ]

    return {
        "expected_excl":    expected_excl,
        "expected_incl":    expected_incl,
        "all_api_tags":     all_api_tags,
        "api_incl_strings": api_incl,
        "api_excl_strings": api_excl,
        "missing_excl":     missing_excl,
        "missing_incl":     missing_incl,
        "expected_filters": expected_filters,
        "api_filter_objs":  api_filter_objs,
        "missing_filters":  missing_filters,
    }


# ---------------------------------------------------------------------------
# Diff / display
# ---------------------------------------------------------------------------

def highlight_diff(text1: str, text2: str) -> str:
    """Return an HTML string showing a line-level diff between two texts."""
    d = difflib.Differ()
    diff = list(d.compare(text1.splitlines(), text2.splitlines()))
    parts = [
        '<div style="font-family:monospace;white-space:pre-wrap;background-color:#f8fafc;'
        'padding:15px;border-radius:8px;border:1px solid #e2e8f0;'
        'max-height:400px;overflow-y:auto;">'
    ]
    for line in diff:
        if line.startswith("+ "):
            parts.append(
                f'<div style="background-color:#dcfce7;color:#166534;'
                f'padding:2px 6px;border-radius:4px;margin-bottom:2px;">{line}</div>'
            )
        elif line.startswith("- "):
            parts.append(
                f'<div style="background-color:#fee2e2;color:#991b1b;'
                f'padding:2px 6px;border-radius:4px;margin-bottom:2px;">{line}</div>'
            )
        elif line.startswith("? "):
            continue
        else:
            parts.append(f'<div style="padding:2px 6px;">{line}</div>')
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Client detection
# ---------------------------------------------------------------------------

def detect_client_from_text(text: str, client_list: list[str]) -> str | None:
    """
    Return the best-matching client name found in *text*, or None.
    Checks aliases first, then falls back to direct substring matching
    (longest name first to avoid partial matches).
    """
    from config import CLIENT_ALIASES  # local import

    if not text:
        return None
    upper = text.upper()
    lower = text.lower()

    # Reporter email domain detection (if text contains email)
    import re as _re_det
    email_m = _re_det.search(r'[\w.+-]+@([\w.-]+\.\w+)', lower)
    if email_m:
        domain = email_m.group(1)
        if "aldi-sued.de" in domain or "aldi-sud.de" in domain:
            return "ALDI Sued"
        if "aldi-pt.pt" in domain or "aldi.pt" in domain:
            return "ALDI Portugal"
        if "aldi-nord.de" in domain:
            return "ALDI Nord"
        if "aldi-ch.ch" in domain or "aldi.ch" in domain:
            return "ALDI Suisse"
        if "aldi.it" in domain or "aldi-italy.it" in domain:
            return "ALDI Italy"
        if "kaufland.de" in domain:
            # Distinguish RCS vs WABA from the text content
            if "rcs" in lower:
                return "Kaufland RCS"
            return "Kaufland WABA"
        if "penny.at" in domain:
            return "PENNY Austria"

    # "WhatsApp Chat Prospekt X" ticket naming from ALDI Sued
    if "whatsapp chat prospekt" in lower or "chat prospekt" in lower:
        return "ALDI Sued"

    # ALDI Portugal is a single client — Regular/Northern is detected from sendout name
    if "aldi portugal" in lower or "aldi pt" in lower:
        return "ALDI Portugal"

    for canonical, aliases in CLIENT_ALIASES.items():
        if any(alias.upper() in upper for alias in aliases):
            return canonical

    for name in sorted(client_list, key=len, reverse=True):
        if name.upper() in upper:
            return name
    return None

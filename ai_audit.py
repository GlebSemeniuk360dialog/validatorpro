"""
ai_audit.py — Gemini-powered deep audit logic.
Isolated from Streamlit so it can be called from tests or CLI.
"""

import io
import json
import logging

from google import genai
from PIL import Image

logger = logging.getLogger(__name__)

_AUDIT_PROMPT_TEMPLATE = """\
⚠️ LANGUAGE RULE — HIGHEST PRIORITY ⚠️
YOU MUST WRITE YOUR ENTIRE RESPONSE IN ENGLISH ONLY.
This overrides everything else. Even if the campaign content is in German, Italian, French, \
Chinese, Japanese, or any other language — every single word of your response must be English.
Do NOT translate content — just describe it in English.
Do NOT switch to any other language at any point.
Violation of this rule makes your response invalid.

You are an expert QA Auditor for WhatsApp Marketing campaigns.
Compare the intended configuration (JIRA/G-Sheet) against the actual technical setup (DMA API/Template).

CLIENT CONTEXT: {client_name}

DATA TO AUDIT (JSON):
{comparison_json}

══════════════════════════════════════════════════════════
MANDATORY AUDIT PROTOCOL — EXECUTE EVERY STEP IN ORDER
══════════════════════════════════════════════════════════
You MUST complete ALL SIX checks below. Do NOT skip any check.
Do NOT merge checks. Do NOT reorder checks.
For every check output EXACTLY this block:

### [EMOJI] CHECK N — [NAME]
**Expected:** [exact value from JIRA / G-Sheet]
**Actual:** [exact value from DMA API]
**Verdict:** ✅ PASS / ❌ FAIL / 🔕 N/A — [one-line reason]

EMOJI rule: ✅ for PASS, ❌ for FAIL, 🔕 for N/A (check genuinely not applicable).
N/A is only allowed when the check cannot be evaluated (e.g. no images provided).
A check is NEVER N/A just because data looks fine — that is a PASS.

CHECK 1 — SCHEDULING
  Compare JIRA date/time to DMA API `Date_Time`. Apply the SCHEDULING RULE below.
CHECK 2 — COPY (body text)
  Compare DMA template body to JIRA description. Apply the TEXT/COPY RULES below.
CHECK 3 — FOOTER
  Compare DMA footer to JIRA footer specification. Apply the FOOTER RULE below.
CHECK 4 — CTA BUTTONS & LINKS
  Check DMA button names and URLs against JIRA. Apply the CTA RULES below.
CHECK 5 — TAGS / AUDIENCE FILTERS
  Compare DMA include/exclude tags to G-Sheet intent. Apply the TAG RULES below.
  This check ALWAYS has a verdict — never skip it, even if G-Sheet tags are empty
  (empty G-Sheet tags = no include filter required = PASS if DMA has no extra unexpected filters).
CHECK 6 — IMAGES / CAROUSEL
  If images were provided, compare them. If no images provided, mark 🔕 N/A.

After all six checks write:
### SUMMARY TABLE
| Check | Verdict |
|-------|---------|
| 1 Scheduling | ✅ / ❌ / 🔕 |
| 2 Copy | ... |
| 3 Footer | ... |
| 4 CTA | ... |
| 5 Tags | ... |
| 6 Images | ... |

**Overall: ✅ ALL PASS** or **❌ N issues found** (list failed checks).

Then write any additional notes or context AFTER the summary table.
══════════════════════════════════════════════════════════

REQUIRED CHECKS & RULES (apply inside the protocol steps above):
1. **Text, Dates, and Change Requests (CRITICAL):**
   - Read the `Comment_Thread`. If the client requested changes in the comments (e.g., "Change the date to X",
     "Update the text to Y", "Exclude tag Z"), this OVERRIDES the original description.
     Evaluate the DMA setup against the *latest* requested changes.
2. **Scheduling:** Check Date and Time.
   - *TAG EQUIVALENCE RULE:* `offset days=1` in the G-Sheet means `leaflet_tag=1` in
     the DMA API (`leaflet_filter.offset_days=1`). Treat these as identical — never flag
     this difference as a mismatch. Similarly `offset days=3` = `leaflet_tag=3` etc.
   - *URL PLACEHOLDER RULE:* `https://rewe.de/{{1}}/angebote/` is the same URL as
     `https://rewe.de/angebote/{{shop_number}}/` — {{{{1}}}} and {{shop_number}} are both
     dynamic store ID placeholders. Query parameters like `?ecid=...` do not affect
     URL identity. Also, a relative URL like `angebote/{{shop_id}}/?ecid=...` in the
     DMA API is the same as `https://rewe.de/angebote/` — the domain is implied.
     Never flag placeholder/param/relative-vs-absolute differences as URL mismatches.
   - *TEMPLATE VARIABLE RULE:* Any URL containing `{{1}}`, `{{shop_number}}`, `{{leaflet_url}}`,
     `{{leaflet_url_path}}` or any `{{...}}` pattern is a dynamic template variable, NOT a real URL.
     NEVER flag `https://aldi.co/{{1}}` or any similar `{{...}}`-containing URL as unexpected —
     these are required template placeholders and should be completely ignored in URL checks.
   - *SHORT URL RULE:* Short URLs (aldi.co, shorturl.at, bit.ly, tinyurl.com, etc.) in the API
     that are not explicitly listed in JIRA should NOT be flagged as unexpected — they
     are used as leaflet URL placeholders and are equivalent to the JIRA URL.
     If JIRA has one short URL and the API has a different short URL pointing to the same
     domain/service, treat them as equivalent. Only flag a URL mismatch if the JIRA
     specifies a full URL and the API has a completely different domain with no obvious
     connection to the JIRA URL.
   - *LEAFLET URL RULE:* If the DMA API contains a URL with `{{{{1}}}}` as a path
     segment (e.g. `https://bit.ly/{{{{1}}}}` or similar), this is a leaflet URL
     placeholder that resolves to the same destination as the actual URL in JIRA.
     Do NOT flag it as an extra or unexpected URL — treat it as equivalent to the
     JIRA URL. Multiple URLs that share the same base/domain or are clearly the same
     link with a placeholder should be treated as one URL.
   - *SCHEDULING RULE (ABSOLUTE — NEVER OVERRIDE):*
     The DMA API `Date_Time` field stores the LOCAL clock time for that client, labeled as Z.
     This means `2026-04-19T09:00:25Z` for a German client means **09:00 CET**, NOT 09:00 UTC.
     For most clients (Germany, Austria, etc.): DMA time = CET clock. JIRA time in CET = direct match.
     Example: JIRA `09:00 CET`, API `09:00Z` → diff = 0 min → ✅ PASS.

     *ALDI PORTUGAL EXCEPTION:* For ALDI Portugal, skip the detailed scheduling check entirely.
     The sendout time is always either 18:00 or 19:00 local Portugal time. If the API time ends
     in 18:xx or 19:xx, mark scheduling as ✅ PASS without further analysis.

     TOLERANCE: Only flag ❌ FAIL if the difference is **strictly more than 40 minutes**.
     A difference of 40 minutes or less is ALWAYS ✅ PASS — no exceptions.
     30 minutes difference → ✅ PASS. 40 minutes → ✅ PASS. 41 minutes → ❌ FAIL.
     Do NOT flag based on comments or client requests — only the clock difference matters.
3. **Text / Copy Validation:**
   - Does the DMA Template match the JIRA Description (or the overridden intent from comments)?
   - *CAROUSEL RULE:* If the DMA Template contains `Template_Carousel_Cards`, check text and buttons
     for EVERY single card against the corresponding slides in the JIRA Description.
     If `JIRA_Parsed_Carousel` is provided, use it to cross-reference exactly.
   - *MARKDOWN/BOLD RULE:* Differences in bold markdown formatting (e.g. `*word*` vs
     `*word word*`, or split vs merged bold phrases) are NOT errors. Only compare the
     actual text content, ignoring asterisks and formatting markers entirely.
   - *SLIDE LABEL RULE (IMPORTANT):* Lines like "Slide 1:", "Slide 2:", "Slider 3:" in the JIRA
     Description are structural labels only — they are NOT part of the message text and must
     be completely ignored during text comparison. Do NOT flag their absence in the DMA as a mismatch.
   - *NAHKAUF PLACEHOLDER RULE:* In Nahkauf templates, `XY-Straße, XY-Hausnr.`
     in JIRA is replaced by `{{1}}, {{2}}.` in the DMA template (with a dot after
     `{{2}}`). The trailing dot is part of the template syntax. Do NOT flag this
     as a mismatch — `{{1}}, {{2}}.` and `XY-Straße, XY-Hausnr.` are equivalent.
   - Ignore internal instructions like "Send this on Monday".
     Ensure text intended for the Footer hasn't mistakenly been put in the Body.
   - *FOOTER RULE:* If JIRA has no footer text → always ✅ PASS even if DMA has a
     footer (it is a default). Only ❌ FAIL if JIRA specifies a footer but it is
     absent from the DMA template.
4. **CTA Buttons & Links:**
   - Do the JIRA and DMA button names match?
   - Verify that URLs found in `JIRA_All_URLs` exist in `API_URLs_Configured`.
   - *IMAGE URL IGNORE RULE (ABSOLUTE):* The DMA API response contains image hosting URLs
     from CDN / storage services. These are NEVER CTA button URLs. You MUST completely
     ignore any URL that:
     • contains `storage.googleapis.com`
     • contains `scontent.whatsapp.net`
     • contains `whatsapp.net`
     • contains `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif` as a path component
     • contains `uploads/file_documents/`
     • is clearly an image CDN link (long token-based URL with `ccb=`, `_nc_sid=`, `oh=`, `oe=` parameters)
     Do NOT list such URLs as "additional" or "unexpected" URLs. Do NOT flag them as ❌ FAIL.
     Only compare actual button/CTA URLs (short links, leaflet URLs, promo landing pages).
     If the only "extra" URLs are image hosting links, CHECK 4 verdict is ✅ PASS (or N/A if no button).
5. **Tags / Audience & Exclusions:**
   - Compare JIRA/Sheet tags to DMA tags (respecting comment overrides).
   - *G-SHEET EXCLUDE TAGS RULE (ABSOLUTE — NO EXCEPTIONS):*
     The G-Sheet `Exclude_Tags` field defines EXACTLY which tags must be excluded.
     This is non-negotiable. You MUST:
     1. Check that every tag in `G_Sheet_Intent.Exclude_Tags` exists in the DMA API as an exclude filter.
     2. Check that the DMA API does NOT have exclude tags that are NOT in `G_Sheet_Intent.Exclude_Tags`.
     Any deviation in EITHER direction = ❌ FAIL:
     - Missing G-Sheet exclude tag in DMA → ❌ FAIL
     - Extra exclude tag in DMA not in G-Sheet → ❌ FAIL
     - Wrong value (e.g. G-Sheet: `familien`, DMA: `grillen`) → ❌ FAIL
     Do NOT rationalize, justify, or accept any explanation for deviations.
     Do NOT say "this is acceptable for segmentation purposes" — it is NOT acceptable.
     The G-Sheet is the source of truth. Period.
     Example: G-Sheet Exclude=`aldithemen_042025=grillen`, DMA excludes `weiterethemen_042025=familien`
     → ❌ FAIL: wrong tag excluded AND required tag missing.
   - *G-SHEET INCLUDE TAGS RULE:* Similarly, if `G_Sheet_Intent.Include_Tags` is
     non-empty, verify all include tags exist in the DMA API configuration.
   - *ALDI PORTUGAL RULE:* For 'ALDI Portugal Regular' the DMA API MUST include
     a shop_number include filter with the Regular shop list. For 'ALDI Portugal
     Northern' it MUST include the Northern shop list. If the wrong shop numbers
     are configured or shop_number filter is missing, flag as ❌ FAIL.
   - *MANDATORY FILTER RULE:* Some clients have mandatory system filters that are
     always present in the DMA API regardless of what JIRA specifies (e.g. ALDI Italy
     always has leaflet_tag=1 for regular sendouts, REWE always has declined_new_terms exclude). If the DMA
     API contains a filter that is not mentioned in JIRA but is a known mandatory client
     filter, do NOT flag it as an audience mismatch. Only flag filters that are
     unexpected AND not part of the client's standard configuration.
   - *ALDI ITALY CAROUSEL RULE:* If the ALDI Italy sendout is a carousel (contains
     carousel cards / custom_cards in component_parameters), the leaflet_tag filter
     is NOT required and its absence is NOT an error. Do NOT flag missing leaflet_tag
     for ALDI Italy carousel sendouts. Only regular (non-carousel) ALDI Italy sendouts
     require leaflet_tag=1.
   - *SPECIAL RULE FOR 'KAUFLAND WABA' SUNDAY SENDOUT:* If the client is Kaufland WABA
     and the JIRA description is empty, this is expected — the carousel card body text
     is always the static leaflet template:
     'Hier findest du unseren aktuellen Prospekt mit den Angeboten vom {{1}} – {{2}} für deine Filiale in {{3}} {{4}} ⬇️'
     Both cards (special and regular leaflet) use this exact same body text with dynamic
     placeholders ({{{{1}}}}=start_date, {{{{2}}}}=end_date, {{{{3}}}}=shop_city, {{{{4}}}}=shop_address).
     Do NOT flag missing JIRA text. DO verify the template body matches this exact text.
     If the actual DMA card body differs from this expected text, flag as ❌ FAIL.
   - *SPECIAL RULE FOR 'KAUFLAND RCS' WEDNESDAY SENDOUT:* If the sendout is on Wednesday
     (not Sunday), Card 1 ('Knüller-Angebote') is a static leaflet card — do NOT check
     its text against JIRA. Card 2 contains a promotional text that MUST match the
     JIRA ticket description. If Card 2 text significantly differs from the JIRA
     description, flag as ❌ FAIL.
   - *SPECIAL RULE FOR 'KAUFLAND RCS' SUNDAY SENDOUT:* If the JIRA description
     starts with '[STATIC RCS TEMPLATE]', the expected card texts are provided there.
     You MUST compare every single word of the DMA card text against these expected
     texts. Any deviation — including extra words, wrong title, or different body text
     — is a ❌ FAIL. Specifically verify ALL of the following:
     1. Card 1 title MUST be exactly 'Wochenstart-Angebote'. Any other title is ❌ FAIL.
     2. Card 2 title MUST be exactly 'Knüller-Angebote'. Any other title is ❌ FAIL.
     3. Card 1 body MUST contain the standard Kaufland text with {{shop_city}},
        {{shop_address}}, {{leaflet_start_date}}, {{leaflet_end_date}} placeholders
        and end with 'Kaufland - Hier bin ich richtig.' and the STOP instruction.
        Any extra text like 'TEST 1 TEST 2 TEST 3' is a critical ❌ FAIL.
     4. Card 1 must have leaflet_type=special with offset_days=1.
     5. Card 2 must use leaflet_type=regular with offset_days=4.
     6. Both cards must have a 'Zum Prospekt' button.
     7. If card titles or body texts differ from expected — ❌ FAIL immediately.
   - *SPECIAL RULE FOR 'TOOM':* If the JIRA request type contains 'special', do NOT
     check for the leaflet_tag / offset_days filter. Special sendouts for Toom do not
     require a leaflet filter.
   - *SPECIAL RULE FOR 'ALDI Sued':* ALDI Sued runs multiple segmented sendouts per week.
     The JIRA ticket has a `Tags_Segment` field that identifies which audience segment this ticket covers.
     The G-Sheet intent (`G_Sheet_Intent.Include_Tags` / `Exclude_Tags`) contains the tags for THAT specific segment.
     The DMA API may run a "Standard" sendout (e.g. "Aldi Süd Standard (excl kochen, haushalt, bio)")
     which serves everyone EXCEPT the excluded segments — this is CORRECT and expected.
     CRITICAL: Compare the G-Sheet Include/Exclude tags against the DMA API tags for the segment shown.
     Do NOT flag the DMA Standard task as wrong just because it has exclusion clauses — those are expected.
     DO flag if the G-Sheet include tags are missing from the DMA API config for this segment.
     The DMA task name with "(excl X, Y, Z)" means those segments have their own separate sendouts.
6. **Images & Carousels:** If images are provided below, visually compare them.
   - Ensure the visual order of JIRA images matches the DMA images.
   - *STRICT RULE:* If a JIRA image is just a generic company logo but the DMA image is a valid
     promotional banner fitting the copy, treat this as a ✅ PASS.

LANGUAGE RULE: Always respond in English only, regardless of the language of the content being audited.

OUTPUT FORMAT (STRICT JSON — no markdown fences, no preamble):
{{
    "audit_report": "Full Markdown report. Use ✅, ❌, ⚠️. Use \\n\\n for newlines.",
    "confidence": <integer 0-100 representing your confidence in this audit result>,
    "confidence_reason": "One sentence explaining the confidence score. Low if data was missing/ambiguous, high if everything was clear.",
    "jira_extracted_urls": ["list", "of", "urls", "from", "JIRA"],
    "api_extracted_urls": ["list", "of", "urls", "from", "DMA"]
}}

Confidence scoring guide:
- 90-100: All data present, clear pass or fail, no ambiguity
- 70-89: Minor missing data (e.g. no footer specified) but conclusion is clear
- 50-69: Some data missing or ambiguous, conclusion is uncertain
- Below 50: Major data gaps, result should be manually reviewed regardless of pass/fail
"""



_EMPTY_TAG_VALUES = {"none", "-", "–", "—", "n/a", "null", ""}

def _norm_tags(s: str) -> str:
    """Normalise a tag string, splitting on , or newline; skip empty/none values."""
    import re as _re
    parts = _re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p and p.lower() not in _EMPTY_TAG_VALUES:
            cleaned.append(p)
    return ", ".join(cleaned)

def _norm_tags_list(s: str) -> list:
    """Same as _norm_tags but returns a list for membership testing."""
    import re as _re
    parts = _re.split(r"[,\n;]+", str(s or ""))
    cleaned = []
    for p in parts:
        p = p.strip().replace(" = ", "=").replace("= ", "=").replace(" =", "=")
        if p:
            cleaned.append(p)
    return cleaned


def build_comparison_data(
    jira: dict,
    tmpl_body: str,
    tmpl_footer: str,
    tmpl_buttons: list[str],
    dma_carousel_texts: list[str],
    api_tag_str: str,
    api_urls: list[str],
    client_name: str = "",
    api_date: str = "",
) -> dict:
    """Assemble the structured payload that is sent to Gemini."""
    from utils import extract_urls  # avoid circular at module level

    jira_all_text = " ".join(filter(None, [
        str(jira.get("description", "")),
        str(jira.get("additional_comments", "")),
        str(jira.get("cta_link", "")),
    ]))

    # For clients where G-Sheet tags are not reliable, derive expected tags from config
    from config import CLIENT_CONFIGS
    _client_lower = client_name.lower()
    _SKIP_GSHEET_TAGS = ("kaufland rcs", "kaufland waba", "aldi portugal")
    if any(s in _client_lower for s in _SKIP_GSHEET_TAGS):
        # Build expected filter string from config
        _all_cf = CLIENT_CONFIGS.get(client_name, {}).get("filters", {})
        if "kaufland" in _client_lower:
            from datetime import datetime as _dt
            try:
                _is_sun = _dt.fromisoformat(api_date.replace("Z","+00:00")).weekday() == 6
            except Exception:
                _is_sun = False
            if "rcs" in _client_lower or "waba" in _client_lower:
                _cf = _all_cf.get("Sunday" if _is_sun else "Wednesday", _all_cf.get("Standard", []))
            else:
                _cf = _all_cf.get("Standard", [])
        elif "aldi portugal" in _client_lower:
            # Use JIRA segment field as primary, fallback to api_tag_str
            jira_segment = str(jira.get("segment", "") or "").lower()
            is_northern = any(kw in jira_segment for kw in ("northern", "norte", "north"))
            if not is_northern:
                is_northern = any(kw in api_tag_str.lower() for kw in ("northern", "norte", "north"))
            if is_northern:
                _cf = _all_cf.get("Northern", _all_cf.get("Standard", []))
            else:
                _cf = _all_cf.get("Regular", _all_cf.get("Standard", []))
        else:
            _cf = _all_cf.get("Standard", [])

        _filter_parts = []
        for f in _cf:
            if f.get("mode") == "exclude":
                continue
            ftype = f.get("type", "")
            name  = f.get("name") or ftype or ""
            val   = f.get("value", "")
            od    = f.get("offset_days")
            if ftype == "leaflet_tag" and od is not None:
                _filter_parts.append(f"leaflet_tag={od}")
            elif name and val:
                _filter_parts.append(f"{name}={val}")
            elif name:
                _filter_parts.append(name)
        expected_incl = ", ".join(_filter_parts) if _filter_parts else "(from config)"
        expected_excl = ""
    else:
        expected_incl = _norm_tags(str(jira.get("gsheet_tags", "")))
        expected_excl = _norm_tags(str(jira.get("gsheet_exclude_tags", "")))

    return {
        "JIRA_Intent": {
            "Date": str(jira.get("date", "")),
            "Timezone": str(jira.get("timezone", "")),
            "Text_Description": str(jira.get("description", "")),
            "JIRA_Parsed_Carousel": jira.get("parsed_carousel"),
            "Footer": str(jira.get("footer_text", "")),
            "CTA_Button_Text": str(jira.get("cta_button", "")),
            "JIRA_All_URLs": ", ".join(extract_urls(jira_all_text)),
            "Tags_Segment": (str(jira.get("segment", "")) if "aldi sued" in _client_lower else "N/A — not checked for this client"),
            "Comment_Thread": "\n".join(jira.get("comments", [])),
        },
        "G_Sheet_Intent": {
            "Include_Tags": expected_incl,
            "Exclude_Tags": expected_excl,
            "Note": "(derived from client config, not G-Sheet)" if any(s in _client_lower for s in _SKIP_GSHEET_TAGS) else "",
            "CRITICAL": "If Exclude_Tags is non-empty, DMA MUST have matching exclude filters. Missing/wrong excludes = ❌ FAIL." if expected_excl else "",
        },
        "DMA_API_Setup": {
            "Date_Time": api_date or str(jira.get("date", "")),  # Raw API scheduled_date
            "Timezone": str(jira.get("timezone", "")),
            "Template_Body_Intro": tmpl_body,
            "Template_Carousel_Cards": dma_carousel_texts,
            "Template_Footer": tmpl_footer,
            "Template_Buttons": ", ".join(tmpl_buttons),
            "API_Tags_And_Filters": api_tag_str,
            "API_URLs_Configured": ", ".join(api_urls),
        },
    }



def _repair_json(raw: str) -> str:
    """Attempt to fix common Gemini JSON corruption before parsing."""
    import re as _re
    # Remove stray 1-4 letter prefixes (with optional spaces) before a quoted string on array lines
    # Handles both: ax"https://..." and e   "https://..."
    raw = _re.sub(r'(\n\s*)[a-zA-Z]{1,4}\s*"', r'\1"', raw)
    # Strip stray '} after a string value: "url'}", -> "url",
    raw = _re.sub(r"'\}", '', raw)
    # Fix trailing commas before closing brackets
    raw = _re.sub(r',(\s*[}\]])', r'\1', raw)
    return raw


def _extract_json(raw_text: str) -> str:
    """Strip optional markdown fences from a JSON response."""
    if "```json" in raw_text:
        return raw_text.split("```json")[1].split("```")[0].strip()
    if "```" in raw_text:
        return raw_text.split("```")[1].split("```")[0].strip()
    return raw_text.strip()


def run_ai_audit(
    api_key: str,
    model_name: str,
    comparison_data: dict,
    client_name: str,
    jira_images: list[dict] | None = None,
    dma_images: list[bytes | None] | None = None,
) -> dict:
    """
    Call Gemini with the comparison data and optional images.
    Returns a dict with keys: audit_report, jira_extracted_urls, api_extracted_urls.
    On parse failure, audit_report contains the raw text.
    """
    client = genai.Client(api_key=api_key)

    prompt = _AUDIT_PROMPT_TEMPLATE.format(
        client_name=client_name,
        comparison_json=json.dumps(comparison_data, indent=2),
    )

    contents: list = [prompt]

    if jira_images:
        contents.append("\n--- JIRA REQUESTED IMAGES (sorted by slide number from filename) ---")
        # Sort by slide number extracted from filename so image01 -> Slide 1, etc.
        import re as _re
        def _slide_num_ai(name: str) -> int:
            import re as _re
            stem = _re.sub(r"\.[a-z0-9]+$", "", name.lower())
            m = _re.search(r"(?<![a-z])(?:slide|card|pic|img|carousel)[-_\s]*0*(\d+)", stem)
            if m:
                n = int(m.group(1))
                if 0 < n <= 50: return n
            all_segs = _re.findall(r"[-_]0*(\d{1,2})(?=[-_]|$)", stem)
            for seg in reversed(all_segs):
                n = int(seg)
                if 0 < n <= 20: return n
            m = _re.search(r"(\d+)$", stem)
            if m:
                n = int(m.group(1))
                if 0 < n <= 50: return n
            return 9999


        sorted_imgs = sorted(jira_images, key=lambda x: _slide_num_ai(x.get("name", "")))
        for img_dict in sorted_imgs:
            slide_n = _slide_num_ai(img_dict.get("name", ""))
            label = f"Slide {slide_n}" if slide_n != 9999 else img_dict.get("name", "unknown")
            try:
                img = Image.open(io.BytesIO(img_dict["bytes"]))
                contents.extend([f"JIRA {label} (Filename: {img_dict['name']}):", img])
            except Exception as exc:
                logger.warning("Could not open JIRA image %s: %s", img_dict.get("name"), exc)

    if dma_images:
        contents.append("\n--- DMA API CONFIGURED IMAGES (In Order) ---")
        for i, img_bytes in enumerate(dma_images):
            if img_bytes:
                try:
                    img = Image.open(io.BytesIO(img_bytes))
                    contents.extend([f"DMA API Slide {i + 1}:", img])
                except Exception as exc:
                    logger.warning("Could not open DMA image %d: %s", i + 1, exc)

    raw_text = ""
    try:
        from google.genai import types as _genai_types
        # For Flash models: disable extended thinking (thinking_budget=0) for max speed.
        # For Pro models: let the model use its default reasoning.
        _is_flash = "flash" in model_name.lower()
        _thinking_cfg = _genai_types.ThinkingConfig(thinking_budget=0) if _is_flash else None
        _config = _genai_types.GenerateContentConfig(
            system_instruction=(
                "You are a QA auditor for WhatsApp marketing campaigns. "
                "ABSOLUTE RULE 1: You MUST respond ONLY in English. "
                "Do NOT use Chinese, Japanese, Korean, Arabic, Cyrillic, or any non-Latin script. "
                "Do NOT use German, French, Italian, Dutch, or any other language — ENGLISH ONLY. "
                "The campaign content may be in any language, but YOUR RESPONSE must always be English. "
                "If you write in any other language, your response is wrong and will be discarded. "
                "ABSOLUTE RULE 2: You MUST execute ALL SIX protocol checks in the exact order given. "
                "Each check must produce its own ### CHECK N header with Expected/Actual/Verdict. "
                "Never merge checks. Never skip a check. Never reorder checks. "
                "A missing check block = invalid audit that will be rejected."
            ),
            **({} if _thinking_cfg is None else {"thinking_config": _thinking_cfg}),
        )

        def _has_non_english(text: str) -> bool:
            """Detect significant non-Latin characters indicating wrong language."""
            non_latin = sum(1 for c in text if ord(c) > 0x036F)
            return non_latin > 20  # more than 20 non-Latin chars = likely wrong language

        raw_text = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=_config,
        ).text

        # If response is in wrong language, retry once with reinforced instruction prepended
        if _has_non_english(raw_text):
            logger.warning("AI response appears to be in non-English — retrying with reinforced instruction")
            _lang_fix = (
                "STOP. Your previous response was NOT in English. "
                "You MUST rewrite your ENTIRE response in English only. "
                "Every single word must be English. "
                "Do NOT use Japanese, Chinese, German, French, Italian, Korean, Arabic, or any other language. "
                "ENGLISH ONLY. Produce the full JSON audit report now, entirely in English:"
            )
            # Prepend the correction as the first content item for maximum impact
            _retry_contents = [_lang_fix] + list(contents)
            raw_text = client.models.generate_content(
                model=model_name,
                contents=_retry_contents,
                config=_config,
            ).text
        json_str = _extract_json(raw_text)
        json_str = _repair_json(json_str)
        result = json.loads(json_str)
        # Sanity-check: if the report itself signals a server/model error, flag it
        report = result.get("audit_report", "")
        if _is_audit_error(report):
            result["error"] = True
        return result
    except json.JSONDecodeError as exc:
        logger.error("AI audit JSON parse failed: %s", exc)
        return {
            "audit_report": f"AI audit generated, but JSON parsing failed: {exc}\n\nRaw output:\n{raw_text}",
            "jira_extracted_urls": [],
            "api_extracted_urls": [],
            "error": True,
        }
    except Exception as exc:
        err_str = str(exc)
        # Detect Gemini 503 / resource exhaustion — transient, user should retry
        _overload = (
            "503" in err_str
            or "UNAVAILABLE" in err_str.upper()
            or "high demand" in err_str.lower()
            or "resource_exhausted" in err_str.lower()
            or "429" in err_str
        )
        logger.error("AI audit call failed (overloaded=%s): %s", _overload, exc)
        return {
            "audit_report": (
                "⚠️ AI model temporarily unavailable — experiencing high demand. "
                "Please try again in a moment."
            ) if _overload else f"AI audit call failed: {exc}",
            "jira_extracted_urls": [],
            "api_extracted_urls": [],
            "error": True,
            "retry_later": _overload,
        }


def _is_audit_error(report: str) -> bool:
    """Return True if the audit report indicates a server/model error rather than a real audit."""
    if not report:
        return True

    # Definitive error phrase matches — safe, won't appear in normal audit text
    _DEFINITIVE_ERRORS = (
        "AI audit call failed",
        "JSON parsing failed",
        "RESOURCE_EXHAUSTED",
        "ServiceUnavailable",
        "overloaded",
        "high demand",
        "deadline exceeded",
    )
    report_lower = report.lower()
    if any(sig.lower() in report_lower for sig in _DEFINITIVE_ERRORS):
        return True

    # HTTP status codes — only flag if they appear with surrounding error context,
    # not inside URLs or filenames (e.g. "500px", "rewe.de/500-products")
    import re as _re
    # Match "503", "429", "500" only when surrounded by non-digit/non-URL characters
    if _re.search(r'(?<![/\w])50[03](?!\d)', report) or _re.search(r'(?<![/\w])429(?!\d)', report):
        # Additional check: must appear near error keywords
        ctx_window = 120
        for m in _re.finditer(r'(?<![/\w])(?:503|429|500)(?!\d)', report):
            start = max(0, m.start() - ctx_window)
            end   = min(len(report), m.end() + ctx_window)
            ctx   = report[start:end].lower()
            if any(kw in ctx for kw in ("error", "unavailable", "failed", "status", "code")):
                return True

    # "UNAVAILABLE" / "INTERNAL" — only flag as standalone status words, not in URLs
    if _re.search(r'(?<![/\w-])UNAVAILABLE(?![\w-])', report):
        return True
    if _re.search(r'(?<![/\w-])INTERNAL(?!\s+(?:link|use|server.*error|[\w-]+\.html))', report):
        # Only flag INTERNAL if it's followed by nothing or an error indicator
        if _re.search(r'INTERNAL["\s]*}', report) or "'status': 'INTERNAL'" in report:
            return True

    # Timeout — only as a standalone word, not "timeout" inside a word
    if _re.search(r'\btimeout\b', report_lower) or _re.search(r'\btime.out\b', report_lower):
        return True

    return False

"""
ai_audit.py — Gemini-powered deep audit logic.
Isolated from Streamlit so it can be called from tests or CLI.
"""

import difflib
import io
import json
import logging
import re as _re
from datetime import datetime as _dt
from typing import Literal

from google import genai
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Structured output schema ───────────────────────────────────────────────────

class CheckVerdict(BaseModel):
    verdict:  Literal["PASS", "FAIL", "NA"]
    reason:   str   # one sentence, English only
    expected: str   # exact value from JIRA / G-Sheet
    actual:   str   # exact value from DMA API

class AuditOutput(BaseModel):
    scheduling: CheckVerdict
    copy:       CheckVerdict
    footer:     CheckVerdict
    cta:        CheckVerdict
    tags:       CheckVerdict
    images:     CheckVerdict
    overall:    Literal["PASS", "FAIL"]
    confidence: int           # 0-100
    confidence_reason: str

_AUDIT_PROMPT_TEMPLATE = """\
{examples_block}⚠️ LANGUAGE RULE — HIGHEST PRIORITY ⚠️
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
MANDATORY AUDIT PROTOCOL — EXECUTE EVERY CHECK IN ORDER
══════════════════════════════════════════════════════════
You MUST complete ALL SIX checks below. Do NOT skip any check. Do NOT merge checks.

For each check, populate these four fields:
  verdict:  "PASS", "FAIL", or "NA" (exact string — no emoji, no extra text)
  reason:   ONE sentence in English explaining the verdict
  expected: brief exact value from JIRA / G-Sheet
  actual:   brief exact value from DMA API / Template

N/A rules: use "NA" ONLY when the check genuinely cannot be evaluated
(e.g. CHECK 6 when no images were provided). "NA" is NEVER correct just because
data looks fine — that is "PASS".

——— IMPORTANT — USE PRE-COMPUTED DIFFS ———
The comparison data includes a "Precomputed_Diffs" section with Python-calculated results.
These diffs are reliable starting points — you MUST confirm or override them using the
rules listed further below. They reduce your workload: you are confirming, not re-discovering.

  Precomputed_Diffs.scheduling:
    • diff_minutes = absolute difference between JIRA local clock and API local clock
    • within_40min_tolerance = True → pre_verdict PASS, False → pre_verdict FAIL
    • Apply SCHEDULING RULE below; override only if a special exception applies (e.g. ALDI Portugal).

  Precomputed_Diffs.copy_text:
    • similarity_ratio = 0.0–1.0 (≥0.92 = nearly identical, ≥0.75 = similar, <0.75 = divergent)
    • pre_verdict: PASS if ≥0.75, FAIL if <0.75 — confirm using intent and the COPY RULES below.
    • A low ratio can be PASS if explained by template variables, placeholder substitution, etc.

  Precomputed_Diffs.tags:
    • missing_include / extra_include / missing_exclude / extra_exclude are Python set diffs.
    • pre_verdict PASS means zero deviations detected. Confirm using TAG RULES below.
    • Note: the tag parser is basic — use the rules to adjudicate ambiguous cases.

  Precomputed_Diffs.cta_urls:
    • image_urls_ignored = count of CDN/storage image URLs already stripped out.
    • missing_from_api / extra_in_api are CTA-only URL diffs.
    • pre_verdict PASS means CTA URLs match after filtering. Apply CTA RULES below.

CHECK 1 — SCHEDULING: Compare JIRA date/time to DMA Date_Time. Apply SCHEDULING RULE.
CHECK 2 — COPY: Compare DMA template body to JIRA description. Apply TEXT/COPY RULES.
CHECK 3 — FOOTER: Compare DMA footer to JIRA footer spec. Apply FOOTER RULE.
CHECK 4 — CTA BUTTONS & LINKS: Check DMA button names and URLs against JIRA. Apply CTA RULES.
CHECK 5 — TAGS / AUDIENCE FILTERS: Compare DMA include/exclude tags to G-Sheet intent. Apply TAG RULES.
  Tags check ALWAYS has a verdict — never "NA" even if G-Sheet tags are empty.
  (empty G-Sheet tags = no include filter required → PASS if DMA has no unexpected extra filters)
CHECK 6 — IMAGES / CAROUSEL: If images were provided, compare visually. If no images → "NA".

overall = "PASS" only if every check is "PASS" or "NA". If ANY check is "FAIL" → overall = "FAIL".
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
   - *EXTRA SHORT URL RULE (ABSOLUTE — NEVER OVERRIDE):*
     If the API contains MORE short URLs than JIRA specifies (e.g. two aldi.co/ links
     while JIRA only listed one), this is NEVER a ❌ FAIL.
     Multiple short URLs on the same domain are for different sendout periods or stores.
     The CHECK 4 rule is: "is the JIRA URL PRESENT in the API?" — NOT "is the API URL list
     identical to JIRA?" Extra same-domain short URLs must be completely ignored.
     Check `Precomputed_Diffs.cta_urls.same_domain_ignored` — if it lists any URLs,
     they are already confirmed as same-domain and should be treated as ✅ PASS.
     Only ❌ FAIL if a JIRA URL is MISSING from the API, or if a truly foreign domain
     (unrelated to the JIRA URL domain) appears unexpectedly.
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

Confidence scoring guide (for the confidence field, 0-100):
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


# ── Pre-computation helpers ────────────────────────────────────────────────────

def _is_image_url(url: str) -> bool:
    """Return True if a URL is an image CDN link — never a CTA button."""
    _IMG_DOMAINS = ("storage.googleapis.com", "scontent.whatsapp.net", "whatsapp.net")
    _IMG_PARAMS  = ("ccb=", "_nc_sid=", "oh=", "oe=", "_nc_ohc=")
    _IMG_EXTS    = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
    u = url.lower()
    if any(d in u for d in _IMG_DOMAINS): return True
    if any(u.endswith(e) or (e + "?") in u or (e + "&") in u for e in _IMG_EXTS): return True
    if "uploads/file_documents/" in u: return True
    if sum(1 for p in _IMG_PARAMS if p in u) >= 3: return True
    return False


def _compute_scheduling_diff(jira_date_str: str, api_date_str: str) -> dict:
    """
    Compare JIRA and DMA dates as LOCAL clock readings (ignore timezone labels).
    The DMA API stores local time labeled as Z — so we strip tz and compare directly.
    """
    def _parse_local(s: str):
        s = str(s or "").strip()
        s = _re.sub(r'\s*(CET|CEST|UTC|GMT|MEZ|MESZ)$', '', s, flags=_re.I).strip()
        s = _re.sub(r'[TZ]', ' ', s).strip().rstrip('+').rstrip('-')
        s = _re.sub(r'\s+\+\d{2}:\d{2}$', '', s).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%Y-%m-%d"):
            try: return _dt.strptime(s.strip(), fmt)
            except ValueError: continue
        return None

    jira_dt = _parse_local(jira_date_str)
    api_dt  = _parse_local(api_date_str)

    if jira_dt is None or api_dt is None:
        return {
            "jira_local_clock": str(jira_date_str),
            "api_local_clock":  str(api_date_str),
            "diff_minutes": None,
            "within_40min_tolerance": None,
            "pre_verdict": "NA",
            "note": "Could not parse one or both dates — AI must evaluate manually",
        }

    diff_min = round(abs((api_dt - jira_dt).total_seconds()) / 60, 1)
    within   = diff_min <= 40
    return {
        "jira_local_clock":      jira_dt.strftime("%Y-%m-%d %H:%M"),
        "api_local_clock":       api_dt.strftime("%Y-%m-%d %H:%M"),
        "diff_minutes":          diff_min,
        "within_40min_tolerance": within,
        "pre_verdict":           "PASS" if within else "FAIL",
        "note": (f"Diff = {diff_min} min — "
                 f"{'✅ PASS (≤40 min tolerance)' if within else '❌ FAIL (>40 min tolerance)'}"),
    }


def _compute_text_similarity(jira_text: str, dma_text: str) -> dict:
    """Compute body-text similarity so AI focuses on intent rather than string matching."""
    def _normalize(t: str) -> str:
        t = str(t or "")
        t = _re.sub(r'\*+', '', t)                           # strip bold markers
        t = _re.sub(r'Slide\s*\d+\s*:', '', t, flags=_re.I)  # strip slide labels
        t = _re.sub(r'Slider\s*\d+\s*:', '', t, flags=_re.I)
        t = _re.sub(r'\s+', ' ', t).strip().lower()
        return t

    jn = _normalize(jira_text)
    dn = _normalize(dma_text)

    if not jn and not dn:
        return {"similarity_ratio": 1.0, "pre_verdict": "PASS",
                "note": "Both texts empty — no copy to compare"}
    if not jn:
        return {"similarity_ratio": 1.0, "pre_verdict": "PASS",
                "note": "JIRA has no description — nothing to check"}
    if not dn:
        return {"similarity_ratio": 0.0, "pre_verdict": "FAIL",
                "note": "DMA template body is empty but JIRA has content"}

    ratio = round(difflib.SequenceMatcher(None, jn, dn).ratio(), 3)
    if ratio >= 0.92:
        assessment = "✅ Texts are nearly identical"
    elif ratio >= 0.75:
        assessment = "⚠️ Texts are similar but differ — AI should verify intent matches"
    else:
        assessment = "❌ Texts differ significantly — likely FAIL unless template variables explain it"

    # Short diff snippet for context (max 6 lines)
    jlines = _re.findall(r'.{1,100}', jn)[:5]
    dlines = _re.findall(r'.{1,100}', dn)[:5]
    diff   = list(difflib.unified_diff(jlines, dlines, lineterm="", n=1))[:8]

    return {
        "similarity_ratio": ratio,
        "pre_verdict":      "PASS" if ratio >= 0.75 else "FAIL",
        "assessment":       assessment,
        "diff_preview":     "\n".join(diff) if diff else "(no diff)",
    }


def _compute_tag_diff(expected_incl: str, expected_excl: str, api_tag_str: str) -> dict:
    """Pre-compute tag set differences so AI just reads the result."""
    exp_inc = set(_norm_tags_list(expected_incl))
    exp_exc = set(_norm_tags_list(expected_excl))

    actual_lines = _re.split(r'[,\n;]+', str(api_tag_str or ""))
    actual_inc, actual_exc = set(), set()
    for line in actual_lines:
        line = line.strip()
        if not line: continue
        lo = line.lower()
        if _re.match(r'^excl[:.\s]', lo) or "exclude" in lo[:10]:
            tag = _re.sub(r'^excl[:\s.]+|^exclude[:\s]+', '', line, flags=_re.I).strip()
            if tag: actual_exc.add(tag)
        else:
            actual_inc.add(line)

    missing_inc = sorted(exp_inc - actual_inc)
    extra_inc   = sorted(actual_inc - exp_inc) if exp_inc else []
    missing_exc = sorted(exp_exc - actual_exc)
    extra_exc   = sorted(actual_exc - exp_exc)
    all_match   = not (missing_inc or missing_exc or extra_exc)

    issues = []
    if missing_inc: issues.append(f"missing include tags: {missing_inc}")
    if extra_inc:   issues.append(f"unexpected include tags: {extra_inc}")
    if missing_exc: issues.append(f"missing exclude tags: {missing_exc}")
    if extra_exc:   issues.append(f"unexpected exclude tags: {extra_exc}")

    return {
        "expected_include": sorted(exp_inc),
        "expected_exclude": sorted(exp_exc),
        "actual_include":   sorted(actual_inc),
        "actual_exclude":   sorted(actual_exc),
        "missing_include":  missing_inc,
        "extra_include":    extra_inc,
        "missing_exclude":  missing_exc,
        "extra_exclude":    extra_exc,
        "pre_verdict":      "PASS" if all_match else "FAIL",
        "note":             "✅ All tags match" if all_match else "❌ " + "; ".join(issues),
    }


_SHORT_URL_DOMAINS = frozenset({
    "aldi.co", "aldi.de", "bit.ly", "tinyurl.com", "shorturl.at",
    "t.co", "goo.gl", "rewe.de", "kaufland.de", "lidl.de", "edeka.de",
    "netto.de", "penny.de", "rossmann.de", "dm.de",
})


def _url_domain(url: str) -> str:
    """Extract lowercase domain from a URL, stripping www."""
    try:
        from urllib.parse import urlparse
        return urlparse(url.lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _is_short_url(url: str) -> bool:
    """Return True if this URL is from a known short-URL / retailer domain."""
    d = _url_domain(url)
    return d in _SHORT_URL_DOMAINS


def _compute_url_diff(jira_urls: list, api_urls: list) -> dict:
    """
    Filter image CDN URLs and compute CTA-only URL diff.

    SAME-DOMAIN SHORT URL RULE:
    If all JIRA CTA URLs are present in the API, any additional API URLs from
    the same domain as a JIRA URL are NOT a mismatch — they are URLs for other
    sendout periods / stores and should be ignored.  Only flag truly foreign
    domains that were not mentioned in JIRA at all.
    """
    jira_cta = [u for u in jira_urls if not _is_image_url(u)]
    api_cta  = [u for u in api_urls  if not _is_image_url(u)]
    img_cnt  = len([u for u in api_urls if _is_image_url(u)])

    missing = [u for u in jira_cta if u not in api_cta]
    extra   = [u for u in api_cta  if u not in jira_cta]

    # Filter "extra" URLs that are same-domain short URLs when the JIRA URL
    # from that domain is already present (different code, same service).
    jira_domains = {_url_domain(u) for u in jira_cta}
    extra_real = [
        u for u in extra
        if not (_is_short_url(u) and _url_domain(u) in jira_domains)
    ]
    same_domain_ignored = [u for u in extra if u not in extra_real]

    ok = not (missing or extra_real)

    note_parts = []
    if ok:
        note_parts.append("✅ CTA URLs match")
    else:
        if missing:   note_parts.append(f"missing from API: {missing}")
        if extra_real: note_parts.append(f"unexpected in API: {extra_real}")
    if same_domain_ignored:
        note_parts.append(
            f"ℹ️ ignored {len(same_domain_ignored)} same-domain short URL(s) as equivalent: {same_domain_ignored}"
        )

    return {
        "jira_cta_urls":           jira_cta,
        "api_cta_urls":            api_cta,
        "image_urls_ignored":      img_cnt,
        "missing_from_api":        missing,
        "extra_in_api":            extra_real,
        "same_domain_ignored":     same_domain_ignored,
        "pre_verdict":             "PASS" if ok else "FAIL",
        "note":                    " | ".join(note_parts) if note_parts else "✅ CTA URLs match",
    }


def _build_report_from_structured(audit: AuditOutput) -> str:
    """Generate a human-readable markdown report from structured AuditOutput."""
    EMOJI = {"PASS": "✅", "FAIL": "❌", "NA": "🔕"}
    NAMES = {
        "scheduling": "CHECK 1 — SCHEDULING",
        "copy":       "CHECK 2 — COPY",
        "footer":     "CHECK 3 — FOOTER",
        "cta":        "CHECK 4 — CTA BUTTONS & LINKS",
        "tags":       "CHECK 5 — TAGS / AUDIENCE FILTERS",
        "images":     "CHECK 6 — IMAGES / CAROUSEL",
    }
    checks = [
        ("scheduling", audit.scheduling),
        ("copy",       audit.copy),
        ("footer",     audit.footer),
        ("cta",        audit.cta),
        ("tags",       audit.tags),
        ("images",     audit.images),
    ]
    lines = []
    for key, chk in checks:
        e = EMOJI.get(chk.verdict, "?")
        lines.append(f"### {e} {NAMES[key]}")
        lines.append(f"**Expected:** {chk.expected}")
        lines.append(f"**Actual:** {chk.actual}")
        lines.append(f"**Verdict:** {e} {chk.verdict} — {chk.reason}")
        lines.append("")

    # Summary table
    lines.append("### SUMMARY TABLE")
    lines.append("| Check | Verdict |")
    lines.append("|-------|---------|")
    label_map = {
        "scheduling": "1 Scheduling",
        "copy":       "2 Copy",
        "footer":     "3 Footer",
        "cta":        "4 CTA",
        "tags":       "5 Tags",
        "images":     "6 Images",
    }
    for key, chk in checks:
        lines.append(f"| {label_map[key]} | {EMOJI.get(chk.verdict, '?')} {chk.verdict} |")

    ov_e = "✅" if audit.overall == "PASS" else "❌"
    lines.append("")
    lines.append(f"**Overall: {ov_e} {audit.overall}**")
    lines.append(f"**Confidence: {audit.confidence}%** — {audit.confidence_reason}")
    return "\n".join(lines)


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

    # ── Pre-compute diffs so AI confirms results rather than discovering them ──
    _jira_url_list = extract_urls(jira_all_text)
    _sched_diff = _compute_scheduling_diff(
        str(jira.get("date", "")),
        api_date or str(jira.get("date", "")),
    )
    _text_diff = _compute_text_similarity(
        str(jira.get("description", "")),
        tmpl_body,
    )
    _tag_diff = _compute_tag_diff(expected_incl, expected_excl, api_tag_str)
    _url_diff = _compute_url_diff(_jira_url_list, list(filter(None, api_urls)))

    return {
        "JIRA_Intent": {
            "Date": str(jira.get("date", "")),
            "Timezone": str(jira.get("timezone", "")),
            "Text_Description": str(jira.get("description", "")),
            "JIRA_Parsed_Carousel": jira.get("parsed_carousel"),
            "Footer": str(jira.get("footer_text", "")),
            "CTA_Button_Text": str(jira.get("cta_button", "")),
            "JIRA_All_URLs": ", ".join(_jira_url_list),
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
        "Precomputed_Diffs": {
            "scheduling": _sched_diff,
            "copy_text":  _text_diff,
            "tags":       _tag_diff,
            "cta_urls":   _url_diff,
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
    examples: list[dict] | None = None,
) -> dict:
    """
    Call Gemini with the comparison data and optional images.
    Returns a dict with keys: audit_report, jira_extracted_urls, api_extracted_urls.
    On parse failure, audit_report contains the raw text.
    """
    from ai_examples import format_examples_for_prompt
    client = genai.Client(api_key=api_key)

    prompt = _AUDIT_PROMPT_TEMPLATE.format(
        client_name=client_name,
        comparison_json=json.dumps(comparison_data, indent=2),
        examples_block=format_examples_for_prompt(examples or []),
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
                "ABSOLUTE RULE 2: You MUST evaluate ALL SIX checks in the exact order given. "
                "Each of the six checks (scheduling, copy, footer, cta, tags, images) must have "
                "a verdict ('PASS', 'FAIL', or 'NA'), a reason, expected value, and actual value. "
                "Never merge checks. Never skip a check. "
                "An empty or missing check field = invalid audit that will be rejected."
            ),
            response_mime_type="application/json",
            response_schema=AuditOutput,
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
                "ENGLISH ONLY. Produce the full JSON audit now, entirely in English:"
            )
            _retry_contents = [_lang_fix] + list(contents)
            raw_text = client.models.generate_content(
                model=model_name,
                contents=_retry_contents,
                config=_config,
            ).text

        # ── Structured output: parse directly into AuditOutput Pydantic model ──
        audit = AuditOutput.model_validate_json(raw_text)
        report = _build_report_from_structured(audit)
        if _is_audit_error(report):
            return {
                "audit_report": report,
                "structured": audit.model_dump(),
                "confidence": audit.confidence,
                "confidence_reason": audit.confidence_reason,
                "jira_extracted_urls": [],
                "api_extracted_urls": [],
                "error": True,
            }
        return {
            "audit_report": report,
            "structured": audit.model_dump(),
            "confidence": audit.confidence,
            "confidence_reason": audit.confidence_reason,
            "jira_extracted_urls": [],
            "api_extracted_urls": [],
        }
    except Exception as exc:
        from pydantic import ValidationError
        err_str = str(exc)
        # Pydantic validation failure — structured output mismatch
        if isinstance(exc, ValidationError):
            logger.error("AI audit Pydantic validation failed: %s", exc)
            return {
                "audit_report": f"AI audit generated, but structured parsing failed: {exc}\n\nRaw output:\n{raw_text}",
                "jira_extracted_urls": [],
                "api_extracted_urls": [],
                "error": True,
            }
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

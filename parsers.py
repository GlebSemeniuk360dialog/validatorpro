"""
parsers.py — JIRA description / carousel parsing.
No Streamlit, no HTTP — pure text transformation.
"""

import re

from utils import clean_jira_markdown, normalize_nahkauf_placeholders

# Regex that matches slide/slider section headers
_SLIDE_SPLIT_RE = re.compile(r"(?i)\**(?:Slide|Slider)(?:\s*\d+)?\**[\s:-]+")


# ---------------------------------------------------------------------------
# Internal building blocks
# ---------------------------------------------------------------------------

def _split_into_parts(description: str) -> list[str]:
    return _SLIDE_SPLIT_RE.split(description) if description else []


def _extract_btn_from_part(part: str) -> str:
    """Pull CTA/button text from a slide section, stripping link lines."""
    m = re.search(
        r"(?:CTA:|Call-to-Action:|Button:)\s*(.*)",
        part,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return ""
    raw = clean_jira_markdown(m.group(1).strip())
    return re.sub(r"(?i)(?:Link|URL):?.*", "", raw).strip()


# ---------------------------------------------------------------------------
# Public parsers
# ---------------------------------------------------------------------------

def parse_generic_carousel(description: str) -> dict | None:
    """
    Generic slide-block parser.
    Returns {"intro": str, "cards": [{"body": str, "btn": str}]} or None.
    """
    parts = _split_into_parts(description)
    if len(parts) <= 1:
        return None

    intro = clean_jira_markdown(parts[0].replace("Intro:", "").strip())
    cards: list[dict] = []

    for part in parts[1:]:
        body_m = re.search(
            r"(.*?)(?:CTA:|Call-to-Action:|Button:|$)",
            part,
            re.DOTALL | re.IGNORECASE,
        )
        body = clean_jira_markdown(body_m.group(1).strip()) if body_m else clean_jira_markdown(part.strip())
        btn = _extract_btn_from_part(part)
        cards.append({"body": body, "btn": btn})

    return {"intro": intro, "cards": cards}


def parse_nahkauf_carousel(description: str) -> dict | None:
    """Nahkauf-specific carousel parser (Text/Bild/CTA structure)."""
    parts = _split_into_parts(description)
    if len(parts) <= 1:
        return None

    intro = clean_jira_markdown(parts[0].replace("Main Slide:", "").strip())
    cards: list[dict] = []

    for part in parts[1:]:
        body_m = re.search(r"(?i)Text:\s*(.*?)(?:Bild:|Call-to-Action|CTA|$)", part, re.DOTALL)
        btn_m = re.search(r"(?i)(?:Call-to-Action.*?|CTA):\s*(.*?)(?:CTA Link:|Link:|$)", part, re.DOTALL)

        body = normalize_nahkauf_placeholders(
            clean_jira_markdown(body_m.group(1) if body_m else part)
        )
        btn = clean_jira_markdown(btn_m.group(1).strip() if btn_m else "")
        cards.append({"body": body, "btn": btn})

    return {"intro": intro, "cards": cards}


def parse_jira_carousel_form(description: str) -> dict | None:
    """
    Parse the structured 'Main Body Text / Card Body Texts / Card Button Texts' form layout.
    Returns None if the description doesn't look like this format.
    """
    if not description:
        return None
    if "Main Body Text" not in description and "Card Body Texts" not in description:
        return None

    # Intro
    intro_m = re.search(
        r"(?i)Main Body Text:?\*?(.*?)(?:Number of cards|Card Images|Card Body Texts)",
        description,
        re.DOTALL,
    )
    intro = ""
    if intro_m:
        raw = intro_m.group(1).strip()
        raw = re.sub(r"(?i)May include placeholders.*?Maximum - \d+ characters", "", raw).strip()
        intro = clean_jira_markdown(raw)

    def _extract_card_sections(section_name: str, stop_after: str = "") -> list[str]:
        stop_pat = stop_after or "Card Button URLs"
        m = re.search(
            rf"(?i){re.escape(section_name)}:?\*?(.*?)(?:{stop_pat}|$)",
            description,
            re.DOTALL,
        )
        if not m:
            return []
        matches = re.findall(
            r"(?i)Card\s*\d+\s*:\s*(.*?)(?=(?:Card\s*\d+\s*:|$))",
            m.group(1),
            re.DOTALL,
        )
        return [clean_jira_markdown(x.strip().rstrip(";").strip()) for x in matches]

    bodies = _extract_card_sections("Card Body Texts", stop_after="Card Button Texts")
    btns   = _extract_card_sections("Card Button Texts", stop_after="Card Button URLs")
    # Extract per-card URLs from "Card Button URLs" section
    urls: list[str] = []
    urls_m = re.search(r"(?i)Card Button URLs:?\*?(.*?)$", description, re.DOTALL)
    if urls_m:
        raw_urls = re.findall(
            r"(?i)Card\s*\d+\s*:\s*(https?://\S+)",
            urls_m.group(1),
        )
        urls = [u.rstrip(".,;)") for u in raw_urls]

    if not bodies and not btns:
        return None

    n = max(len(bodies), len(btns), len(urls))
    cards = [
        {
            "body": bodies[i] if i < len(bodies) else "",
            "btn":  btns[i]   if i < len(btns)   else "",
            "url":  urls[i]   if i < len(urls)    else "",
        }
        for i in range(n)
    ]
    return {"intro": intro, "cards": cards, "urls": urls}


def parse_penny_at_carousel(description: str) -> dict | None:
    """
    Parser for Penny AT carousel form format:
        Main Body Text: ...
        Number of cards: 4
        Card 1: Title Text: ... CTA: ... URL: ...
        Card 2: Title Text: ... CTA: ... URL: ...
    """
    if not description:
        return None

    # Extract main body text
    intro_m = re.search(r"Main Body Text[:\s*\n]+(.*?)(?:\nNumber of cards|\nCard |\Z)", description, re.DOTALL | re.IGNORECASE)
    intro = clean_jira_markdown(intro_m.group(1).strip()) if intro_m else ""

    # Extract cards — each starts with "Card N:"
    card_blocks = re.split(r"\nCard\s+\d+\s*:", description)
    if len(card_blocks) <= 1:
        return None

    cards = []
    for block in card_blocks[1:]:
        # Extract text body
        text_m = re.search(r"Text[:\s]+(.*?)(?:CTA:|URL:|$)", block, re.DOTALL | re.IGNORECASE)
        body = clean_jira_markdown(text_m.group(1).strip()) if text_m else ""
        # Extract CTA
        cta_m = re.search(r"CTA[:\s]+(.*?)(?:URL:|$)", block, re.DOTALL | re.IGNORECASE)
        btn = clean_jira_markdown(cta_m.group(1).strip()) if cta_m else ""
        # Extract URL
        url_m = re.search(r"URL[:\s]+(https?://\S+)", block, re.IGNORECASE)
        url = url_m.group(1).strip() if url_m else ""
        cards.append({"body": body, "btn": btn, "url": url})

    if not cards:
        return None
    return {"intro": intro, "cards": cards}


def pick_carousel_parser(description: str, client: str) -> dict | None:
    """
    Select and run the appropriate carousel parser for *client*.
    Falls back through progressively more generic parsers.
    """
    client_lower = client.lower()

    # Penny AT uses its own card form format
    if "penny" in client_lower and ("austria" in client_lower or "at" in client_lower or "öster" in client_lower):
        result = parse_penny_at_carousel(description)
        if result:
            return result

    # Structured form format takes priority for all clients
    result = parse_jira_carousel_form(description)
    if result:
        return result

    if "Nahkauf" in client:
        return parse_nahkauf_carousel(description) or parse_generic_carousel(description)

    # REWE and all others use the generic parser
    return parse_generic_carousel(description)

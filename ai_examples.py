"""
ai_examples.py — Few-shot example library for AI audits.

Examples are stored in ai_examples.json alongside this file.
Each example records a real past check (or a manually crafted one)
with the correct verdict, so Gemini can learn by analogy.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

EXAMPLES_PATH = Path(__file__).parent / "ai_examples.json"

# Which comparison_data fields are relevant to each check type.
# Format: "Section.Field" — nested with dot notation.
_CHECK_FIELDS: dict[str, list[str]] = {
    "scheduling": [
        "JIRA_Intent.Date",
        "JIRA_Intent.Timezone",
        "DMA_API_Setup.Date_Time",
        "Precomputed_Diffs.scheduling",
    ],
    "copy": [
        "JIRA_Intent.Text_Description",
        "JIRA_Intent.JIRA_Parsed_Carousel",
        "DMA_API_Setup.Template_Body_Intro",
        "DMA_API_Setup.Template_Carousel_Cards",
        "Precomputed_Diffs.copy_text",
    ],
    "footer": [
        "JIRA_Intent.Footer",
        "DMA_API_Setup.Template_Footer",
    ],
    "cta": [
        "JIRA_Intent.CTA_Button_Text",
        "JIRA_Intent.JIRA_All_URLs",
        "DMA_API_Setup.Template_Buttons",
        "DMA_API_Setup.API_URLs_Configured",
        "Precomputed_Diffs.cta_urls",
    ],
    "tags": [
        "G_Sheet_Intent.Include_Tags",
        "G_Sheet_Intent.Exclude_Tags",
        "DMA_API_Setup.API_Tags_And_Filters",
        "Precomputed_Diffs.tags",
    ],
    "images": [
        "JIRA_Intent.Text_Description",
        "DMA_API_Setup.Template_Carousel_Cards",
    ],
}

CheckType = Literal["scheduling", "copy", "footer", "cta", "tags", "images"]
VerdictType = Literal["PASS", "FAIL", "NA"]


# ── Snippet extraction ────────────────────────────────────────────────────────

def extract_snippet(comparison_data: dict, check: str) -> dict:
    """
    Extract only the fields from comparison_data that are relevant to
    a specific check type. Keeps examples small and focused.
    """
    fields = _CHECK_FIELDS.get(check, [])
    snippet: dict = {}

    for field_path in fields:
        parts = field_path.split(".")
        src = comparison_data
        # Walk down to the section
        for part in parts[:-1]:
            if not isinstance(src, dict) or part not in src:
                src = None
                break
            src = src[part]
        if src is None:
            continue
        leaf = parts[-1]
        if not isinstance(src, dict) or leaf not in src:
            continue
        # Build the same nested structure in snippet
        dest = snippet
        for part in parts[:-1]:
            dest = dest.setdefault(part, {})
        dest[leaf] = src[leaf]

    return snippet


# ── Prompt formatting ─────────────────────────────────────────────────────────

def format_examples_for_prompt(examples: list[dict]) -> str:
    """
    Format a list of example dicts into a prompt block.
    Returns an empty string if there are no examples.
    """
    if not examples:
        return ""

    lines = [
        "══════════ FEW-SHOT EXAMPLES — STUDY THESE BEFORE AUDITING ══════════",
        "These are real past audits with confirmed correct verdicts.",
        "Use them as reference for how to apply the rules to similar cases.",
        "",
    ]

    for i, ex in enumerate(examples, 1):
        check   = ex.get("check", "?").upper()
        verdict = ex.get("verdict", "?")
        scenario = ex.get("scenario", "")
        client   = ex.get("client", "any")

        lines.append(f"── EXAMPLE {i}  [{check} — {verdict}]  {scenario}")
        if client and client != "any":
            lines.append(f"   Client: {client}")

        snippet = ex.get("input_snippet")
        if snippet:
            lines.append("   Relevant data:")
            lines.append(json.dumps(snippet, indent=4, ensure_ascii=False))

        out = ex.get("correct_output", {})
        if out:
            lines.append(f"   ✔ Correct verdict : {out.get('verdict', '?')}")
            lines.append(f"     reason          : \"{out.get('reason', '')}\"")
            lines.append(f"     expected        : \"{out.get('expected', '')}\"")
            lines.append(f"     actual          : \"{out.get('actual', '')}\"")
        lines.append("")

    lines.append("══════════ END EXAMPLES — NOW AUDIT THE REAL CASE BELOW ══════════")
    lines.append("")
    return "\n".join(lines)


# ── Library class ─────────────────────────────────────────────────────────────

class ExamplesLibrary:
    """
    Manages the ai_examples.json file.
    Instantiate once at app startup and reuse.
    """

    def __init__(self, path: Path | str = EXAMPLES_PATH):
        self.path = Path(path)
        self._examples: list[dict] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.exists():
            logger.info("ai_examples.json not found — starting with empty library")
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._examples = data.get("examples", [])
            logger.info("Loaded %d examples from %s", len(self._examples), self.path)
        except Exception as exc:
            logger.error("Failed to load ai_examples.json: %s", exc)
            self._examples = []

    def _save(self) -> None:
        try:
            self.path.write_text(
                json.dumps({"examples": self._examples}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed to save ai_examples.json: %s", exc)

    def reload(self) -> None:
        """Re-read the file from disk (useful after external edits)."""
        self._load()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get_all(self) -> list[dict]:
        return list(self._examples)

    def get_by_id(self, ex_id: str) -> dict | None:
        return next((e for e in self._examples if e.get("id") == ex_id), None)

    def add(self, example: dict) -> str:
        """
        Add a new example. Auto-assigns id and added_at.
        Returns the new id.
        """
        ex_id = uuid.uuid4().hex[:8]
        entry = {
            "id":          ex_id,
            "active":      True,
            "added_at":    date.today().isoformat(),
            **{k: v for k, v in example.items() if k not in ("id", "added_at")},
        }
        self._examples.append(entry)
        self._save()
        logger.info("Added example %s (%s / %s)", ex_id, entry.get("client"), entry.get("check"))
        return ex_id

    def update(self, ex_id: str, fields: dict) -> bool:
        """Update specific fields of an example. Returns True if found."""
        for ex in self._examples:
            if ex.get("id") == ex_id:
                # Protect id and added_at from being overwritten
                fields.pop("id", None)
                fields.pop("added_at", None)
                ex.update(fields)
                self._save()
                return True
        return False

    def delete(self, ex_id: str) -> bool:
        """Delete an example by id. Returns True if found."""
        before = len(self._examples)
        self._examples = [e for e in self._examples if e.get("id") != ex_id]
        if len(self._examples) < before:
            self._save()
            return True
        return False

    # ── Selection ─────────────────────────────────────────────────────────────

    def select_for_audit(
        self,
        client_name: str,
        max_examples: int = 3,
    ) -> list[dict]:
        """
        Pick the most relevant active examples for a given client audit.

        Scoring:
          2 — exact client match
          1 — client = "any" (cross-client generic example)
          0 — different client (excluded)

        After scoring, we select greedily:
          - Prefer higher score
          - Avoid duplicating the same (check, verdict) pair
          - Stop at max_examples
        """
        client_lower = client_name.lower().strip()
        active = [e for e in self._examples if e.get("active", True)]

        def _score(ex: dict) -> int:
            ex_client = str(ex.get("client", "any")).lower().strip()
            if ex_client == "any":
                return 1
            # Partial match (e.g. "aldi sued" in "aldi sued standard")
            if ex_client == client_lower:
                return 2
            if ex_client in client_lower or client_lower in ex_client:
                return 2
            return 0

        scored = [(s, ex) for ex in active if (s := _score(ex)) > 0]
        # Sort: higher score first, then FAIL before PASS (failures teach more)
        scored.sort(key=lambda t: (-t[0], 0 if t[1].get("verdict") == "FAIL" else 1))

        selected: list[dict] = []
        seen: set[tuple] = set()

        for _, ex in scored:
            key = (ex.get("check", "?"), ex.get("verdict", "?"))
            if key not in seen:
                selected.append(ex)
                seen.add(key)
            if len(selected) >= max_examples:
                break

        logger.debug(
            "Selected %d/%d examples for client '%s'",
            len(selected), len(active), client_name,
        )
        return selected

# AI Audit Quality Improvements — Brainstorm

## Round 1 — Initial Ideas (prioritised)

| # | Idea | Effort | Impact |
|---|---|---|---|
| 1 | Pre-compute scheduling diff in Python (pass minutes, not raw timestamps) | Low | High |
| 2 | Structured JSON output via Pydantic schema (zero parsing failures) | Medium | Very High |
| 3 | Slim down comparison data — strip fields irrelevant to any check | Low | Medium |
| 4 | Few-shot examples in prompt (1-2 good PASS + FAIL per check type) | Low | Medium |
| 5 | Override logging + dashboard tracking of most-overridden checks | Medium | Medium |
| 6 | Pre-compute tag diff explicitly before sending to AI | Medium | High |

## Root causes identified

- AI finding the diff itself (cognitive load → misses subtle differences or hallucinates)
- Timezone math is ambiguous in natural language → scheduling wrong verdicts
- Raw DMA API payload is noisy (image CDN URLs, internal IDs, webhook configs)
- Markdown parsing is fragile (~5% JSON parse failures)
- No feedback loop when humans override AI verdicts

---

## Round 2 — Implemented ✅

| # | Idea | Status |
|---|---|---|
| 1 | Pre-compute scheduling diff in Python (diff_minutes, within_40min_tolerance) | ✅ Done — `_compute_scheduling_diff` |
| 2 | Structured JSON output via Pydantic schema (`AuditOutput`, `CheckVerdict`) | ✅ Done — `response_schema=AuditOutput` in `GenerateContentConfig` |
| 3 | Slim down cognitive load — strip image CDN URLs before AI sees them | ✅ Done — `_compute_url_diff` filters image URLs server-side |
| 4 | Pre-compute text similarity ratio via `difflib.SequenceMatcher` | ✅ Done — `_compute_text_similarity` |
| 5 | Pre-compute tag set diff (missing/extra include and exclude) | ✅ Done — `_compute_tag_diff` |
| 6 | All diffs injected as `Precomputed_Diffs` in comparison JSON | ✅ Done — `build_comparison_data` now includes this block |

### How it works end-to-end

1. `build_comparison_data` calls the four helper functions and adds a `Precomputed_Diffs`
   block to the JSON sent to Gemini.
2. The prompt instructs the AI to **confirm** the pre-computed results rather than discover them,
   reducing cognitive load and scheduling timezone confusion.
3. `run_ai_audit` passes `response_schema=AuditOutput` + `response_mime_type="application/json"`
   to Gemini — the model is forced to return a valid `AuditOutput` JSON, eliminating parse failures.
4. `_build_report_from_structured` converts the Pydantic object back to the standard
   markdown format (`### ✅/❌ CHECK N — …`) so all downstream callers (`bulk_validator.py`,
   `server.py`) work with zero changes.
5. `thinking_budget=0` on Flash models keeps latency low for bulk audits.

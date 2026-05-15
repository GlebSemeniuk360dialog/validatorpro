# Iconography — Validator Pro

The product ships **no icon set**. Status meaning is carried by system emoji + Unicode glyphs. This file is the canonical mapping.

## Status glyphs (always emoji)

| Glyph | Class      | Color (dark)   | Meaning                                      |
|-------|------------|----------------|----------------------------------------------|
| ✅    | `.vp-pass` | `#00d4aa`      | Check passed / matched                       |
| ❌    | `.vp-fail` | `#ff4d6d`      | Check failed / mismatched                    |
| ⚠️    | `.vp-warn` | `#ffb547`      | Warning / needs review                       |
| 🔴    | —          | (intrinsic)    | Severity: critical (orphan scanner)          |
| 🟡    | —          | (intrinsic)    | Severity: minor                              |
| 🟢    | —          | (intrinsic)    | Severity: ok                                 |
| 🔵    | —          | (intrinsic)    | Severity: info / automated                   |

When emoji appear inside the `.vp-ai-report` they are wrapped in colored `<span>`s so the glyph's intrinsic color is overridden by the status palette. Outside that report, the intrinsic emoji color is used as-is.

## Action glyphs (Unicode)

| Glyph | Used on                  |
|-------|--------------------------|
| ▶     | "Load ticket", "Validate"|
| ✕     | "Clear", "Clear selection"|
| ←     | "Back"                   |
| →     | "Sign in →"              |
| ›     | Slide accordion chevron (rotates 90° when open) — written as `&#x203A;` |

## Section prefixes (emoji)

These are page-level / section-level prefixes that label *what kind of thing* a control acts on. They are NOT decoration — every one corresponds to a domain concept.

| Glyph | Concept            |
|-------|--------------------|
| ⚡    | The product itself (also the favicon) |
| 🎯    | Client context     |
| 🎫    | JIRA ticket        |
| 📅    | G-Sheet schedule   |
| 📋    | Picker / list      |
| 🚀    | DMA sendout / launch |
| 🤖    | AI audit           |
| 🔄    | Refresh            |
| 🔍    | Search / inspect   |
| 🔒    | Auth / lockout     |
| ⚠️    | Orphan scanner / warning |

## Rules

1. **Never add a new emoji** without a clear functional meaning. Decorative emoji are out of style.
2. **Never invent SVG icons.** If something needs a real icon, use **Lucide** (CDN: `https://unpkg.com/lucide@latest`) and document the choice. Match stroke-only style, 1.5px weight.
3. **Never use icon fonts** (Font Awesome, Material Icons). Not in the system.
4. **Logo / mark**: the ⚡ emoji is the favicon. The `validator-mark.svg` in this folder is a non-source mark suggestion, in case a real logo file is needed.

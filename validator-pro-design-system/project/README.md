# Validator Pro — Design System (v2 · tech futurist)

A design system extracted from **360Dialog Sendout Validator Pro**, the internal Streamlit-based tool used by the 360Dialog operations team to validate WhatsApp Business sendouts before they ship to retail clients (ALDI, Kaufland, REWE, PENNY, Migros, TUI, etc.).

The system is small, opinionated, and deeply technical-looking. It's built for operators who spend hours inside it cross-referencing JIRA tickets against the DMA API and a Google Sheet of scheduled sendouts. Every visual decision serves *information density* and *quick scanning of pass/fail status*.

> **v2 push (May 2026).** The original system was already terse and dashboard-y; v2 sharpens it toward a futurist / HUD register. Specifically: switched to **Space Grotesk + JetBrains Mono**, tightened the radius family (cards `10→6`, controls `8→4`, pills `→999`), added an **electric-cyan accent** for live-data signals, introduced **HUD corner brackets**, **status LEDs with glow**, **dashed accent dividers**, **scanline overlay** and **telemetry-style readouts**. Brand indigo and the four status colors are unchanged — only the surrounding geometry, motifs and type pair shifted.

> **Brand context note.** The pasted project description names the company "Gleb Inc". The actual codebase is owned by Gleb Semeniuk at 360Dialog and the product is "Sendout Validator Pro" (a.k.a. "360Dialog Validator Pro"). This design system documents the visual identity of the Validator Pro product itself — that's the only consistent visual surface present in the source.

---

## Sources

- **Codebase** — `Claude/` (mounted local folder)
  - `app.py` — Streamlit page setup, tabs, queue, control panel, validation runner. `st.set_page_config(page_title="360Dialog Validator Pro", layout="wide", page_icon="⚡")`
  - `ui_renderer.py` — the canonical visual layer. Contains `STREAMLIT_DARK_CSS`, `STREAMLIT_LIGHT_CSS`, `COMPONENT_CSS`, `COMPONENT_CSS_LIGHT`. **All color, spacing, type and radius values in this design system were lifted from these constants.**
  - `config.py` — client config (account_id, filters, timezones) for ~30 retail brands the validator runs against.
  - `ai_audit.py`, `bulk_validator.py`, `parsers.py`, `schedule.py`, `features.py`, `api_client.py`, `utils.py` — business logic.
  - `.streamlit/config.toml` — `base = "light"` (Streamlit chrome default; the app overrides to dark via injected CSS unless `dark_mode=False`).

No Figma file or external brand book was attached. The visual identity here is entirely derived from the implemented CSS.

---

## Product context

**Sendout Validator Pro** is an internal operations console.

- **Who uses it:** 3 named operators — Gleb Semeniuk, Martina Sesar, Alex Volkonitin (per `_USERS` in `app.py`).
- **What it does:**
  1. Pulls pending WhatsApp sendout JIRA tickets from `360dialog.atlassian.net`.
  2. Cross-references each ticket against (a) the DMA API and (b) a published Google Sheet schedule.
  3. Runs a deterministic "Regular Check" + an LLM-backed "AI Audit" (Gemini 2.5 Pro) comparing template body text, button copy, footer, URLs, leaflet tags, carousel slide images and RCS card content.
  4. Surfaces orphan sendouts (configured in DMA but missing from JIRA/G-Sheet), bulk-validates queues, pings a Slack webhook on failure, writes audit status back to JIRA.
- **Surfaces:**
  - Top-level tabs: `Validator`, `Orphan Scanner`, `Dashboard` (`app.py:2513`).
  - Within `Validator`: sticky sub-nav with `Setup`, `Content`, `Visuals`, `AI` panels (the `.vp-nav` component).
  - Sidebar: account info, JIRA Field Inspector toggle, G-Sheet refresh, cache clear, Slack webhook expander.
  - Login screen with username + password + brute-force lockout.

---

## Visual identity in one paragraph

A near-black indigo ground (`#0d0f18`), single-radius cards (`10px`) outlined with a single near-invisible hairline (`#1e2235`), DM Sans for everything that isn't a value, DM Mono for everything that is. The only chromatic note is a confident electric indigo (`#3d4bff`) — used sparingly, only on the primary CTA, the active nav pill, and an accent for slide numbers. Status colors (teal, pink-red, amber, lavender) appear *only* in pass/fail badges and check rows — never in chrome. Tiny all-caps tracked labels (`11px`, `letter-spacing: 0.08–0.1em`) replace decorative headlines. The whole thing reads as a high-information ops dashboard — closer to a terminal than to marketing software.

---

## Index — what's in this folder

```
README.md                    ← you are here
SKILL.md                     ← agent-skill manifest (cross-compatible with Claude Code)
colors_and_type.css          ← all design tokens + element defaults

fonts/                       ← (CDN-only — DM Sans / DM Mono are pulled from Google Fonts)

assets/                      ← logos, marks, icon notes
  validator-mark.svg         ← bespoke mark built from the ⚡ page_icon + brand indigo

preview/                     ← cards rendered into the Design System tab
  type-display.html
  type-overline.html
  type-mono.html
  type-scale.html
  color-surfaces.html
  color-brand.html
  color-semantic.html
  color-foreground.html
  radii.html
  spacing.html
  buttons.html
  badges.html
  tags.html
  check-rows.html
  metric.html
  card.html
  nav-pills.html
  url-row.html
  slide-accordion.html
  diff-block.html
  inputs.html
  ai-report.html
  iconography.html

ui_kits/
  validator-pro/             ← the only product surface in the codebase
    README.md
    index.html               ← interactive clickthrough of the Validator
    Shell.jsx
    Sidebar.jsx
    Topbar.jsx
    NavPills.jsx
    Queue.jsx
    ControlPanel.jsx
    Metric.jsx
    Card.jsx
    CheckRow.jsx
    Badge.jsx
    Tag.jsx
    UrlRow.jsx
    SlideAccordion.jsx
    AIReport.jsx
    DiffBlock.jsx
    Inputs.jsx
    Button.jsx
    Login.jsx
    OrphanScanner.jsx
    Dashboard.jsx
    tokens.js                ← JS mirror of colors_and_type.css
```

There are no slide templates in the source, so `slides/` is intentionally omitted.

---

## CONTENT FUNDAMENTALS

Copy in Validator Pro is **terse, technical, second-person-imperative, lowercase-tolerant**. The voice is "ops engineer talking to ops engineer" — there is no marketing register anywhere.

### Voice & tone
- **Direct imperative.** "Refresh Queue", "Clear", "Validate", "Sign in →", "Retry with new Sendout ID". No "Please", no "Let's", no exclamation points.
- **State of fact, not encouragement.** Status copy reads: `"Pending Tickets: 12"`, `"No upcoming rows in G-Sheet for this client."`, `"Ticket MAS-4141 has changed since last validation — re-run the audit."`
- **Operator-to-operator.** Captions assume technical context: `"Select one ticket to validate · select multiple for bulk actions"`. The user is *you* when addressed, but most strings are objective (no pronoun).
- **Em dash separator** — used heavily to attach a hint to a noun (`"Ticket MAS-4141 has changed since last validation — re-run the audit."`).
- **Middle dot · for inline lists.** `"Audience filter: locale=de · shop_number=001"`.
- **Backticks for identifiers.** Sendout IDs, account IDs, hashes are wrapped in backticks/code style: `` `manual_sid_MAS-4141` ``.

### Casing
- **Sentence case** for actions and headings (`"Pick DMA Sendout"`, `"Pending Sendouts — Next 7 Days"`).
- **ALL CAPS, tracked** for *overline* labels (component titles, card titles, section headers, metric labels). E.g. `"AUDIENCE FILTER"`, `"JIRA DESCRIPTION"`, `"TEXT COMPARISON"`. This is the system's primary typographic motif.
- **PascalCase** in product/tab names (`Validator`, `Orphan Scanner`, `Dashboard`, `Setup`, `Content`, `Visuals`, `AI`).

### Pronouns
- *You* appears very rarely, only in error/instruction strings (`"Please enter the correct ID below and try again."`).
- The default is impersonal: `"Run the AI audit to see results here."` rather than `"You can run..."`.
- *We* is never used.

### Emoji usage — **deliberate and functional**
Emoji are used as **status icons**, not decoration. They appear only:
- As tab/page glyphs: `⚡ Sendout Validator Pro`, `🎯 Client Context`, `🎫 Ticket ID`, `📅 G-Sheet row`, `📋 Pick DMA Sendout`, `🤖 AI Bulk Audit`, `🚀 Validate Pair`, `⚠️ Orphan Sendout Scanner`, `🔍 Validator Pro — Sign in`.
- As **pass/fail/warn markers**: `✅`, `❌`, `⚠️`, `🔴`, `🟡`, `🟢`, `🔵`. These are colored further in CSS (`.vp-pass`, `.vp-fail`, `.vp-warn`).
- As button affordances: `▶ Load ticket`, `✕ Clear`, `🔄 Refresh Queue`, `← Back`, `→ Sign in`.

Never as decoration in body copy. The bar for adding a new emoji is high — it must mean something.

### Example strings (verbatim)
- `"Pending Tickets: 12"`
- `"Select one ticket to validate · select multiple for bulk actions"`
- `"No active pending sendouts found in DMA for ALDI Sued."`
- `"Sendout found: \`abcd1234-…\`"`
- `"⚠️ This sendout has no matching JIRA ticket. It may have been created directly in DMA without going through the approval process."`
- `"❌ AI Audit Failed — Manual Review Required"`
- `"Too many failed attempts. Try again in 247 seconds."`
- `"Click **Scan all accounts** to start."`

---

## VISUAL FOUNDATIONS

### Color
- **Single dark ground.** `#0a0c14` (v2 — pushed slightly cooler/darker than v1's `#0d0f18` for a more HUD-like feel; v1's value lives on as `--bg-app-soft` for diff blocks and the rare "darker child" surface).
- **Two surface layers above ground.** `#11141f` for cards/panels (`--bg-surface-1`), `#181b2c` for inputs and the deepest nested chips (`--bg-surface-2`). A third quasi-surface `#1e2235` doubles as both the default hairline and the inline-code background.
- **One brand color (unchanged).** `#3d4bff` electric indigo. Used in exactly four roles: primary button fill, active nav pill, focus ring, slide-number accent. v2 adds an optional **brand glow** (`box-shadow: 0 0 12px rgba(61, 75, 255, 0.35)`) on the active nav pill and the product mark — used sparingly.
- **Secondary accent: electric cyan `#00e5ff` (NEW in v2).** Used for "live data" signals — HUD corner brackets, scan-line accents, telemetry-readout values, dashed-divider accents, the leading `—` glyph in section headers, status LEDs. Never used on actionable buttons.
- **Status palette (unchanged).** Teal `#00d4aa`, pink-red `#ff4d6d`, amber `#ffb547`, lavender `#a0aaff`.
- **No gradients, anywhere.** No bluish-purple wash, no radial backgrounds. Flat fills + a single 1px hairline. Glows live in `box-shadow` only.
- **Subtle dot grid on the app ground (NEW in v2).** 16px lattice at ~7% opacity. Near-invisible at rest, but adds a hint of "this is a console" texture.

### Type
- **Space Grotesk** for everything UI (v2 — replaces DM Sans). Weights actually used: 400, 500, 600, 700. The Grotesk's slight geometric character + tight `-0.02em` display tracking gives the system a contemporary tech read without tipping into sci-fi.
- **JetBrains Mono** for: card `<pre>` content, URL chips, sendout IDs, code, diff lines, **all overlines and section headers** (v2 changed this — overlines used to be DM Sans, they're now mono for a stronger terminal feel), tag pills, telemetry readouts.
- **A very small type scale.** Body sits at **13px**; everything quieter is **11px** with letter-spacing (`0.12em` standard, `0.16em` for section headers — wider than v1's `0.08/0.1em`). The largest type in normal flow is **18px** (metric / readout values), with **22px** for product titles and **28–32px** reserved for display headings.
- **No webfont files locally** — Space Grotesk + JetBrains Mono are loaded from Google Fonts via `@import` inside `colors_and_type.css`. This is the project's only external dependency.

### Spacing
- **No formal scale** in the codebase — values are picked per component. The de-facto rhythm (`colors_and_type.css` extracts it as `--space-*`):
  - `4 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 20 / 24 / 28`
- Card / metric inner padding: **16px 18px** (asymmetric — slightly wider horizontally).
- Section header margin: **28px top, 12px bottom**.
- Grid gaps: **12px** (3-col), **14px** (2-col).

### Backgrounds & imagery
- **No imagery in chrome.** No background photos, illustrations, patterns, noise, gradients. The product is 100% data — the only images that appear are the actual DMA-fetched sendout previews and JIRA attachment thumbnails, rendered inside `.vp-img-card` containers.
- Image containers have a `#1a1d2e` background and `#0d0f18` letterbox behind the `<img>` (objects fit `contain`, not `cover`).

### Animation
- **Transitions are 0.18–0.2s, never longer.** Defined on `.vp-nav-btn` (`all .18s`), `.vp-slide-arrow` (`transform .2s`).
- **No bounces, no springs, no entrance animation.** No `@keyframes` are defined in the source.
- The only "motion" is the slide-accordion arrow rotating 90° on open (`.vp-slide-arrow.open { transform: rotate(90deg); }`).
- `[data-testid="stProgressBar"]` uses brand indigo as the fill — a horizontal linear fill is the only progress affordance.

### Hover & press states
- **Hover = surface bump.** Nav button hover: background goes from `transparent` → `#1e2235`, text from `#8890b5` → `#e2e4f0`. No color change, just contrast.
- **Active = brand pill.** Active nav buttons fill with `#3d4bff` and the text snaps to white.
- **Primary buttons** lighten on hover (`#3d4bff` → `#5560ff`). Not darker.
- **Accordion headers** get `#1a1d2e` background on hover.
- **Toggle buttons** flip their border color to brand indigo on hover and their text to `#a0aaff`.
- **No press/active state** is defined anywhere — there is no `:active` scale or color shift. Buttons just fire.

### Borders & shadows
- **Every panel gets one** 1px hairline at `#1e2235` (dark) or `#e2e4f0` (light). No double borders, no inset highlights.
- **No box-shadows at all.** The system rejects elevation as a visual cue — depth is communicated through surface color difference only (`bg-app` → `bg-surface-1` → `bg-surface-2`).
- **Status-tinted borders** for badges and check rows: `1px solid rgba(<status>, 0.2)` over a `rgba(<status>, 0.05)` fill.

### Radii
- **Tighter family in v2** — sharper, more terminal-like silhouettes.
  - **6px** for cards/panels (was 10 in v1).
  - **4px** for buttons, inputs, badges (inner pill), check rows, URL chips (was 8 and 6).
  - **8px** for the nav rail wrapper (was 12).
  - **`999px` (pill)** for badge and tag pills — fully circular ends (was 20).
  - **2–3px** for the smallest tokens (inline `<code>`, diff lines).
- No `border-radius: 0` anywhere — there's still a touch of softness, just less of it than v1.

### Transparency & blur
- **No `backdrop-filter` anywhere.** No frosted glass.
- Transparency is used only for **status soft fills** — `00d4aa18` (`rgba(0, 212, 170, .094)`) and friends. These build subtle tinted areas without polluting the design with new opaque colors.
- The **sticky nav** uses `position: sticky` over a solid `#0d0f18` background — opaque, not translucent.

### Layout rules
- **Streamlit `layout="wide"`.** The page fills available width — no `max-width` on the main column.
- **Sticky top nav** at `top: 0`, `z-index: 999`, with a `border-bottom`. It "fills the Streamlit column" — the source comment explicitly notes "NO iframe... breaks scroll".
- **Sidebar fixed.** 12141f background, 1px right border.
- **Grid layouts** are explicit CSS Grid: `.vp-two-col` (1fr 1fr, 14px gap) and `.vp-three-col` (1fr 1fr 1fr, 12px gap). Mobile (`max-width: 640px`) collapses both to 1 column.

### Card anatomy
A card is:
1. `#12141f` background
2. `1px solid #1e2235` border
3. `border-radius: 10px`
4. `padding: 16px 18px`
5. Optional first child: `.vp-card-title` overline (caps, 11px, `#8890b5`, `0.08em` tracking, 10px bottom margin)

There is no shadow, no header bar, no accent stripe. Cards do not have colored left borders. **Cards with colored left borders are explicitly out of style for this system.**

### Color vibe of imagery
- Images are sendout creatives (typically retail leaflet/promotion content) — they're whatever the client provides. The system **does not** filter or tone them. They sit in flat dark-surface containers with no overlay.

---

## ICONOGRAPHY

The product has **no proper icon set**. Status meaning is carried by **system emoji** (`✅ ❌ ⚠️ 🔴 🟡 🟢 🔵`), action affordance by **Unicode glyphs** (`▶ ✕ ← → ›`), and chevrons in the slide accordion by an HTML entity `&#x203A;` (`›`) rotated 90° on open.

### Approach
- **No icon font is loaded.** No Lucide, Heroicons, Material Icons, etc.
- **No SVG icons** are stored in the codebase. There are no `.svg` files in `Claude/`.
- **Emoji are functional, not ornamental.** They communicate pass/fail/warn/info status and act as glyph prefixes for action labels.
- **Unicode arrows are the secondary set.** `▶`, `←`, `→`, `›` (kept as HTML entities for the chevron), `✕` for "close/clear".
- **The page favicon is the ⚡ emoji** — set via `st.set_page_config(..., page_icon="⚡")`. There is no PNG/ICO favicon file. The ⚡ effectively *is* the product mark.

### What we ship in `assets/`
- `validator-mark.svg` — a bespoke mark built from `⚡` rendered in brand indigo on a 10px-rounded square (the system's universal card radius), to give the product a real logo file in case it ever needs one.
- `icons.md` — notes on which emoji/glyph means what, copy-pasteable.

### Recommendation (FLAG)
For new screens that need a real icon set, we recommend **Lucide** — its stroke-only style, 1.5px weight, and slightly rounded joins line up with the system's restrained register. Loading from CDN is fine:

```html
<script src="https://unpkg.com/lucide@latest"></script>
<i data-lucide="check-circle"></i>
```

This is a substitution — there is no icon set in the source codebase. **Confirm with the user before standardizing on Lucide.**

---

## Open caveats

- **No font files were attached.** DM Sans / DM Mono are loaded from Google Fonts. If you need them offline, download them from https://fonts.google.com/specimen/DM+Sans and https://fonts.google.com/specimen/DM+Mono into `fonts/` and add `@font-face` rules.
- **No logo / brand mark exists** in the codebase. The `⚡` emoji acts as the favicon. The bespoke `validator-mark.svg` in `assets/` is our suggestion, not source.
- **No Figma file** was attached. Everything documented here is reverse-engineered from `ui_renderer.py`.
- **No real icon set.** Emoji and Unicode carry all glyph duty; if production needs SVG, plan on Lucide as the substitute.
- **The "Gleb Inc" company name in the prompt doesn't appear in the codebase** — the source is consistently branded "360Dialog Validator Pro". This design system documents the latter.

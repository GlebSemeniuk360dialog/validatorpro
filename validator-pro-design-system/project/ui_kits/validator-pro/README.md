# Validator Pro — UI Kit

A pixel-faithful React recreation of the **360Dialog Sendout Validator Pro** product — the only consistent visual surface in the source codebase. Built directly from `ui_renderer.py`'s CSS constants, not screenshots.

## What's in here

| File | Purpose |
|------|---------|
| `index.html` | Interactive clickthrough — login → main app → drill into a ticket → switch sub-tabs |
| `tokens.js` | JS-side mirror of `colors_and_type.css` (dark theme) |
| `Primitives.jsx` | `Overline`, `SectionHeader`, `Card`, `Badge`, `Tag`, `CheckRow`, `Metric`, `Button`, `Input`, `Select` |
| `Shell.jsx` | `Topbar`, `Sidebar`, `MainTabs`, `NavPill` — top-level app chrome |
| `Login.jsx` | Pre-auth screen with narrow centered column |
| `Queue.jsx` | The pending-tickets table with multi-row selection and bulk-action bar |
| `Validator.jsx` | Drilldown view with sticky sub-nav (Setup · Content · Visuals · AI), text diff, slide accordion, AI report |
| `OrphanScanner.jsx` | Sendout-vs-JIRA-vs-G-Sheet cross-reference with grouped result lists |
| `Dashboard.jsx` | Today's stats + audit log + top failure modes |

## Click path through the demo

1. Land on the **login screen**. Type any of `gleb` / `martina` / `alex` plus any password → "Sign in →".
2. Default tab is **Validator** — the pending ticket queue.
3. Click any row, then **▶ Load ticket** → enter the validator drilldown.
4. Cycle the **Setup · Content · Visuals · AI** sub-tabs.
5. Click **← Back to queue**, then switch the top tabs to **Orphan Scanner** or **Dashboard**.

## What's faithful, what's faked

**Faithful** — these come from `ui_renderer.py` and match exactly:
- Surfaces (`#0d0f18` / `#12141f` / `#1a1d2e` / `#1e2235`).
- Brand indigo `#3d4bff` and its hover `#5560ff`.
- Status palette (`#00d4aa`, `#ff4d6d`, `#ffb547`, `#a0aaff`).
- DM Sans + DM Mono usage (loaded via `colors_and_type.css`).
- 10/8/6/3/20px radius family.
- Overline motif (11px / 600 / `0.08em` tracking / `#8890b5`).
- Card / badge / tag / check-row / nav / metric / slide-accordion / URL chip / diff block / AI report — all 1:1 with the source CSS.
- Copy patterns (em-dashes, middle-dot lists, sentence case, backticked identifiers, status emoji as functional glyphs).

**Faked / cosmetic only** — the kit is not production code:
- Data is hardcoded (`QUEUE_ROWS`, `ORPHANS`, `LOG`).
- The text-diff utility in `Validator.jsx` is a naive line-by-line comparison, not Python's `difflib.Differ`.
- The sidebar's Slack webhook input doesn't post anywhere.
- The Streamlit-specific chrome (`stMetric`, `stExpander`, `stDataFrame`) is recreated in plain React, not actually rendered by Streamlit.

## How to use this kit when designing new Validator screens

1. Import `colors_and_type.css` (gives you tokens + element defaults).
2. Load `tokens.js` so you can reference values in JS-driven styles.
3. Stick to **one radius per role**: 10 for surfaces, 8 for controls, 20 for pills.
4. Never reach for a new color — work from the surfaces + brand + 4-status palette only.
5. The **overline** is your only display hierarchy device. Don't add a new heading scale.
6. Status meaning belongs in the **fill + border tint pair** (`color18` + `color33`), not in a new shape.
7. New action verbs should fit the existing dialect: short, imperative, sentence case, optional emoji prefix.

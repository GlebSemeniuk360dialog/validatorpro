---
name: validator-pro-design
description: Use this skill to generate well-branded interfaces and assets for Validator Pro (360Dialog's internal Sendout Validator), either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

## Quick reference

- **Product**: 360Dialog Sendout Validator Pro — internal ops tool for WhatsApp Business sendout QA.
- **Primary brand color**: `#3d4bff` (electric indigo). Used sparingly — primary button, active nav, focus, slide-num.
- **Surfaces (dark, default)**: app `#0d0f18`, card `#12141f`, input/nested `#1a1d2e`, hairline `#1e2235`.
- **Status**: teal `#00d4aa`, pink-red `#ff4d6d`, amber `#ffb547`, lavender `#a0aaff`.
- **Type**: DM Sans (UI) + DM Mono (values/code), 11/12/13/15/18px scale.
- **Workhorse motif**: 11px ALL CAPS tracked overline, `letter-spacing: 0.08–0.1em`, color `#8890b5`.
- **Radii**: 10px cards, 8px buttons/inputs/badges, 20px pills, 3px tiny tokens.
- **Animation**: only 0.18–0.2s color/transform transitions. No keyframes. No shadows, no gradients.

## Files

- `colors_and_type.css` — drop-in tokens + element defaults (`html`, `body`, `h1–h4`, `code`, etc).
- `README.md` — full visual + content foundations, iconography, caveats.
- `preview/*.html` — design system specimen cards.
- `ui_kits/validator-pro/` — React/JSX recreation of the Validator product. `index.html` is the interactive demo. Use these components as the source of truth for any new Validator surfaces.
- `assets/` — logo/mark + icon usage notes.

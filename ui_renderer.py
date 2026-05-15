"""
ui_renderer.py — Builds the validation results as raw HTML injected via
st.markdown(unsafe_allow_html=True).

Key design decisions:
- NO iframe (st_components.html). Iframes clip content and break scroll.
  Instead we inject directly into Streamlit's page DOM.
- The sticky nav uses position:sticky on a wrapper that fills the Streamlit
  column, so it stays put relative to the page scroll, not an iframe scroll.
- A scoped CSS class prefix (.vp-) prevents leaking styles into Streamlit.
- The full Streamlit app gets a dark theme via STREAMLIT_DARK_CSS.
"""

import base64
import difflib
import html
import json

from config import CLIENT_CONFIGS
from utils import (
    clean_button_text,
    compare_urls_smart,
    extract_all_tags,
    extract_api_urls_advanced,
    extract_urls,
    is_media_url,
)

# ── global dark theme injected once into Streamlit's chrome ───────────────
STREAMLIT_DARK_CSS = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&display=swap');

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
.main, .block-container,
[data-testid="stMainBlockContainer"] {
    background-color: #0d0f18 !important;
    color: #e2e4f0 !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Stack Streamlit columns on mobile */
@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
    [data-testid="stSidebar"] {
        display: none;
    }
    .block-container {
        padding: 1rem 0.75rem !important;
    }
}

[data-testid="stSidebar"],
[data-testid="stSidebarContent"] {
    background-color: #12141f !important;
    border-right: 1px solid #1e2235 !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span { color: #c8cadc !important; }

[data-testid="stHeader"] {
    background-color: #0d0f18 !important;
    border-bottom: 1px solid #1e2235 !important;
}

[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
[data-testid="stHeadingWithActionElements"] h1,
[data-testid="stHeadingWithActionElements"] h2 {
    color: #e2e4f0 !important;
    font-family: 'DM Sans', sans-serif !important;
}

input, textarea,
[data-testid="stTextInput"] input,
[data-baseweb="input"] input {
    background-color: #1a1d2e !important;
    border: 1px solid #2a2d42 !important;
    color: #e2e4f0 !important;
    border-radius: 8px !important;
}
input::placeholder { color: #5a5f7a !important; }

[data-baseweb="select"] > div,
[data-baseweb="select"] input {
    background-color: #1a1d2e !important;
    border-color: #2a2d42 !important;
    color: #e2e4f0 !important;
}
[data-baseweb="popover"] { background: #1a1d2e !important; }
[role="option"] { background: #1a1d2e !important; color: #e2e4f0 !important; }

[data-testid="stButton"] > button {
    background-color: #3d4bff !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
}
[data-testid="stButton"] > button:hover { background-color: #5560ff !important; }

[data-testid="stDataFrame"],
[data-testid="stDataFrameResizable"] {
    background-color: #12141f !important;
    border: 1px solid #1e2235 !important;
    border-radius: 10px !important;
}

[data-testid="stExpander"] {
    background-color: #12141f !important;
    border: 1px solid #1e2235 !important;
    border-radius: 10px !important;
}

[data-testid="stMetric"] {
    background: #12141f !important;
    border: 1px solid #1e2235 !important;
    border-radius: 10px !important;
    padding: 14px 18px !important;
}
[data-testid="stMetricValue"] { color: #e2e4f0 !important; }
[data-testid="stMetricLabel"] { color: #8890b5 !important; }

[data-testid="stAlert"] { border-radius: 8px !important; }

hr { border-color: #1e2235 !important; }

[data-testid="stToast"] {
    background: #1a1d2e !important;
    border: 1px solid #2a2d42 !important;
}

[data-testid="stCaptionContainer"] p { color: #5a5f7a !important; }

/* progress */
[data-testid="stProgressBar"] > div > div { background: #3d4bff !important; }
</style>
"""

# ── scoped component CSS ───────────────────────────────────────────────────
COMPONENT_CSS = """
<style>
/* All rules scoped under .vp- prefix */

.vp-wrap { font-family: 'DM Sans', sans-serif; color: #e2e4f0 !important; }

/* sticky nav */
.vp-nav-wrap {
    position: sticky;
    top: 0;
    z-index: 999;
    background: #0d0f18;
    border-bottom: 1px solid #1e2235;
    padding: 8px 0 8px;
    margin-bottom: 20px;
}
.vp-nav {
    display: flex;
    gap: 4px;
    background: #12141f;
    border: 1px solid #1e2235;
    border-radius: 12px;
    padding: 5px;
    max-width: 600px;
}
.vp-nav-btn {
    flex: 1;
    padding: 9px 12px;
    background: transparent !important;
    color: #8890b5 !important;
    border-radius: 8px;
    cursor: pointer !important;
    user-select: none;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    font-weight: 500;
    transition: all .18s;
    white-space: nowrap;
    pointer-events: auto !important;
    position: relative;
    z-index: 10;
    text-align: center;
    display: flex;
    align-items: center;
    justify-content: center;
}
.vp-nav-btn:hover  { background: #1e2235 !important; color: #e2e4f0 !important; }
.vp-nav-btn.active { background: #3d4bff !important; color: #fff !important; }

.vp-panel { display: none; }
.vp-panel.active { display: block; }

/* metrics */
.vp-metrics {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 24px;
}
.vp-metric {
    background: #12141f;
    border: 1px solid #1e2235;
    border-radius: 10px;
    padding: 16px 18px;
}
.vp-metric-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #8890b5 !important;
    margin-bottom: 6px;
}
.vp-metric-value { font-size: 18px; font-weight: 600; color: #e2e4f0 !important; }
.vp-metric-value.ok     { color: #00d4aa !important; }
.vp-metric-value.danger { color: #ff4d6d !important; }
.vp-metric-value.warn   { color: #ffb547 !important; }

/* section */
.vp-section {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: #8890b5 !important;
    margin: 28px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e2235;
}

/* card */
.vp-card {
    background: #12141f;
    border: 1px solid #1e2235;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 12px;
}
.vp-card-title {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #8890b5 !important;
    margin-bottom: 10px;
}
.vp-card pre {
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    color: #e2e4f0 !important;
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
}

.vp-two-col   { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.vp-three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }

/* Mobile responsive */
@media (max-width: 640px) {
    .vp-two-col   { grid-template-columns: 1fr; }
    .vp-three-col { grid-template-columns: 1fr; }
    .vp-card pre  { font-size: 11px; }
    .vp-tag       { font-size: 10px; padding: 2px 6px; }
    .vp-badge     { font-size: 10px; }
}

/* badge */
.vp-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 14px;
}
.vp-badge-ok     { background:#00d4aa18; color:#00d4aa; border:1px solid #00d4aa33; }
.vp-badge-danger { background:#ff4d6d18; color:#ff4d6d; border:1px solid #ff4d6d33; }
.vp-badge-warn   { background:#ffb54718; color:#ffb547; border:1px solid #ffb54733; }
.vp-badge-info   { background:#3d4bff18; color:#a0aaff; border:1px solid #3d4bff33; }

/* check rows */
.vp-check {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 8px;
    font-size: 13px;
}
.vp-check.ok   { background:#00d4aa0d; border:1px solid #00d4aa22; }
.vp-check.fail { background:#ff4d6d0d; border:1px solid #ff4d6d22; }
.vp-check.warn { background:#ffb5470d; border:1px solid #ffb54722; }
.vp-check .icon { font-size:15px; flex-shrink:0; margin-top:1px; }
.vp-check .lbl  { font-size:11px; color:#8890b5 !important; }
.vp-check .val  { color:#e2e4f0 !important; margin-top:2px; word-break:break-all; }

/* url rows */
.vp-url {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 6px;
    margin-bottom: 6px;
    background: #1a1d2e;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    word-break: break-all;
}
.vp-url a { color: #00d4aa !important; text-decoration: none; }
.vp-url a:hover { text-decoration: underline; }

/* image cards */
.vp-img-card {
    background: #1a1d2e;
    border: 1px solid #1e2235;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 4px;
}
.vp-img-card img { width:100%; display:block; height:auto; object-fit:contain; background:#0d0f18; }
.vp-img-lbl { padding:8px 12px; font-size:11px; color:#8890b5 !important; font-family:'DM Mono',monospace; }
.vp-img-txt { padding:0 12px 10px; font-size:12px; color:#e2e4f0 !important; line-height:1.5; }
.vp-img-placeholder {
    height:120px; display:flex; align-items:center; justify-content:center;
    color:#5a5f7a; font-size:12px; background:#12141f;
}

/* slide accordion */
.vp-slide {
    background: #12141f;
    border: 1px solid #1e2235;
    border-radius: 10px;
    margin-bottom: 10px;
    overflow: hidden;
}
.vp-slide-hdr {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    cursor: pointer;
    user-select: none;
    font-size: 13px;
    font-weight: 500;
    color: #e2e4f0 !important;
}
.vp-slide-hdr:hover { background: #1a1d2e; }
.vp-slide-arrow { font-size:16px; color:#8890b5; transition:transform .2s; display:inline-block; }
.vp-slide-arrow.open { transform: rotate(90deg); }
.vp-slide-body { display:none; padding:16px 18px 18px; border-top:1px solid #1e2235; }
.vp-slide-num {
    font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.08em; color:#7b87ff !important;
}

/* diff */
.vp-diff {
    background: #0d0f18;
    border: 1px solid #1e2235;
    border-radius: 8px;
    padding: 12px;
    margin-top: 12px;
    max-height: 320px;
    overflow-y: auto;
}
.vp-diff-line {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 3px;
    margin-bottom: 1px;
    white-space: pre-wrap;
    word-break: break-word;
}
.vp-diff-add { background:#00d4aa18; color:#00d4aa !important; }
.vp-diff-rem { background:#ff4d6d18; color:#ff4d6d !important; }
.vp-diff-ctx { color:#5a5f7a !important; }
.vp-toggle-btn {
    margin-top:10px;
    background:none !important;
    border:1px solid #2a2d42;
    color:#8890b5 !important;
    border-radius:6px;
    padding:5px 12px;
    font-size:12px;
    cursor:pointer !important;
    font-family:'DM Sans',sans-serif;
    pointer-events:auto !important;
}
.vp-toggle-btn:hover { border-color:#3d4bff; color:#a0aaff !important; }

/* tags */
.vp-tag {
    display:inline-block; padding:3px 10px; border-radius:20px;
    font-size:11px; margin:3px 4px 3px 0; font-family:'DM Mono',monospace;
}
.vp-tag-inc { background:#00d4aa18; color:#00d4aa !important; border:1px solid #00d4aa33; }
.vp-tag-exc { background:#ff4d6d18; color:#ff4d6d !important; border:1px solid #ff4d6d33; }

/* AI report */
.vp-ai-report {
    background:#12141f; border:1px solid #1e2235; border-radius:10px;
    padding:20px 24px; font-size:13px; line-height:1.9;
    white-space:pre-wrap; word-break:break-word; color:#e2e4f0 !important;
}
.vp-ai-report.has-errors { border-color:#ff4d6d44; }
.vp-ai-report.all-ok     { border-color:#00d4aa44; }
.vp-pass { color:#00d4aa; }
.vp-fail { color:#ff4d6d; }
.vp-warn { color:#ffb547; }

/* raw pre */
.vp-raw-pre {
    display:none; background:#0d0f18; border:1px solid #1e2235; border-radius:8px;
    padding:14px; font-family:'DM Mono',monospace; font-size:11px; color:#8890b5 !important;
    overflow-x:auto; max-height:400px; overflow-y:auto; white-space:pre;
    margin-top:10px;
}

/* ── markdown report styles ── */
.vp-md-h2 { font-size:15px; font-weight:600; color:#e2e4f0 !important; margin:18px 0 6px; }
.vp-md-h3 { font-size:13px; font-weight:600; color:#a0aaff !important; margin:14px 0 4px; text-transform:uppercase; letter-spacing:.05em; }
.vp-md-hr { border:none; border-top:1px solid #2a2d42; margin:12px 0; }
.vp-md-li { padding:2px 0 2px 10px; line-height:1.7; }
.vp-md-p  { line-height:1.7; margin:2px 0; }
.vp-md-br { height:6px; }
.vp-ai-report code { background:#1e2235; padding:1px 5px; border-radius:3px; font-family:'DM Mono',monospace; font-size:11px; }
.vp-ai-report strong { color:#e2e4f0 !important; font-weight:600; }
.vp-ai-report em { color:#c8cadc; font-style:italic; }
</style>
"""


# ── light theme ───────────────────────────────────────────────────────────
STREAMLIT_LIGHT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&display=swap');

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
.main, .block-container,
[data-testid="stMainBlockContainer"] {
    background-color: #f5f6fa !important;
    color: #1a1d2e !important;
    font-family: 'DM Sans', sans-serif !important;
}

/* Force ALL text dark in light mode */
p, span, div, label, h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] *,
[data-testid="stText"] *,
[data-testid="stHeading"] *,
[class*="st-"] { color: #1a1d2e !important; }

/* Exceptions — keep coloured elements */
[data-testid="stButton"] > button,
[data-testid="stButton"] > button * { color: #ffffff !important; }
.vp-pass, .vp-fail, .vp-warn,
.vp-badge *, .vp-tag * { color: inherit !important; }

[data-testid="stSidebar"],
[data-testid="stSidebarContent"] {
    background-color: #ffffff !important;
    border-right: 1px solid #e2e4f0 !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span { color: #3a3d52 !important; }

[data-testid="stHeader"] {
    background-color: #ffffff !important;
    border-bottom: 1px solid #e2e4f0 !important;
}

input, textarea,
[data-testid="stTextInput"] input,
[data-baseweb="input"] input {
    background-color: #ffffff !important;
    border: 1px solid #d0d3e8 !important;
    color: #1a1d2e !important;
    border-radius: 8px !important;
}

[data-baseweb="select"] > div,
[data-baseweb="select"] input {
    background-color: #ffffff !important;
    border-color: #d0d3e8 !important;
    color: #1a1d2e !important;
}
[data-baseweb="popover"] { background: #ffffff !important; }
[role="option"] { background: #ffffff !important; color: #1a1d2e !important; }

[data-testid="stButton"] > button {
    background-color: #3d4bff !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
}
[data-testid="stButton"] > button:hover { background-color: #5560ff !important; }

[data-testid="stMetric"] {
    background: #ffffff !important;
    border: 1px solid #e2e4f0 !important;
    border-radius: 10px !important;
    padding: 14px 18px !important;
}
[data-testid="stMetricValue"] { color: #1a1d2e !important; }
[data-testid="stMetricLabel"] { color: #6b6f8a !important; }

[data-testid="stDataFrame"],
[data-testid="stDataFrameResizable"] {
    background-color: #ffffff !important;
    border: 1px solid #e2e4f0 !important;
    border-radius: 10px !important;
}

[data-testid="stExpander"] {
    background-color: #ffffff !important;
    border: 1px solid #e2e4f0 !important;
    border-radius: 10px !important;
}

hr { border-color: #e2e4f0 !important; }
[data-testid="stCaptionContainer"] p { color: #9096b0 !important; }
[data-testid="stProgressBar"] > div > div { background: #3d4bff !important; }
</style>
"""

# ── light variant of component CSS ────────────────────────────────────────
COMPONENT_CSS_LIGHT = """
<style>
.vp-wrap { font-family: 'DM Sans', sans-serif; color: #1a1d2e !important; }

.vp-nav-wrap {
    position: sticky; top: 0; z-index: 999;
    background: #f5f6fa; border-bottom: 1px solid #e2e4f0;
    padding: 8px 0; margin-bottom: 20px;
}
.vp-nav {
    display: flex; gap: 4px; background: #ffffff;
    border: 1px solid #e2e4f0; border-radius: 12px; padding: 5px; max-width: 600px;
}
.vp-nav-btn {
    flex:1; padding:9px 12px; background:transparent !important;
    color:#6b6f8a !important; border-radius:8px; cursor:pointer !important;
    user-select:none; font-family:'DM Sans',sans-serif; font-size:13px; font-weight:500;
    transition:all .18s; white-space:nowrap; pointer-events:auto !important;
    position:relative; z-index:10; text-align:center;
    display:flex; align-items:center; justify-content:center;
}
.vp-nav-btn:hover  { background:#f0f1fa !important; color:#1a1d2e !important; }
.vp-nav-btn.active { background:#3d4bff !important; color:#fff !important; }

.vp-panel { display:none; }
.vp-panel.active { display:block; }

.vp-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }
.vp-metric { background:#ffffff; border:1px solid #e2e4f0; border-radius:10px; padding:16px 18px; }
.vp-metric-label { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:#6b6f8a !important; margin-bottom:6px; }
.vp-metric-value { font-size:18px; font-weight:600; color:#1a1d2e !important; }
.vp-metric-value.ok     { color:#0a9e7a !important; }
.vp-metric-value.danger { color:#d63050 !important; }
.vp-metric-value.warn   { color:#c47d0a !important; }

.vp-section { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.1em; color:#6b6f8a !important; margin:28px 0 12px; padding-bottom:8px; border-bottom:1px solid #e2e4f0; }

.vp-card { background:#ffffff; border:1px solid #e2e4f0; border-radius:10px; padding:16px 18px; margin-bottom:12px; }
.vp-card-title { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:#6b6f8a !important; margin-bottom:10px; }
.vp-card pre { font-family:'DM Mono',monospace; font-size:12px; color:#1a1d2e !important; white-space:pre-wrap; word-break:break-word; margin:0; }

.vp-two-col   { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.vp-three-col { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }

.vp-badge { display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; margin-bottom:14px; }
.vp-badge-ok     { background:#0a9e7a18; color:#0a9e7a; border:1px solid #0a9e7a33; }
.vp-badge-danger { background:#d6305018; color:#d63050; border:1px solid #d6305033; }
.vp-badge-warn   { background:#c47d0a18; color:#c47d0a; border:1px solid #c47d0a33; }
.vp-badge-info   { background:#3d4bff18; color:#3d4bff; border:1px solid #3d4bff33; }

.vp-check { display:flex; align-items:flex-start; gap:10px; padding:10px 14px; border-radius:8px; margin-bottom:8px; font-size:13px; }
.vp-check.ok   { background:#0a9e7a0d; border:1px solid #0a9e7a22; }
.vp-check.fail { background:#d630500d; border:1px solid #d6305022; }
.vp-check.warn { background:#c47d0a0d; border:1px solid #c47d0a22; }
.vp-check .icon { font-size:15px; flex-shrink:0; margin-top:1px; }
.vp-check .lbl  { font-size:11px; color:#6b6f8a !important; }
.vp-check .val  { color:#1a1d2e !important; margin-top:2px; word-break:break-all; }

.vp-url { display:flex; align-items:center; gap:10px; padding:8px 12px; border-radius:6px; margin-bottom:6px; background:#f0f1fa; font-family:'DM Mono',monospace; font-size:11px; word-break:break-all; }
.vp-url a { color:#3d4bff !important; text-decoration:none; }
.vp-url a:hover { text-decoration:underline; }

.vp-img-card { background:#f0f1fa; border:1px solid #e2e4f0; border-radius:10px; overflow:hidden; margin-bottom:4px; }
.vp-img-card img { width:100%; display:block; height:auto; object-fit:contain; background:#f5f6fa; }
.vp-img-lbl { padding:8px 12px; font-size:11px; color:#6b6f8a !important; font-family:'DM Mono',monospace; }
.vp-img-txt { padding:0 12px 10px; font-size:12px; color:#1a1d2e !important; line-height:1.5; }
.vp-img-placeholder { height:120px; display:flex; align-items:center; justify-content:center; color:#9096b0; font-size:12px; background:#f0f1fa; }

.vp-slide { background:#ffffff; border:1px solid #e2e4f0; border-radius:10px; margin-bottom:10px; overflow:hidden; }
.vp-slide-hdr { display:flex; align-items:center; gap:10px; padding:14px 18px; cursor:pointer; user-select:none; font-size:13px; font-weight:500; color:#1a1d2e !important; }
.vp-slide-hdr:hover { background:#f5f6fa; }
.vp-slide-arrow { font-size:16px; color:#9096b0; transition:transform .2s; display:inline-block; }
.vp-slide-arrow.open { transform:rotate(90deg); }
.vp-slide-body { display:none; padding:16px 18px 18px; border-top:1px solid #e2e4f0; }
.vp-slide-num { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:#3d4bff !important; }

.vp-diff { background:#f5f6fa; border:1px solid #e2e4f0; border-radius:8px; padding:12px; margin-top:12px; max-height:320px; overflow-y:auto; }
.vp-diff-line { font-family:'DM Mono',monospace; font-size:11px; padding:2px 6px; border-radius:3px; margin-bottom:1px; white-space:pre-wrap; word-break:break-word; }
.vp-diff-add { background:#0a9e7a18; color:#0a7a5c !important; }
.vp-diff-rem { background:#d630500d; color:#b02040 !important; }
.vp-diff-ctx { color:#9096b0 !important; }
.vp-toggle-btn { margin-top:10px; background:none !important; border:1px solid #d0d3e8; color:#6b6f8a !important; border-radius:6px; padding:5px 12px; font-size:12px; cursor:pointer !important; font-family:'DM Sans',sans-serif; pointer-events:auto !important; }
.vp-toggle-btn:hover { border-color:#3d4bff; color:#3d4bff !important; }

.vp-tag { display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; margin:3px 4px 3px 0; font-family:'DM Mono',monospace; }
.vp-tag-inc { background:#0a9e7a18; color:#0a7a5c !important; border:1px solid #0a9e7a33; }
.vp-tag-exc { background:#d630500d; color:#b02040 !important; border:1px solid #d6305033; }

.vp-ai-report { background:#ffffff; border:1px solid #e2e4f0; border-radius:10px; padding:20px 24px; font-size:13px; line-height:1.9; white-space:pre-wrap; word-break:break-word; color:#1a1d2e !important; }
.vp-ai-report.has-errors { border-color:#d6305044; }
.vp-ai-report.all-ok     { border-color:#0a9e7a44; }
.vp-pass { color:#0a9e7a; }
.vp-fail { color:#d63050; }
.vp-warn { color:#c47d0a; }

.vp-raw-pre { display:none; background:#f5f6fa; border:1px solid #e2e4f0; border-radius:8px; padding:14px; font-family:'DM Mono',monospace; font-size:11px; color:#6b6f8a !important; overflow-x:auto; max-height:400px; overflow-y:auto; white-space:pre; margin-top:10px; }

/* ── markdown report styles (light) ── */
.vp-md-h2 { font-size:15px; font-weight:600; color:#1a1d2e !important; margin:18px 0 6px; }
.vp-md-h3 { font-size:13px; font-weight:600; color:#3d4bff !important; margin:14px 0 4px; text-transform:uppercase; letter-spacing:.05em; }
.vp-md-hr { border:none; border-top:1px solid #d0d3e8; margin:12px 0; }
.vp-md-li { padding:2px 0 2px 10px; line-height:1.7; }
.vp-md-p  { line-height:1.7; margin:2px 0; }
.vp-md-br { height:6px; }
.vp-ai-report code { background:#f0f1fa; padding:1px 5px; border-radius:3px; font-family:'DM Mono',monospace; font-size:11px; }
.vp-ai-report strong { color:#1a1d2e !important; font-weight:600; }
.vp-ai-report em { color:#4a4f6a; font-style:italic; }
</style>
"""

_JS = """
<script>
function sendHeight() {
    var h = document.body.scrollHeight;
    window.parent.postMessage({type: 'streamlit:setFrameHeight', height: h}, '*');
}
function showTab(id, btn) {
    document.querySelectorAll('.vp-panel').forEach(function(p) { p.classList.remove('active'); });
    document.querySelectorAll('.vp-nav-btn').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById('vp-panel-' + id).classList.add('active');
    btn.classList.add('active');
    setTimeout(sendHeight, 50);
}
function toggleSlide(uid) {
    var body = document.getElementById(uid);
    var arr  = document.getElementById('arr_' + uid);
    var isOpen = body.style.display === 'block';
    body.style.display = isOpen ? 'none' : 'block';
    arr.classList.toggle('open', !isOpen);
    setTimeout(sendHeight, 50);
}
function toggleVis(uid) {
    var el = document.getElementById(uid);
    if (!el) return;
    var hidden = el.style.display === 'none' || el.style.display === '';
    el.style.display = hidden ? 'block' : 'none';
    setTimeout(sendHeight, 50);
}
window.addEventListener('load', function() { setTimeout(sendHeight, 100); });
</script>
"""


# ── helpers ────────────────────────────────────────────────────────────────

def _e(s) -> str:
    return html.escape(str(s or ""))

def _img_tag(src, alt="") -> str:
    if isinstance(src, bytes) and src:
        b64 = base64.b64encode(src).decode()
        return f'<img src="data:image/png;base64,{b64}" alt="{_e(alt)}">'
    if isinstance(src, str) and src.startswith("http"):
        return f'<img src="{_e(src)}" alt="{_e(alt)}">'
    return '<div class="vp-img-placeholder">No image</div>'

def _badge(text, kind="info"):
    return f'<span class="vp-badge vp-badge-{kind}">{_e(text)}</span>'

def _check(icon, label, value, kind="ok"):
    return (
        f'<div class="vp-check {kind}">'
        f'<span class="icon">{icon}</span>'
        f'<div><div class="lbl">{_e(label)}</div>'
        f'<div class="val">{_e(value)}</div></div></div>'
    )

def _section(title):
    return f'<div class="vp-section">{_e(title)}</div>'

def _diff_html(text1, text2):
    lines = list(difflib.Differ().compare(text1.splitlines(), text2.splitlines()))
    parts = []
    for line in lines:
        if line.startswith("+ "):
            parts.append(f'<div class="vp-diff-line vp-diff-add">{_e(line)}</div>')
        elif line.startswith("- "):
            parts.append(f'<div class="vp-diff-line vp-diff-rem">{_e(line)}</div>')
        elif line.startswith("? "):
            continue
        else:
            parts.append(f'<div class="vp-diff-line vp-diff-ctx">{_e(line)}</div>')
    return "".join(parts)

def _url_row(url, matched):
    icon = "✅" if matched else "❌"
    return (
        f'<div class="vp-url"><span>{icon}</span>'
        f'<a href="{_e(url)}" target="_blank">{_e(url)}</a></div>'
    )

def _slide_block(idx, j_card, a_body, a_btn, j_bytes, api_img_url):
    uid = f"slide_{idx}"
    return (
        f'<div class="vp-slide">'
        f'<div class="vp-slide-hdr" onclick="toggleSlide(\'{uid}\')">'
        f'<span class="vp-slide-arrow" id="arr_{uid}">&#x203A;</span>'
        f'<span class="vp-slide-num">Slide {idx}</span>'
        f'</div>'
        f'<div class="vp-slide-body" id="{uid}">'
        f'<div class="vp-two-col">'
        f'<div><div class="vp-img-card">{_img_tag(j_bytes)}'
        f'<div class="vp-img-lbl">JIRA</div>'
        f'<div class="vp-img-txt"><b>Body:</b> {_e(j_card["body"])}<br>'
        f'<b>Button:</b> {_e(j_card["btn"])}</div></div></div>'
        f'<div><div class="vp-img-card">{_img_tag(api_img_url)}'
        f'<div class="vp-img-lbl">DMA configured</div>'
        f'<div class="vp-img-txt"><b>Body:</b> {_e(a_body)}<br>'
        f'<b>Button:</b> {_e(a_btn)}</div></div></div>'
        f'</div></div></div>'
    )


# ── panel builders ─────────────────────────────────────────────────────────


def _markdown_to_html(text: str) -> str:
    """Convert a Gemini markdown report to styled HTML."""
    import re as _re
    lines = text.split("\n")
    out = []
    for line in lines:
        # Colour emoji markers first (before escaping)
        line_esc = _e(line)
        line_esc = line_esc.replace("✅", '<span class="vp-pass">✅</span>')
        line_esc = line_esc.replace("❌", '<span class="vp-fail">❌</span>')
        line_esc = line_esc.replace("⚠️", '<span class="vp-warn">⚠️</span>')
        # ### heading
        if line_esc.startswith("###"):
            inner = line_esc.lstrip("#").strip()
            out.append(f'<div class="vp-md-h3">{inner}</div>')
        # ## heading
        elif line_esc.startswith("##"):
            inner = line_esc.lstrip("#").strip()
            out.append(f'<div class="vp-md-h2">{inner}</div>')
        # --- horizontal rule
        elif line_esc.strip() in ("---", "***", "___"):
            out.append('<hr class="vp-md-hr">')
        # bullet  * or -
        elif _re.match(r"^[\*\-]\s", line_esc):
            inner = line_esc[2:].strip()
            inner = _re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', inner)
            inner = _re.sub(r"\*(.+?)\*",     r'<em>\1</em>', inner)
            inner = _re.sub(r"`(.+?)`",        r'<code>\1</code>', inner)
            out.append(f'<div class="vp-md-li">• {inner}</div>')
        # blank line → spacer
        elif line_esc.strip() == "":
            out.append('<div class="vp-md-br"></div>')
        # normal paragraph
        else:
            inner = line_esc
            inner = _re.sub(r"\*\*(.+?)\*\*", r'<strong>\1</strong>', inner)
            inner = _re.sub(r"\*(.+?)\*",     r'<em>\1</em>', inner)
            inner = _re.sub(r"`(.+?)`",        r'<code>\1</code>', inner)
            out.append(f'<div class="vp-md-p">{inner}</div>')
    return "\n".join(out)

def _build_ai_panel(jira, ai_result, jira_imgs, dma_urls):
    if not ai_result:
        return '<div class="vp-card"><p style="color:#8890b5">Run the AI audit to see results here.</p></div>'

    has_errors = "❌" in ai_result
    cls   = "has-errors" if has_errors else "all-ok"
    kind  = "danger" if has_errors else "ok"
    label = f"{ai_result.count('❌')} issue(s) found" if has_errors else "All checks passed"

    fmt = _markdown_to_html(ai_result)

    parts = [_badge(label, kind), f'<div class="vp-ai-report {cls}">{fmt}</div>']

    if jira_imgs or dma_urls:
        parts.append(_section("Images Analysed"))
        for i in range(max(len(jira_imgs), len(dma_urls))):
            j_b  = jira_imgs[i]["bytes"] if i < len(jira_imgs) else None
            j_nm = jira_imgs[i].get("name", f"slide_{i+1}") if i < len(jira_imgs) else ""
            d_u  = dma_urls[i] if i < len(dma_urls) else None
            parts.append(
                f'<div class="vp-two-col" style="margin-bottom:16px;">'
                f'<div class="vp-img-card">{_img_tag(j_b)}'
                f'<div class="vp-img-lbl">JIRA — {_e(j_nm)}</div></div>'
                f'<div class="vp-img-card">{_img_tag(d_u)}'
                f'<div class="vp-img-lbl">DMA configured</div></div>'
                f'</div>'
            )
    return "".join(parts)


def _strip_slide_labels(text: str) -> str:
    """Remove everything from the first Slide N: marker onwards.
    Keeps only the intro text before the carousel slides.
    """
    import re as _re
    m = _re.search(r'(?im)^[\s*]*(?:Slide|Slider)\s*\d+\s*:', text)
    if m:
        return text[:m.start()].strip()
    return text.strip()


def _build_content_panel(jira, api, tmpl, leaflet_data, ai_urls, client=""):
    parts = []
    # Strip "Slide N:" structural labels — they are not part of the message text
    jira_desc = _strip_slide_labels(str(jira.get("description", "")).replace("\r", "").strip())
    body = next((c.get("text","") for c in (tmpl or {}).get("components",[]) if c["type"]=="BODY"), "")

    # Kaufland RCS: Sunday = fully static; Wednesday = Card 1 static, Card 2 from JIRA
    if client == "Kaufland RCS":
        from datetime import datetime as _dtrcs
        try:
            _is_sun_rcs = _dtrcs.fromisoformat(
                str(api.get("scheduled_date","")).replace("Z","+00:00")
            ).weekday() == 6
        except Exception:
            _is_sun_rcs = True  # safe default — treat as static

        if _is_sun_rcs or not jira_desc:
            # Sunday or no description — show static card texts
            static_cards = CLIENT_CONFIGS.get("Kaufland RCS", {}).get("sunday_rcs_cards", [])
            if static_cards:
                parts.append(_badge("Static RCS Template — No JIRA description required", "info"))
                parts.append(_section("RCS Card Texts (Static)"))
                for i, card in enumerate(static_cards, 1):
                    parts.append(
                        f'<div class="vp-card" style="margin-bottom:12px;">'
                        f'<div class="vp-card-title">Card {i}: {_e(card["title"])}</div>'
                        f'<pre>{_e(card["body"])}</pre>'
                        f'<div style="margin-top:8px;"><span class="vp-tag vp-tag-inc">Button: {_e(card["button"])}</span>'
                        f'<span class="vp-tag vp-tag-inc">Leaflet: {_e(card["leaflet_filter"])}</span></div>'
                        f'</div>'
                    )
        else:
            # Wednesday — Card 2 has JIRA-specific promotional text
            rcs_cards = (api.get("google_rcs_content", {})
                           .get("richCard", {})
                           .get("carouselCard", {})
                           .get("cardContents", []))
            parts.append(_section("Wednesday RCS Cards"))
            parts.append(_badge("Card 1: Static leaflet card (Knüller-Angebote)", "info"))
            if len(rcs_cards) >= 2:
                card2_desc = rcs_cards[1].get("description", "")
                card2_title = rcs_cards[1].get("title", "Card 2")
                sim2 = difflib.SequenceMatcher(None, jira_desc, card2_desc).ratio() if card2_desc else 0
                sim2_kind = "ok" if sim2 > 0.9 else ("warn" if sim2 > 0.6 else "fail")
                parts.append(_section(f"Card 2: {card2_title} (JIRA vs API)"))
                parts.append(
                    f'<div class="vp-two-col">'
                    f'<div class="vp-card"><div class="vp-card-title">JIRA Description</div>'
                    f'<pre>{_e(jira_desc) or "<em>None</em>"}</pre></div>'
                    f'<div class="vp-card"><div class="vp-card-title">RCS Card 2 Text</div>'
                    f'<pre>{_e(card2_desc) or "<em>None</em>"}</pre></div>'
                    f'</div>'
                )
                if card2_desc:
                    parts.append(_badge(f"Similarity {int(sim2*100)}%", sim2_kind))
        return "".join(parts)

    # Kaufland WABA Sunday — static carousel text, no JIRA description needed
    if client == "Kaufland WABA" and not jira_desc:
        api_cards = []
        for cp in api.get("component_parameters", []):
            if isinstance(cp, dict) and cp.get("source") == "custom_cards":
                api_cards = cp.get("cards", [])
                break
        if len(api_cards) == 3:
            tmpl_cards = next(
                (c.get("cards", []) for c in tmpl.get("components", []) if c.get("type") == "CAROUSEL"), []
            )
            tmpl_card3_body = ""
            if len(tmpl_cards) >= 3:
                for cc in tmpl_cards[2].get("components", []):
                    if cc.get("type") == "BODY":
                        tmpl_card3_body = cc.get("text", "")
                        break
            pc = jira.get("parsed_carousel") or {}
            jira_card3_body = ""
            if pc.get("cards") and len(pc["cards"]) >= 3:
                jira_card3_body = pc["cards"][2].get("body", "")
            if tmpl_card3_body or jira_card3_body:
                parts.append(_section("Card 3 Text Comparison"))
                sim3 = difflib.SequenceMatcher(None, jira_card3_body, tmpl_card3_body).ratio() if tmpl_card3_body else 0
                sim3_kind = "ok" if sim3 > 0.9 else ("warn" if sim3 > 0.6 else "fail")
                parts.append(
                    f'<div class="vp-two-col">'
                    f'<div class="vp-card"><div class="vp-card-title">JIRA Card 3</div>'
                    f'<pre>{_e(jira_card3_body) or "<em>None</em>"}</pre></div>'
                    f'<div class="vp-card"><div class="vp-card-title">Template Card 3</div>'
                    f'<pre>{_e(tmpl_card3_body) or "<em>None</em>"}</pre></div>'
                    f'</div>'
                )
                if tmpl_card3_body:
                    parts.append(_badge(f"Similarity {int(sim3*100)}%", sim3_kind))
        return "".join(parts)

    parts.append(_section("Text Comparison"))
    sim = difflib.SequenceMatcher(None, jira_desc, body).ratio() if body else 0
    sim_kind = "ok" if sim > 0.9 else ("warn" if sim > 0.6 else "fail")

    parts.append(
        f'<div class="vp-two-col">'
        f'<div class="vp-card"><div class="vp-card-title">JIRA Description</div>'
        f'<pre>{_e(jira_desc) or "<em>None</em>"}</pre></div>'
        f'<div class="vp-card"><div class="vp-card-title">Template Body</div>'
        f'<pre>{_e(body) or "<em>None</em>"}</pre></div>'
        f'</div>'
    )
    if body:
        parts.append(_badge(f"Similarity {int(sim*100)}%", sim_kind))
        uid = "diff_main"
        parts.append(
            f'<div class="vp-toggle-btn" onclick="toggleVis(\'{uid}\')">Show diff</div>'
            f'<div class="vp-diff" id="{uid}" style="display:none">{_diff_html(jira_desc, body)}</div>'
        )

    if tmpl:
        parts.append(_section("Interactive Elements"))
        ft = next((c.get("text","") for c in tmpl.get("components",[]) if c["type"]=="FOOTER"), "")
        jira_ft = str(jira.get("footer_text","") or "")
        # Pass if JIRA has no footer (DMA may add a default footer)
        # Fail only if JIRA specifies a footer but DMA is missing it
        if not jira_ft.strip():
            ft_ok = True  # JIRA empty — DMA footer is fine
        else:
            ft_ok = jira_ft == ft  # JIRA has footer — must match DMA
        parts.append(_check("✅" if ft_ok else "❌","Footer",f'JIRA: "{jira_ft}" → API: "{ft}"',"ok" if ft_ok else "fail"))

        api_btns = [clean_button_text(b.get("text","")) for c in tmpl.get("components",[]) if c["type"]=="BUTTONS" for b in c.get("buttons",[])]
        jira_btn_raw = str(jira.get("cta_button",""))
        btn_ok = clean_button_text(jira_btn_raw) in api_btns
        parts.append(_check("✅" if btn_ok else "❌","CTA Button",f'"{jira_btn_raw}"',"ok" if btn_ok else "fail"))

    parts.append(_section("URL Validation"))
    jira_set = (
        ai_urls["jira"] if ai_urls else
        sorted({u for u in (
            extract_urls(jira_desc) +
            extract_urls(str(jira.get("additional_comments",""))) +
            ([jira.get("cta_link")] if jira.get("cta_link") else [])
        ) if not is_media_url(u)})
    )
    api_set = (
        ai_urls["api"] if ai_urls else
        sorted({u for u in (
            extract_api_urls_advanced(api) + (extract_urls(str(tmpl)) if tmpl else [])
        ) if not is_media_url(u)})
    )
    if leaflet_data and not ai_urls and leaflet_data:
        l_url = leaflet_data[0].get("public_url") or leaflet_data[0].get("url","")
        if l_url:
            api_set = [u.replace("@leaflet_url_path", l_url) for u in api_set]

    parts.append('<div class="vp-two-col">')
    parts.append('<div><div class="vp-card-title">Expected (JIRA)</div>')
    if not jira_set: parts.append('<p style="color:#8890b5;font-size:12px">None found</p>')
    for url in jira_set:
        parts.append(_url_row(url, any(compare_urls_smart(url,a) for a in api_set)))
    parts.append('</div><div><div class="vp-card-title">Actual (API)</div>')
    if not api_set: parts.append('<p style="color:#8890b5;font-size:12px">None found</p>')
    for url in api_set:
        parts.append(f'<div class="vp-url"><span>🔗</span><a href="{_e(url)}" target="_blank">{_e(url)}</a></div>')
    parts.append('</div></div>')
    return "".join(parts)



def _jira_images_by_slide(carousel_images: list) -> dict:
    """
    Return a dict of {slide_number: bytes} built from JIRA attachment filenames.
    Uses the same numbering logic as api_client._slide_number so image01 -> 1, etc.
    Falls back to position order for images with no detectable number.
    """
    import re as _re

    def _slide_num(name: str) -> int:
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

    by_slide: dict[int, bytes] = {}
    unnumbered: list[bytes] = []

    for img in carousel_images:
        name  = img.get("name", "") if isinstance(img, dict) else ""
        bdata = img.get("bytes") if isinstance(img, dict) else None
        if not bdata:
            continue
        num = _slide_num(name)
        if num == 9999:
            unnumbered.append(bdata)
        else:
            by_slide[num] = bdata

    slot = 1
    for bdata in unnumbered:
        while slot in by_slide:
            slot += 1
        by_slide[slot] = bdata
        slot += 1

    return by_slide




def _extract_rcs_cards(api: dict) -> list[dict]:
    """Extract RCS cardContents from google_rcs_content.richCard.carouselCard."""
    try:
        cards = (api.get("google_rcs_content", {})
                    .get("richCard", {})
                    .get("carouselCard", {})
                    .get("cardContents", []))
        return cards if isinstance(cards, list) else []
    except Exception:
        return []


def _is_sunday_sendout(api: dict) -> bool:
    """Return True if the scheduled_date falls on a Sunday."""
    import re as _re
    from datetime import datetime
    date_str = str(api.get("scheduled_date", ""))
    if not date_str:
        return False
    try:
        # Parse ISO date e.g. "2026-04-12T09:45:36Z"
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.weekday() == 6  # 6 = Sunday
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Visuals panel
# ---------------------------------------------------------------------------

def _build_visuals_panel(jira: dict, api: dict, tmpl: dict | None,
                         leaflet_data: list) -> str:
    parts = []

    # ── RCS carousel (Kaufland RCS) ──
    rcs_cards = _extract_rcs_cards(api)
    if rcs_cards:
        parts.append(_section("RCS Carousel Cards"))
        is_sunday = _is_sunday_sendout(api)
        if is_sunday:
            parts.append(_badge("Sunday Sendout — Static RCS template", "info"))
        for i, card in enumerate(rcs_cards, 1):
            title = card.get("title", f"Card {i}")
            desc  = card.get("description", "")
            img_url = (card.get("media", {})
                           .get("contentInfo", {})
                           .get("fileUrl", ""))
            btn = ""
            btn_url = ""
            for sug in card.get("suggestions", []):
                action = sug.get("action", {})
                btn = action.get("text", "")
                btn_url = action.get("openUrlAction", {}).get("url", "")
                break
            # Per-card leaflet_filter; fall back to top-level leaflet_filter
            lf = card.get("leaflet_filter") or api.get("leaflet_filter") or {}
            lf_tags = [t.get("name","") + "=" + t.get("value","")
                       for t in lf.get("tags", [])]
            lf_od = lf.get("offset_days")
            if lf_od is not None:
                lf_tags.append(f"offset_days={lf_od}")
            lf_str = ", ".join(lf_tags) if lf_tags else "No leaflet filter"

            parts.append(
                f'<details><summary>'
                f'<span class="vp-slide-num">Card {i}: {_e(title)}</span>'
                f'</summary>'
                f'<div class="vp-slide-body" style="display:block">'
                f'<div class="vp-two-col">'
                f'<div class="vp-img-card">{_img_tag(img_url if img_url.startswith("http") else None)}'
                f'<div class="vp-img-lbl">Card image</div></div>'
                f'<div>'
                f'<div class="vp-card"><div class="vp-card-title">Description</div>'
                f'<pre>{_e(desc)}</pre></div>'
                f'<div style="margin-top:8px;">'
                f'<span class="vp-tag vp-tag-inc">Button: {_e(btn)}</span>'
                + (f'<span class="vp-tag vp-tag-inc">URL: <a href="{_e(btn_url)}" target="_blank">{_e(btn_url)}</a></span>' if btn_url else "")
                + f'<span class="vp-tag vp-tag-inc">Leaflet: {_e(lf_str)}</span>'
                f'</div></div></div>'
                f'</div></details>'
            )
        return "".join(parts)

    carousel_parsed = jira.get("parsed_carousel")
    tmpl_carousel = next(
        (c for c in (tmpl or {}).get("components", []) if c["type"] == "CAROUSEL"), None
    )

    api_custom_cards: list[dict] = []
    def _collect(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "carousel" and "cards" in obj:
                api_custom_cards.extend(obj["cards"])
            for v in obj.values(): _collect(v)
        elif isinstance(obj, list):
            for item in obj: _collect(item)
    _collect(api)

    first_leaflet = leaflet_data[0] if leaflet_data and isinstance(leaflet_data, list) else None
    l_url = (first_leaflet.get("public_url") or first_leaflet.get("url") or "") if first_leaflet else ""
    l_img = (first_leaflet.get("document_url") or first_leaflet.get("cover_image") or
             first_leaflet.get("image_url")) if first_leaflet else None

    if carousel_parsed and tmpl_carousel:
        parts.append(_section("Carousel Slides"))
        if carousel_parsed.get("intro"):
            parts.append(
                f'<div class="vp-card" style="margin-bottom:16px;">'
                f'<div class="vp-card-title">Intro text</div>'
                f'<pre>{_e(carousel_parsed["intro"])}</pre></div>'
            )

        api_cards = tmpl_carousel.get("cards", [])
        jira_cards = carousel_parsed["cards"]

        # Build slide_num -> bytes dict once
        jira_by_slide = _jira_images_by_slide(jira.get("carousel_images") or [])

        for i, j_card in enumerate(jira_cards):
            if i >= len(api_cards):
                break
            a_card = api_cards[i]
            a_body = next((c.get("text", "") for c in a_card.get("components", [])
                           if c["type"] == "BODY"), "")
            a_btn = next(
                (b.get("text", "")
                 for c in a_card.get("components", []) if c["type"] == "BUTTONS"
                 for b in c.get("buttons", [])), ""
            )
            if l_url:
                a_body = a_body.replace("@leaflet_url_path", l_url)
                a_btn = a_btn.replace("@leaflet_url_path", l_url)

            # Look up by slide number (filename-based), not array position
            j_bytes = jira_by_slide.get(i + 1)

            api_img_url = None
            if api_custom_cards and i < len(api_custom_cards):
                for cp in api_custom_cards[i].get("component_parameters", []):
                    if cp.get("type") == "header_image" and cp.get("value"):
                        api_img_url = cp["value"]
            if not api_custom_cards and not api_img_url:
                for comp in a_card.get("components", []):
                    if comp["type"] == "HEADER" and comp.get("format") == "IMAGE":
                        api_img_url = comp.get("example", {}).get("header_handle", [None])[0]
            if (not api_img_url or api_img_url == "@leaflet_image_url") and l_img:
                api_img_url = l_img

            parts.append(_slide_block(i + 1, j_card, a_body, a_btn, j_bytes, api_img_url))
    elif api_custom_cards:
        # WABA carousel with custom cards (e.g. Kaufland WABA)
        parts.append(_section("WABA Carousel Cards (DMA Configured)"))
        is_sunday = _is_sunday_sendout(api)
        if is_sunday:
            parts.append(_badge("Sunday Sendout — Leaflet-sourced carousel", "info"))
        top_lf = api.get("leaflet_filter", {})

        # Build leaflet_type -> first matching leaflet lookup from leaflet_data
        leaflet_by_type: dict[str, dict] = {}
        for lf_item in (leaflet_data or []):
            lf_type_val = (lf_item.get("data") or {}).get("leaflet_type", "")
            if lf_type_val and lf_type_val not in leaflet_by_type:
                leaflet_by_type[lf_type_val] = lf_item

        # Get tmpl carousel cards for body text
        tmpl_carousel_cards = []
        if tmpl:
            tc = next((c for c in tmpl.get("components", []) if c["type"] == "CAROUSEL"), None)
            if tc:
                tmpl_carousel_cards = tc.get("cards", [])

        for i, dma_card in enumerate(api_custom_cards, 1):
            # Per-card leaflet filter, fall back to top-level
            card_lf = dma_card.get("leaflet_filter") or top_lf or {}
            lf_type = next((t.get("value","") for t in card_lf.get("tags",[])
                            if t.get("name") == "leaflet_type"), "")
            lf_od = card_lf.get("offset_days")
            lf_tags = [f"leaflet_type={lf_type}"] if lf_type else []
            if lf_od is not None:
                lf_tags.append(f"offset_days={lf_od}")
            lf_str = ", ".join(lf_tags) if lf_tags else "Main leaflet filter"

            # Resolve image: static custom value OR leaflet image by type
            api_img_url = None
            img_source  = None
            for cp in dma_card.get("component_parameters", []):
                if cp.get("type") == "header_image":
                    api_img_url = cp.get("value") or None
                    img_source  = cp.get("source", "")
                    break
            is_leaflet_img = (img_source == "leaflet_image_url" or not api_img_url)
            if is_leaflet_img:
                # Pick leaflet matching this card's leaflet_type
                matched_lf = leaflet_by_type.get(lf_type) or (leaflet_data[0] if leaflet_data else None)
                if matched_lf:
                    api_img_url = (matched_lf.get("document_url") or
                                   matched_lf.get("cover_image") or
                                   matched_lf.get("image_url"))

            # Get leaflet URL for this card
            matched_lf_for_url = leaflet_by_type.get(lf_type) or (leaflet_data[0] if leaflet_data else None)
            leaflet_url = (matched_lf_for_url.get("url") or matched_lf_for_url.get("public_url", "")) if matched_lf_for_url else ""

            # Get template body text for this card (from WABA template carousel)
            tmpl_body_text = ""
            if i - 1 < len(tmpl_carousel_cards):
                tc_card = tmpl_carousel_cards[i - 1]
                tmpl_body_text = next((c.get("text","") for c in tc_card.get("components",[])
                                       if c["type"] == "BODY"), "")
            # Fallback: show the dynamic sources as the "text"
            if not tmpl_body_text:
                body_params = [cp for cp in dma_card.get("component_parameters", [])
                               if cp.get("type") == "body_text"]
                if body_params:
                    tmpl_body_text = " | ".join(cp.get("source","") for cp in body_params)

            # Dynamic sources (non-image, non-button params)
            sources = [cp.get("source","") for cp in dma_card.get("component_parameters", [])
                       if cp.get("source") and cp.get("type") not in ("header_image", "button_cta", "body_text")]
            body_sources = [cp.get("source","") for cp in dma_card.get("component_parameters", [])
                            if cp.get("type") == "body_text" and cp.get("source")]

            parts.append(
                f'<details open><summary>'
                f'<span class="vp-slide-num">Card {i} — {_e(lf_str)}</span>'
                f'</summary>'
                f'<div class="vp-slide-body" style="display:block;padding-top:14px">'
                f'<div class="vp-two-col">'
                # Image side
                f'<div>'
                f'<div class="vp-img-card">{_img_tag(api_img_url)}'
                f'<div class="vp-img-lbl">Leaflet image ({_e(lf_type or "main")})</div></div>'
                + (f'<div style="margin-top:8px;"><a href="{_e(leaflet_url)}" target="_blank" style="font-size:11px;color:#00d4aa;">{_e(leaflet_url[:60])}...</a></div>' if leaflet_url else "")
                + f'</div>'
                # Text side
                f'<div>'
                + (f'<div class="vp-card"><div class="vp-card-title">Template body text</div><pre>{_e(tmpl_body_text)}</pre></div>' if tmpl_body_text else "")
                + (f'<div class="vp-card" style="margin-top:8px"><div class="vp-card-title">Dynamic body sources</div><pre>{_e(chr(10).join(body_sources))}</pre></div>' if body_sources else "")
                + f'<div style="margin-top:8px;">'
                f'<span class="vp-tag vp-tag-inc">Button: leaflet_url_path</span>'
                f'<span class="vp-tag vp-tag-inc">Leaflet: {_e(lf_str)}</span>'
                f'</div></div></div>'
                f'</div></details>'
            )
    else:
        parts.append(_section("Header Image"))
        img_tmpl = None
        for p in api.get("component_parameters", []):
            if p.get("type") == "header_image":
                img_tmpl = p.get("value") or (
                    "@leaflet_image_url" if p.get("source") == "leaflet_image_url" else None
                )
                break
        if (img_tmpl == "@leaflet_image_url" or not img_tmpl) and first_leaflet:
            img_tmpl = (first_leaflet.get("document_url") or
                        first_leaflet.get("cover_image") or
                        first_leaflet.get("image_url"))

        parts.append(
            f'<div class="vp-two-col">'
            f'<div class="vp-img-card">{_img_tag(jira.get("attachment_bytes"))}'
            f'<div class="vp-img-lbl">JIRA Request</div></div>'
            f'<div class="vp-img-card">{_img_tag(img_tmpl)}'
            f'<div class="vp-img-lbl">DMA Configured</div></div>'
            f'</div>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tech panel
# ---------------------------------------------------------------------------

def _filter_matches(expected: dict, actual: dict) -> bool:
    """Match expected filter against actual API filter dict.
    "type"="tag" is a category label, not a field required in the actual dict.
    """
    exp_name = expected.get("name")
    exp_val  = str(expected.get("value", ""))
    if exp_name and exp_val and expected.get("mode") != "exclude":
        if actual.get("name") == exp_name and str(actual.get("value", "")) == exp_val:
            return True

    if expected.get("type") == "leaflet_tag" and expected.get("offset_days") is not None:
        if (actual.get("type") == "leaflet_tag" and
                str(actual.get("offset_days", "")) == str(expected["offset_days"])):
            return True

    for k, v in expected.items():
        if k == "mode":
            if v == "exclude":
                if actual.get("exclude_value") != expected.get("value"):
                    return False
        elif k == "type" and v in ("tag", "leaflet_tag"):
            pass  # category label, not a matchable field
        elif k in actual:
            if str(actual.get(k, "")) != str(v):
                return False
        elif k == "values":
            actual_val = actual.get("value") or actual.get("shop_number") or ""
            if isinstance(v, list) and str(actual_val) not in [str(x) for x in v]:
                return False
        elif k not in {"name", "value", "values", "shop_number", "locale", "type", "mode", "offset_days"}:
            return False
    return True


def _build_tech_panel(jira: dict, api: dict, client: str) -> str:
    parts = []
    _client_cfg = CLIENT_CONFIGS.get(client, {})

    parts.append(_section("Account Routing"))
    expected_acc = _client_cfg.get("account_id", "—")
    actual_acc = api.get("account_id")
    try:
        acc_ok = int(expected_acc) == int(actual_acc)
    except (TypeError, ValueError):
        acc_ok = str(expected_acc) == str(actual_acc)
    parts.append(_check(
        "✅" if acc_ok else "❌", "Account ID",
        f"Expected {expected_acc} → Got {actual_acc}",
        "ok" if acc_ok else "fail"
    ))

    parts.append(_section("Tag Configuration"))

    # ── Resolve config filters (day-of-week aware for Kaufland) ──────────────
    _all_cf = _client_cfg.get("filters", {})
    if client in ("Kaufland RCS", "Kaufland WABA"):
        from datetime import datetime as _dt2
        _ds = str(api.get("scheduled_date", ""))
        try:
            _dt_obj = _dt2.fromisoformat(_ds.replace("Z", "+00:00"))
            _is_sun = _dt_obj.weekday() == 6
        except Exception:
            _is_sun = False
        _cfg_filters = _all_cf.get("Sunday" if _is_sun else "Wednesday", _all_cf.get("Standard", []))
    else:
        _cfg_filters = _all_cf.get("Standard", [])

    # ── G-Sheet include/exclude tags (always shown for every client) ─────────
    gsheet_inc_raw = str(jira.get("gsheet_tags") or "").strip()
    gsheet_exc_raw = str(jira.get("gsheet_exclude_tags") or "").strip()
    seg = str(jira.get("segment") or "").strip()

    def _parse_tag_str(raw: str) -> list[str]:
        out = []
        for part in raw.split(","):
            part = part.strip()
            if part and part.lower() not in {"none", "-", "—", "n/a", ""}:
                out.append(part)
        return out

    gsheet_includes = _parse_tag_str(gsheet_inc_raw)
    gsheet_excludes = _parse_tag_str(gsheet_exc_raw)

    # ── ROW 1: Required Includes | Required Excludes ─────────────────────────
    parts.append('<div class="vp-two-col" style="margin-bottom:16px;">')

    # — Required Includes column —
    parts.append('<div class="vp-card">')
    parts.append('<div class="vp-card-title">Required Includes</div>')
    has_inc = False
    # G-Sheet includes (always, every client)
    for tag in gsheet_includes:
        parts.append(f'<span class="vp-tag vp-tag-inc" title="G-Sheet">📋 {_e(tag)}</span>')
        has_inc = True
    # Segment (from JIRA)
    if seg:
        parts.append(f'<span class="vp-tag vp-tag-inc" title="Segment">Segment: {_e(seg)}</span>')
        has_inc = True
    # Client config include filters
    for _f in _cfg_filters:
        if _f.get("mode") == "exclude":
            continue
        _ftype = _f.get("type", "")
        _fn    = _f.get("name") or _ftype or ""
        _fval  = _f.get("value", "")
        _fod   = _f.get("offset_days")
        if _ftype == "leaflet_tag" and _fod is not None:
            parts.append(f'<span class="vp-tag vp-tag-inc" title="Config">leaflet_tag={_e(str(_fod))}</span>')
        elif _fn and _fval:
            parts.append(f'<span class="vp-tag vp-tag-inc" title="Config">{_e(_fn)}={_e(str(_fval))}</span>')
        elif _fn:
            parts.append(f'<span class="vp-tag vp-tag-inc" title="Config">{_e(_fn)}</span>')
        has_inc = True
    if not has_inc:
        parts.append('<span style="color:#8890b5;font-size:12px;">None</span>')
    parts.append('</div>')

    # — Required Excludes column —
    parts.append('<div class="vp-card">')
    parts.append('<div class="vp-card-title">Required Excludes</div>')
    has_exc = False
    # G-Sheet excludes (always, every client)
    for tag in gsheet_excludes:
        parts.append(f'<span class="vp-tag vp-tag-exc" title="G-Sheet">📋 {_e(tag)}</span>')
        has_exc = True
    # Client config exclude filters
    for _f in _cfg_filters:
        if _f.get("mode") != "exclude":
            continue
        _ftype = _f.get("type", "")
        _fn    = _f.get("name") or _ftype or ""
        _fval  = _f.get("value", "") or _f.get("exclude_value", "")
        if _fn and _fval:
            parts.append(f'<span class="vp-tag vp-tag-exc" title="Config">{_e(_fn)}={_e(str(_fval))}</span>')
        elif _fn:
            parts.append(f'<span class="vp-tag vp-tag-exc" title="Config">{_e(_fn)}</span>')
        has_exc = True
    if not has_exc:
        parts.append('<span style="color:#8890b5;font-size:12px;">None</span>')
    parts.append('</div>')

    parts.append('</div>')  # end ROW 1

    # ── ROW 2: Actual API Tags (full width) ──────────────────────────────────
    all_api_tags = extract_all_tags(api)
    parts.append('<div class="vp-card" style="margin-bottom:16px;">')
    parts.append('<div class="vp-card-title">Actual API Tags</div>')
    if all_api_tags:
        for tg in all_api_tags:
            key_name = tg.get("name") or tg.get("type") or "filter"
            val = (tg.get("value") or tg.get("exclude_value") or tg.get("values") or
                   tg.get("exclude_values") or tg.get("offset_days") or "Active")
            is_excl = "exclude_value" in tg or "exclude_values" in tg or tg.get("mode") == "exclude"
            cls    = "vp-tag-exc" if is_excl else "vp-tag-inc"
            prefix = "Excl" if is_excl else "Incl"
            parts.append(f'<span class="vp-tag {cls}">{_e(prefix)}: {_e(key_name)}={_e(str(val))}</span>')
    else:
        parts.append('<span style="color:#8890b5;font-size:12px;">No tags detected in API payload</span>')
    parts.append('</div>')

    parts.append(_section("Client-Specific Filters"))

    # Use shared check_tags for all tag validation
    from utils import check_tags as _check_tags
    tag_result = _check_tags(jira, api, client)

    for exp_f in tag_result["expected_filters"]:
        found = any(_filter_matches(exp_f, act) for act in tag_result["api_filter_objs"])
        if not found:
            parts.append(_check("❌", "Missing filter", json.dumps(exp_f), "fail"))
    if not tag_result["missing_filters"]:
        if tag_result["expected_filters"]:
            parts.append(_check("✅", "All client filters", "Present and correct.", "ok"))
        else:
            parts.append(_check("ℹ️", "Filters", "No strict filters required for this client.", "warn"))

    uid = "raw_json"
    parts.append(
        f'<div class="vp-toggle-btn" style="margin-top:16px" onclick="toggleVis(\'{uid}\')">Show raw API output</div>'
        f'<pre class="vp-raw-pre" id="{uid}" style="display:none">{_e(json.dumps(api, indent=2))}</pre>'
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_results_html(
    jira: dict,
    api: dict,
    tmpl: dict | None,
    leaflet_data: list,
    client: str,
    ai_result: str,
    ai_urls: dict | None,
    dma_image_urls: list,
    dark: bool = True,
) -> str:
    """Return the full HTML results panel rendered via st_components.html."""
    apps = jira.get("approval_status") or []
    if not isinstance(apps, list):
        apps = [str(apps)]
    approved = bool(apps)
    issues = ai_result.count("❌") if ai_result else 0

    css = COMPONENT_CSS if dark else COMPONENT_CSS_LIGHT

    metrics_html = (
        f'<div class="vp-metrics">'
        f'<div class="vp-metric"><div class="vp-metric-label">Client</div>'
        f'<div class="vp-metric-value">{_e(client)}</div></div>'
        f'<div class="vp-metric"><div class="vp-metric-label">Scheduled Date</div>'
        f'<div class="vp-metric-value">{_e(str(jira.get("date", "—"))[:10])}</div></div>'
        f'<div class="vp-metric"><div class="vp-metric-label">AI Issues</div>'
        f'<div class="vp-metric-value {"danger" if issues else "ok"}">{issues}</div></div>'
        f'<div class="vp-metric"><div class="vp-metric-label">Approval</div>'
        f'<div class="vp-metric-value {"ok" if approved else "warn"}">'
        f'{"Approved" if approved else "Pending"}</div></div>'
        f'</div>'
    )

    nav_html = (
        '<div class="vp-nav-wrap">'
        '<div class="vp-nav">'
        '<div class="vp-nav-btn active" onclick="showTab(\'ai\',this)">🤖 AI Audit</div>'
        '<div class="vp-nav-btn" onclick="showTab(\'content\',this)">📝 Content</div>'
        '<div class="vp-nav-btn" onclick="showTab(\'visuals\',this)">🖼 Visuals</div>'
        '<div class="vp-nav-btn" onclick="showTab(\'tech\',this)">⚙️ Technical</div>'
        '</div></div>'
    )

    ai_html      = _build_ai_panel(jira, ai_result, jira.get("carousel_images") or [], dma_image_urls)
    content_html = _build_content_panel(jira, api, tmpl, leaflet_data, ai_urls, client=client)
    visuals_html = _build_visuals_panel(jira, api, tmpl, leaflet_data)
    tech_html    = _build_tech_panel(jira, api, client)

    panels = (
        f'<div id="vp-panel-ai"      class="vp-panel active">{ai_html}</div>'
        f'<div id="vp-panel-content" class="vp-panel">{content_html}</div>'
        f'<div id="vp-panel-visuals" class="vp-panel">{visuals_html}</div>'
        f'<div id="vp-panel-tech"    class="vp-panel">{tech_html}</div>'
    )

    return css + metrics_html + nav_html + panels + _JS

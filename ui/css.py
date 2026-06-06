"""Custom CSS injection for the Data Chat app."""

import streamlit as st


def inject_css():
    st.markdown(
        """
<style>
/* ── Global ─────────────────────────── */
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stSidebar"] { background: #161b27; border-right: 1px solid #1e293b; }

/* ── Chat messages ───────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 12px;
    padding: 0.6rem 0.8rem;
    margin-bottom: 0.25rem;
}

/* User bubble */
[data-testid="stChatMessageContent"][class*="user"] {
    background: rgba(99, 102, 241, 0.1);
    border: 1px solid rgba(99, 102, 241, 0.25);
    border-radius: 12px;
    padding: 0.75rem 1rem;
}

/* ── Expanders ───────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    background: #161b27;
}
[data-testid="stExpander"] summary {
    font-size: 0.82rem;
    color: #64748b;
    font-weight: 500;
}
[data-testid="stExpander"] summary:hover { color: #94a3b8; }

/* ── Code blocks ─────────────────────── */
pre {
    border-radius: 8px !important;
    border: 1px solid #1e293b !important;
}

/* ── Plotly chart background ──────────── */
.js-plotly-plot .plotly { border-radius: 10px; }

/* ── Sidebar divider ─────────────────── */
hr { border-color: #1e293b !important; }

/* ── Input box ───────────────────────── */
[data-testid="stChatInputTextArea"] {
    background: #161b27 !important;
    border: 1px solid #334155 !important;
    border-radius: 10px !important;
}

/* ── Hide default footer & menu ──────── */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""",
        unsafe_allow_html=True,
    )

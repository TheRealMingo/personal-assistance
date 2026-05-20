"""Inject mobile-responsive CSS into any Streamlit page."""

from __future__ import annotations

import streamlit as st

_MOBILE_CSS = """
<style>
/* ── Mobile-responsive overrides ──────────────────────────────────────── */
@media (max-width: 768px) {
    /* Reduce horizontal padding on small screens */
    [data-testid="stMainBlockContainer"],
    [data-testid="stBottomBlockContainer"] {
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }

    /* Force all columns to stack vertically */
    [data-testid="column"] {
        width: 100% !important;
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }

    /* Make data tables horizontally scrollable */
    [data-testid="stDataFrame"],
    .stDataFrame {
        overflow-x: auto !important;
    }

    /* Reduce font size in tables on small screens */
    .dataframe td,
    .dataframe th {
        font-size: 0.78rem !important;
        padding: 0.25rem 0.4rem !important;
    }

    /* Prevent sidebar from obscuring content on mobile */
    [data-testid="stSidebar"] {
        min-width: 0 !important;
    }

    /* Reduce metric label size */
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }

    /* Chat input full-width */
    [data-testid="stChatInput"] {
        width: 100% !important;
    }

    /* Wrap long code blocks */
    pre, code {
        white-space: pre-wrap !important;
        word-break: break-word !important;
    }
}
</style>
"""


def inject_mobile_css() -> None:
    """Inject mobile-responsive CSS into the current Streamlit page."""
    st.markdown(_MOBILE_CSS, unsafe_allow_html=True)

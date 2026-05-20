"""Global search sidebar widget + file preview modal dialog.

Usage — call once per page at the **page level** (outside any sidebar block):

    from utils.global_search_sidebar import render_global_search
    render_global_search()

The function handles both the sidebar search widget and the modal preview
dialog.  It is a no-op when Global Search is disabled in Settings.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from config.config import config
from config.runtime_settings import load_settings

_VAULT_LABELS: dict[str, str] = {
    "obsidian_vault_exercise_path": "Exercise",
    "obsidian_vault_task_list_path": "Tasks",
    "obsidian_vault_shopping_list_path": "Shopping",
    "obsidian_vault_daily_routine_path": "Routine",
    "obsidian_vault_weight_path": "Weight",
    "obsidian_vault_book_path": "Books",
}


@st.cache_data(ttl=30, show_spinner=False)
def _global_search(query: str) -> dict[str, list[dict]]:
    """Search all vault directories for *query*.

    Returns ``{label: [{"name": ..., "path": ..., "snippet": ...}, ...]}``.
    """
    results: dict[str, list[dict]] = {}
    q_lower = query.strip().lower()
    if not q_lower:
        return results

    for cfg_key, label in _VAULT_LABELS.items():
        vault_path = Path(config.get(cfg_key, "."))
        if not vault_path.is_dir():
            continue
        matches: list[dict] = []
        for md_file in vault_path.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if q_lower not in text.lower():
                continue
            idx = text.lower().find(q_lower)
            start = max(0, idx - 60)
            end = min(len(text), idx + 120)
            snippet = text[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(text):
                snippet += "…"
            matches.append({"name": md_file.stem, "path": str(md_file), "snippet": snippet})
        if matches:
            results[label] = matches
    return results


@st.dialog("📄 File Preview", width="large")
def _file_preview_dialog(match: dict) -> None:
    """Modal dialog showing formatted file contents for a search result."""
    preview_path = Path(match["path"])
    st.caption(f"`{preview_path.name}` — `{preview_path.parent}`")
    st.divider()
    try:
        raw = preview_path.read_text(encoding="utf-8", errors="replace")
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                st.markdown("**Frontmatter**")
                st.code(parts[1].strip(), language="yaml")
                body = parts[2].strip()
                if body:
                    st.markdown("**Content**")
                    st.markdown(body, unsafe_allow_html=True)
            else:
                st.code(raw, language="markdown")
        else:
            st.markdown(raw, unsafe_allow_html=True)
    except OSError as exc:
        st.error(f"Could not read file: {exc}")


def _render_search_sidebar_widgets() -> None:
    """Render the search input and result list inside the sidebar."""
    with st.sidebar:
        st.divider()
        with st.expander("🔍 Global Search", expanded=False):
            search_query = st.text_input(
                "Search all data",
                key="global_search_query",
                placeholder="tasks, exercise, shopping…",
                label_visibility="collapsed",
            )
            if search_query:
                with st.spinner("Searching…"):
                    search_results = _global_search(search_query)
                if search_results:
                    for label, matches in search_results.items():
                        st.markdown(
                            f"**{label}** "
                            f"({len(matches)} match{'es' if len(matches) != 1 else ''})"
                        )
                        for m in matches[:5]:
                            btn_key = f"sr_{abs(hash(m['path']))}"
                            if st.button(m["name"], key=btn_key, use_container_width=True):
                                st.session_state["_search_preview"] = m
                                st.rerun()
                            st.caption(m["snippet"])
                        if len(matches) > 5:
                            st.caption(f"…and {len(matches) - 5} more")
                else:
                    st.caption("No results found.")


def render_global_search() -> None:
    """Render the Global Search sidebar widget and handle the preview modal.

    Call once per page at page level (outside any ``with st.sidebar:`` block).
    Safe to call even when Global Search is disabled — becomes a no-op.
    """
    settings = load_settings()
    if not settings.get("global_search_enabled", True):
        return

    _render_search_sidebar_widgets()

    # Open the preview dialog when a result was clicked on the previous rerun.
    if "_search_preview" in st.session_state:
        _file_preview_dialog(st.session_state.pop("_search_preview"))

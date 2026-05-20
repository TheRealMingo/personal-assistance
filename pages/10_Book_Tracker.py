"""Streamlit page for the Book Tracker — manage your reading list."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from yaml import safe_load, dump as yaml_dump

from config.config import config
from tools.book_tool import (
    add_book_tool,
    update_book_tool,
    delete_book_tool,
    BOOK_STATUSES,
    _format_author,
)
from utils.global_search_sidebar import render_global_search
from utils.mobile_css import inject_mobile_css

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Book Tracker", page_icon="📚", layout="wide")
inject_mobile_css()
render_global_search()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)

_STATUS_EMOJI = {
    "To Be Read": "📖",
    "Currently Reading": "🔖",
    "Read": "✅",
    "Did not finish": "❌",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def load_books(vault_path: str) -> pd.DataFrame:
    """Read all book `.md` notes into a tidy DataFrame."""
    columns = ["Title", "Author", "Genre", "Status", "Notes", "File"]
    folder = Path(vault_path)
    if not folder.exists():
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for md_file in sorted(folder.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            logging.warning("Could not read %s: %s", md_file, exc)
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 2:
            continue
        try:
            data = safe_load(parts[1]) or {}
        except Exception as exc:  # noqa: BLE001
            logging.warning("YAML parse error in %s: %s", md_file, exc)
            continue
        if not isinstance(data, dict):
            continue

        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        tags_lower = [str(t).lstrip("#").lower() for t in tags]
        if tags_lower and "book" not in tags_lower:
            continue

        rows.append(
            {
                "Title": md_file.stem,
                "Author": _format_author(data.get("author", "")),
                "Genre": str(data.get("genre", "") or ""),
                "Status": str(data.get("status", "To Be Read") or "To Be Read"),
                "Notes": str(data.get("Notes", "") or ""),
                "File": md_file.name,
            }
        )

    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        status_order = {s: i for i, s in enumerate(BOOK_STATUSES)}
        df["_sort"] = df["Status"].map(lambda s: status_order.get(s, 99))
        df = df.sort_values(["_sort", "Title"]).drop(columns=["_sort"]).reset_index(drop=True)
    return df


def _update_book_note(file_name: str, row: dict[str, Any]) -> None:
    """Rewrite a book note's frontmatter with values from *row*."""
    folder = Path(config["obsidian_vault_book_path"])
    path = folder / file_name
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No frontmatter found in {file_name}")
    body = text[match.end():]
    data = safe_load(match.group(1)) or {}

    new_status = str(row.get("Status", "To Be Read")).strip()
    if new_status not in BOOK_STATUSES:
        new_status = "To Be Read"

    data["author"] = str(row.get("Author", "")).strip()
    data["genre"] = str(row.get("Genre", "")).strip()
    data["Notes"] = str(row.get("Notes", "")).strip()
    data["status"] = new_status
    data["read"] = new_status == "Read"

    new_yaml = yaml_dump(data, default_flow_style=False, sort_keys=False, indent=2)

    new_title = str(row.get("Title", "")).strip()
    old_stem = Path(file_name).stem

    if new_title and new_title != old_stem:
        safe_new = new_title.replace("/", "-").replace("\\", "-")
        new_path = folder / f"{safe_new}.md"
        if new_path.exists():
            raise ValueError(f"A book named '{new_title}' already exists.")
        path.write_text(f"---\n{new_yaml}---{body}", encoding="utf-8")
        path.rename(new_path)
    else:
        path.write_text(f"---\n{new_yaml}---{body}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Book cover lookup
# ---------------------------------------------------------------------------

def _ol_user_agent() -> str:
    """Return the User-Agent string for Open Library API requests."""
    if config.get("book_tracker_user_agent"):
        return config["book_tracker_user_agent"]
    email = config.get("book_tracker_contact_email") or "unknown"
    return f"PersonalAssistant ({email})"


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_cover_url(title: str, author: str = "") -> str | None:
    """Search Open Library by title and return a cover image URL, or None."""
    import json
    import urllib.parse
    import urllib.request

    params: dict[str, str] = {"title": title, "limit": "1", "fields": "cover_i"}
    if author:
        params["author"] = author
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _ol_user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        docs = data.get("docs", [])
        if docs and docs[0].get("cover_i"):
            cover_id = docs[0]["cover_i"]
            return f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# Open Library search
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _search_open_library(title: str) -> list[dict]:
    """Search Open Library by title and return up to 5 candidate books."""
    import json
    import urllib.parse
    import urllib.request

    params = {"title": title, "limit": "5", "fields": "title,author_name,subject,cover_i"}
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _ol_user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        results = []
        for doc in data.get("docs", []):
            author_str = _format_author(doc.get("author_name", []))
            subjects = doc.get("subject", [])
            genre = subjects[0] if subjects else ""
            results.append({
                "title": doc.get("title", ""),
                "author": author_str,
                "genre": genre,
                "cover_i": doc.get("cover_i"),
            })
        return results
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Edit dialog
# ---------------------------------------------------------------------------

@st.dialog("Edit Book")
def _edit_book_dialog(row: Any, file_name: str) -> None:
    """Modal dialog for editing a single book note."""
    st.caption(f"File: `{file_name}`")

    current_title = str(row.get("Title", "")).strip()
    current_author = str(row.get("Author", "")).strip()
    current_genre = str(row.get("Genre", "")).strip()
    current_status = str(row.get("Status", "To Be Read")).strip()
    if current_status not in BOOK_STATUSES:
        current_status = "To Be Read"
    current_notes = str(row.get("Notes", "")).strip()

    # Consume any OL-prefilled data from a previous lookup. We write directly
    # to the widget-state keys so the values take effect even though the
    # text_input widgets have explicit `key=` parameters (which causes
    # Streamlit to ignore the `value=` default after first render).
    ol_prefill = st.session_state.pop(f"ol_apply_{file_name}", None)
    if ol_prefill:
        st.session_state[f"edit_title_{file_name}"]  = ol_prefill.get("title",  current_title)
        st.session_state[f"edit_author_{file_name}"] = ol_prefill.get("author", current_author)
        st.session_state[f"edit_genre_{file_name}"]  = ol_prefill.get("genre",  current_genre)
    title_default  = st.session_state.get(f"edit_title_{file_name}",  current_title)
    author_default = st.session_state.get(f"edit_author_{file_name}", current_author)
    genre_default  = st.session_state.get(f"edit_genre_{file_name}",  current_genre)

    # Cover (refresh if author changed after OL apply)
    cover_url = _fetch_cover_url(title_default, author_default)
    if cover_url:
        img_col, _ = st.columns([1, 3])
        with img_col:
            st.image(cover_url, width=110)

    # --- Open Library lookup (outside form so it doesn't submit) -----------
    ol_results_key = f"ol_results_{file_name}"
    if st.button("🔍 Look up on Open Library", key=f"ol_lookup_{file_name}"):
        with st.spinner("Searching Open Library..."):
            results = _search_open_library(title_default)
        if results:
            st.session_state[ol_results_key] = results
        else:
            st.warning("No results found on Open Library.")
        st.rerun()

    if ol_results_key in st.session_state:
        results = st.session_state[ol_results_key]
        options = ["— select a match —"] + [
            f"{r['title']} — {r['author']}" for r in results
        ]
        sel = st.selectbox("Open Library results", options, key=f"ol_sel_{file_name}")
        if sel != "— select a match —":
            chosen = results[options.index(sel) - 1]
            cover_preview = (
                f"https://covers.openlibrary.org/b/id/{chosen['cover_i']}-M.jpg"
                if chosen.get("cover_i") else None
            )
            if cover_preview:
                prev_col, _ = st.columns([1, 4])
                with prev_col:
                    st.image(cover_preview, width=80, caption="Preview")
            if st.button("✅ Apply to form", key=f"ol_apply_btn_{file_name}"):
                st.session_state[f"ol_apply_{file_name}"] = chosen
                st.session_state.pop(ol_results_key, None)
                st.rerun()

    st.divider()

    with st.form(f"edit_book_form_{file_name}"):
        new_title = st.text_input(
            "Title", value=title_default, key=f"edit_title_{file_name}"
        )
        c1, c2 = st.columns(2)
        with c1:
            new_author = st.text_input(
                "Author", value=author_default, key=f"edit_author_{file_name}"
            )
        with c2:
            new_genre = st.text_input(
                "Genre", value=genre_default, key=f"edit_genre_{file_name}"
            )
        new_status = st.selectbox(
            "Status",
            options=BOOK_STATUSES,
            index=BOOK_STATUSES.index(current_status),
            format_func=lambda s: f"{_STATUS_EMOJI.get(s, '')} {s}",
            key=f"edit_status_{file_name}",
        )
        new_notes = st.text_area(
            "Notes", value=current_notes, height=120, key=f"edit_notes_{file_name}"
        )

        btn_cols = st.columns(3)
        with btn_cols[0]:
            save_clicked = st.form_submit_button(
                "💾 Save", type="primary", use_container_width=True
            )
        with btn_cols[2]:
            cancel_clicked = st.form_submit_button(
                "Cancel", use_container_width=True
            )

    logging.info(
        "Edit dialog buttons: save=%s cancel=%s file=%s",
        save_clicked, cancel_clicked, file_name,
    )

    if cancel_clicked:
        st.session_state.pop(ol_results_key, None)
        st.session_state["book_table_nonce"] = st.session_state.get("book_table_nonce", 0) + 1
        st.session_state.pop("book_editing_file", None)
        st.rerun()

    if save_clicked:
        logging.info(
            "Saving book %s -> title=%r author=%r genre=%r status=%r notes=%r",
            file_name, new_title, new_author, new_genre, new_status, new_notes,
        )
        if not new_title.strip():
            st.error("Title is required.")
            return
        updated: dict[str, Any] = {
            "Title": new_title.strip(),
            "Author": new_author.strip(),
            "Genre": new_genre.strip(),
            "Status": new_status,
            "Notes": new_notes.strip(),
        }
        try:
            _update_book_note(file_name, updated)
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to update book")
            st.error(f"Failed to update book: {exc}")
            return
        load_books.clear()
        st.session_state.pop(ol_results_key, None)
        for k in (
            f"edit_title_{file_name}",
            f"edit_author_{file_name}",
            f"edit_genre_{file_name}",
            f"edit_status_{file_name}",
            f"edit_notes_{file_name}",
        ):
            st.session_state.pop(k, None)
        st.session_state["book_table_nonce"] = st.session_state.get("book_table_nonce", 0) + 1
        st.session_state.pop("book_editing_file", None)
        st.toast("Book updated.", icon="📚")
        logging.info("Book %s saved successfully.", file_name)
        st.rerun()

    # --- Delete section ---
    st.divider()
    if st.session_state.get(f"confirm_delete_book_{file_name}"):
        st.warning("⚠️ **Permanently delete this book note?** This cannot be undone.")
        d_cols = st.columns(2)
        if d_cols[0].button("Yes, delete", type="primary", width="stretch", key=f"book_del_yes_{file_name}"):
            try:
                (Path(config["obsidian_vault_book_path"]) / file_name).unlink()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not delete file: {exc}")
                return
            load_books.clear()
            st.session_state.pop(f"confirm_delete_book_{file_name}", None)
            st.session_state["book_table_nonce"] = st.session_state.get("book_table_nonce", 0) + 1
            st.session_state.pop("book_editing_file", None)
            st.toast("Book deleted.", icon="🗑️")
            st.rerun()
        if d_cols[1].button("No, keep", width="stretch", key=f"book_del_no_{file_name}"):
            st.session_state.pop(f"confirm_delete_book_{file_name}", None)
            st.rerun()
    else:
        if st.button("🗑️ Delete book", key=f"book_del_btn_{file_name}"):
            st.session_state[f"confirm_delete_book_{file_name}"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("📚 Book Tracker")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

vault_path = config.get("obsidian_vault_book_path", ".")
df = load_books(vault_path)

col_refresh, col_info = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh"):
        load_books.clear()
        st.rerun()
with col_info:
    st.caption(f"Loaded **{len(df)}** book notes from `{vault_path}`")

# --- Stats -----------------------------------------------------------------
if not df.empty:
    stat_cols = st.columns(len(BOOK_STATUSES))
    for i, status in enumerate(BOOK_STATUSES):
        count = int((df["Status"] == status).sum())
        stat_cols[i].metric(f"{_STATUS_EMOJI[status]} {status}", count)
    st.divider()

# --- Add new book ----------------------------------------------------------
with st.expander("➕ Add a new book", expanded=False):
    bc1, bc2 = st.columns(2)
    with bc1:
        add_title = st.text_input("Title *", key="book_add_title")
        add_author = st.text_input("Author", key="book_add_author")
        add_genre = st.text_input("Genre", key="book_add_genre")
    with bc2:
        add_status = st.selectbox(
            "Status",
            options=BOOK_STATUSES,
            index=0,
            key="book_add_status",
            format_func=lambda s: f"{_STATUS_EMOJI.get(s, '')} {s}",
        )
        add_notes = st.text_area("Notes (optional)", key="book_add_notes", height=100)

    # --- Open Library lookup for new book ----------------------------------
    if st.button("🔍 Search Open Library", key="book_add_ol_btn"):
        title_q = st.session_state.get("book_add_title", "").strip()
        if title_q:
            with st.spinner("Searching Open Library..."):
                add_ol_results = _search_open_library(title_q)
            if add_ol_results:
                st.session_state["book_add_ol_results"] = add_ol_results
            else:
                st.warning("No results found on Open Library.")
        else:
            st.warning("Enter a title first.")

    if "book_add_ol_results" in st.session_state:
        add_results = st.session_state["book_add_ol_results"]
        add_options = ["— select a match —"] + [
            f"{r['title']} — {r['author']}" for r in add_results
        ]
        add_sel = st.selectbox("Open Library results", add_options, key="book_add_ol_sel")
        if add_sel != "— select a match —":
            add_chosen = add_results[add_options.index(add_sel) - 1]
            add_cover = (
                f"https://covers.openlibrary.org/b/id/{add_chosen['cover_i']}-M.jpg"
                if add_chosen.get("cover_i") else None
            )
            if add_cover:
                prev_col, _ = st.columns([1, 5])
                with prev_col:
                    st.image(add_cover, width=80, caption="Preview")
            if st.button("✅ Apply", key="book_add_ol_apply"):
                st.session_state["book_add_title"]  = add_chosen["title"]
                st.session_state["book_add_author"] = add_chosen["author"]
                st.session_state["book_add_genre"]  = add_chosen.get("genre", "")
                st.session_state.pop("book_add_ol_results", None)
                st.rerun()

    st.divider()
    if st.button("Add book", type="primary", key="book_add_submit"):
        if not add_title.strip():
            st.error("Title is required.")
        else:
            try:
                response = add_book_tool.invoke(
                    {
                        "title": add_title.strip(),
                        "author": add_author.strip(),
                        "genre": add_genre.strip(),
                        "notes": add_notes.strip(),
                        "status": add_status,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to add book")
                st.error(f"Failed to add book: {exc}")
            else:
                st.success(response)
                for k in ("book_add_title", "book_add_author", "book_add_genre",
                          "book_add_status", "book_add_notes"):
                    st.session_state.pop(k, None)
                load_books.clear()
                st.rerun()

if df.empty:
    st.info("No books found. Add one above to get started!")
    st.stop()

# --- Filters ---------------------------------------------------------------
st.subheader("Filters")
f_cols = st.columns(3)
with f_cols[0]:
    sel_status = st.multiselect(
        "Status",
        options=BOOK_STATUSES,
        default=[],
        key="book_filter_status",
        format_func=lambda s: f"{_STATUS_EMOJI.get(s, '')} {s}",
    )
with f_cols[1]:
    genre_options = sorted(g for g in df["Genre"].unique() if g)
    sel_genres = st.multiselect("Genre", genre_options, default=[], key="book_filter_genre")
with f_cols[2]:
    book_search = st.text_input("Search (title / author)", "", key="book_filter_search")

filtered = df.copy()
if sel_status:
    filtered = filtered[filtered["Status"].isin(sel_status)]
if sel_genres:
    filtered = filtered[filtered["Genre"].isin(sel_genres)]
if book_search.strip():
    _q = book_search.strip().lower()
    filtered = filtered[
        filtered["Title"].str.lower().str.contains(_q, na=False)
        | filtered["Author"].str.lower().str.contains(_q, na=False)
    ]

# --- Table -----------------------------------------------------------------
st.subheader("All Books")

if filtered.empty:
    st.info("No books match the current filters.")
else:
    st.caption("Click any row to open an edit modal.")

    display_df = filtered[["Title", "Author", "Genre", "Status", "Notes", "File"]].reset_index(drop=True)
    display_df["Status"] = display_df["Status"].apply(
        lambda s: f"{_STATUS_EMOJI.get(s, '')} {s}"
    )

    selection_state = st.dataframe(
        display_df.drop(columns=["File", "Notes"]),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Title": st.column_config.TextColumn("Title", width="large"),
            "Author": st.column_config.TextColumn("Author"),
            "Genre": st.column_config.TextColumn("Genre"),
            "Status": st.column_config.TextColumn("Status"),
        },
        key=f"book_table_editor_{st.session_state.get('book_table_nonce', 0)}",
    )

    selected_rows = (
        getattr(getattr(selection_state, "selection", None), "rows", None)
        or (
            selection_state.get("selection", {}).get("rows")
            if isinstance(selection_state, dict)
            else None
        )
        or []
    )
    if selected_rows:
        sel_idx = int(selected_rows[0])
        sel_row = filtered.iloc[sel_idx]
        st.session_state["book_editing_file"] = str(sel_row["File"])

    editing_file = st.session_state.get("book_editing_file")
    if editing_file:
        match = filtered[filtered["File"] == editing_file]
        if not match.empty:
            _edit_book_dialog(match.iloc[0], editing_file)
        else:
            # File no longer present (renamed/deleted) — clear state.
            st.session_state.pop("book_editing_file", None)

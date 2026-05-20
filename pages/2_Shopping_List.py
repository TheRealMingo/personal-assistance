"""Streamlit page for managing the shopping list."""

from __future__ import annotations
from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search

import logging
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from tools.shopping_list_tool import (
    delete_shopping_item_raw,
    list_shopping_items_raw,
    save_shopping_item_raw,
)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Shopping List", page_icon="🛒", layout="wide")
inject_mobile_css()
render_global_search()
st.title("🛒 Shopping List")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")


@st.cache_data(ttl=15, show_spinner=False)
def _load_items() -> list[dict[str, Any]]:
    return list_shopping_items_raw()


def _to_dataframe(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for it in items:
        rows.append(
            {
                "Item": it.get("item", ""),
                "Description": it.get("description", "") or "",
                "URL": it.get("url", "") or "",
                "Price": it.get("price"),
                "Category": it.get("category", "") or "",
                "Bought": bool(it.get("bought", False)),
                "Date Created": it.get("Date Created", ""),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
ctrl_cols = st.columns([1, 1, 6])
with ctrl_cols[0]:
    if st.button("🔄 Refresh", width='stretch'):
        _load_items.clear()
        st.rerun()
with ctrl_cols[1]:
    show_add = st.toggle("➕ Add item", value=False, key="shop_show_add")

# ---------------------------------------------------------------------------
# Add new item form
# ---------------------------------------------------------------------------
if show_add:
    # Build sorted unique list of existing categories from current items so the
    # new-item form can offer them in a dropdown (with an "Other" escape hatch).
    _existing_categories = sorted(
        {
            str(it.get("category") or "").strip()
            for it in _load_items()
            if str(it.get("category") or "").strip()
        },
        key=str.lower,
    )
    _OTHER_LABEL = "Other"
    _cat_options = [*_existing_categories, _OTHER_LABEL]

    # Generation counter: incrementing it changes all widget keys, which
    # resets every field to its default value after a successful add.
    if "shop_add_gen" not in st.session_state:
        st.session_state.shop_add_gen = 0
    _gen = st.session_state.shop_add_gen

    st.markdown("**Add a new item**")
    c1, c2 = st.columns(2)
    with c1:
        new_item = st.text_input("Item *", key=f"shop_new_item_{_gen}")
        new_url = st.text_input("URL", key=f"shop_new_url_{_gen}")
        new_price = st.number_input(
            "Price", min_value=0.0, step=0.01, value=0.0, key=f"shop_new_price_{_gen}"
        )
    with c2:
        cat_choice = st.selectbox(
            "Category",
            options=_cat_options,
            index=0,
            key=f"shop_new_cat_select_{_gen}",
            help="Pick an existing category or choose Other to add a new one.",
        )
        if cat_choice == _OTHER_LABEL:
            new_category_text = st.text_input(
                "New category name",
                key=f"shop_new_cat_other_{_gen}",
                placeholder="e.g. Office supplies",
            )
        else:
            new_category_text = cat_choice.strip()
        new_bought = st.checkbox(
            "Already bought", value=False, key=f"shop_new_bought_{_gen}"
        )
    new_description = st.text_area("Description", key=f"shop_new_desc_{_gen}")

    if st.button("Add to shopping list", type="primary", key=f"shop_add_btn_{_gen}", width='stretch'):
        new_category = new_category_text.strip()
        if not new_item.strip():
            st.error("Item name is required.")
        elif cat_choice == _OTHER_LABEL and not new_category:
            st.error("Please type a new category name (or pick an existing one).")
        else:
            try:
                save_shopping_item_raw(
                    original_name=None,
                    item=new_item,
                    description=new_description,
                    url=new_url,
                    price=new_price if new_price > 0 else None,
                    category=new_category,
                    bought=new_bought,
                )
                _load_items.clear()
                st.session_state.shop_add_gen += 1
                st.success(f"Added '{new_item}'.")
                st.rerun()
            except FileExistsError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not add item: {exc}")

# ---------------------------------------------------------------------------
# Filters & sorting
# ---------------------------------------------------------------------------
items = _load_items()
df = _to_dataframe(items)

if df.empty:
    st.info("Your shopping list is empty. Add an item to get started.")
    st.stop()

with st.expander("🔎 Filter & sort", expanded=True):
    fc = st.columns(4)
    with fc[0]:
        text_search = st.text_input("Search (item/description)", key="shop_filter_text")
    with fc[1]:
        category_options = sorted({c for c in df["Category"].fillna("") if c})
        selected_categories = st.multiselect(
            "Category", category_options, key="shop_filter_category"
        )
    with fc[2]:
        bought_filter = st.selectbox(
            "Bought status",
            ["All", "Not bought", "Bought"],
            key="shop_filter_bought",
        )
    with fc[3]:
        sort_column = st.selectbox(
            "Sort by",
            ["Item", "Category", "Price", "Bought", "Date Created"],
            index=0,
            key="shop_sort_col",
        )
    sort_desc = st.checkbox("Descending", value=False, key="shop_sort_desc")

filtered = df.copy()
if text_search.strip():
    pattern = text_search.strip()
    filtered = filtered[
        filtered["Item"].str.contains(pattern, case=False, na=False)
        | filtered["Description"].str.contains(pattern, case=False, na=False)
    ]
if selected_categories:
    filtered = filtered[filtered["Category"].isin(selected_categories)]
if bought_filter == "Bought":
    filtered = filtered[filtered["Bought"]]
elif bought_filter == "Not bought":
    filtered = filtered[~filtered["Bought"]]

filtered = filtered.sort_values(
    by=sort_column, ascending=not sort_desc, na_position="last"
).reset_index(drop=True)

# ---------------------------------------------------------------------------
# Edit modal dialog
# ---------------------------------------------------------------------------

@st.dialog("Edit shopping item")
def _edit_item_dialog(row: Any, original_name: str) -> None:
    """Modal that lets the user edit every field of a single shopping item."""
    _existing_cats = sorted(
        {
            str(it.get("category") or "").strip()
            for it in _load_items()
            if str(it.get("category") or "").strip()
        },
        key=str.lower,
    )
    _OTHER_LABEL = "Other"
    _cat_opts = [*_existing_cats, _OTHER_LABEL]

    st.caption(f"Editing: **{original_name}**")

    c1, c2 = st.columns(2)
    with c1:
        edit_item = st.text_input("Item *", value=str(row["Item"]))
        edit_url = st.text_input("URL", value=str(row["URL"] or ""))
        edit_price = st.number_input(
            "Price",
            min_value=0.0,
            step=0.01,
            value=float(row["Price"]) if pd.notna(row["Price"]) and row["Price"] else 0.0,
        )
    with c2:
        current_cat = str(row["Category"] or "").strip()
        if current_cat and current_cat in _existing_cats:
            cat_index = _cat_opts.index(current_cat)
        else:
            cat_index = len(_cat_opts) - 1  # "Other"
        cat_choice = st.selectbox("Category", options=_cat_opts, index=cat_index)
        if cat_choice == _OTHER_LABEL:
            edit_category = st.text_input(
                "New category name", value=current_cat if current_cat not in _existing_cats else ""
            )
        else:
            edit_category = cat_choice
        edit_bought = st.checkbox("Bought", value=bool(row["Bought"]))
    edit_description = st.text_area("Description", value=str(row["Description"] or ""))

    btn_cols = st.columns(2)
    if btn_cols[0].button("💾 Save", type="primary", width="stretch", key="shop_edit_save"):
        if not edit_item.strip():
            st.error("Item name is required.")
        elif cat_choice == _OTHER_LABEL and not edit_category.strip():
            st.error("Please enter a category name.")
        else:
            try:
                save_shopping_item_raw(
                    original_name=original_name,
                    item=edit_item.strip(),
                    description=edit_description,
                    url=edit_url,
                    price=edit_price if edit_price > 0 else None,
                    category=edit_category.strip(),
                    bought=edit_bought,
                    date_created=str(row["Date Created"] or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
                )
                _load_items.clear()
                st.session_state.pop("shop_table", None)
                st.toast("Item updated.", icon="✅")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Failed to update: {exc}")
    if btn_cols[1].button("Cancel", width="stretch", key="shop_edit_cancel"):
        st.session_state.pop("shop_table", None)
        st.rerun()

    st.divider()
    if st.session_state.get("confirm_delete_shop_item"):
        st.warning("⚠️ **Permanently delete this item?** This cannot be undone.")
        d_cols = st.columns(2)
        if d_cols[0].button("Yes, delete", type="primary", width="stretch", key="shop_del_confirm"):
            try:
                delete_shopping_item_raw(original_name)
                _load_items.clear()
                st.session_state.pop("confirm_delete_shop_item", None)
                st.session_state.pop("shop_table", None)
                st.toast("Item deleted.", icon="🗑️")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not delete: {exc}")
        if d_cols[1].button("No, keep", width="stretch", key="shop_del_cancel"):
            st.session_state.pop("confirm_delete_shop_item", None)
            st.rerun()
    else:
        if st.button("🗑️ Delete item", key="shop_del_btn"):
            st.session_state["confirm_delete_shop_item"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Items table (hidden while the Add Item panel is open)
# ---------------------------------------------------------------------------
if not show_add:
    st.subheader(f"Items ({len(filtered)})")
    st.caption("Click a row to open an edit modal.")

    table_df = filtered.drop(columns=["Date Created"]).reset_index(drop=True)
    sel_state = st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Item": st.column_config.TextColumn("Item"),
            "Description": st.column_config.TextColumn("Description"),
            "URL": st.column_config.LinkColumn(
                "URL",
                help="Click to open in a new tab.",
                display_text="Open ↗",
            ),
            "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "Category": st.column_config.TextColumn("Category"),
            "Bought": st.column_config.CheckboxColumn("Bought"),
        },
        key="shop_table",
    )
    sel_rows = getattr(getattr(sel_state, "selection", None), "rows", None) or []
    if sel_rows:
        sel_idx = int(sel_rows[0])
        sel_row = filtered.reset_index(drop=True).iloc[sel_idx]
        _edit_item_dialog(sel_row, str(sel_row["Item"]))


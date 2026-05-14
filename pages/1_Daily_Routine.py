"""Streamlit page: Daily Routine Tracker."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from yaml import safe_load

from config.config import config
from config.daily_routine import ALL_ITEMS, MORNING_ITEMS, NIGHT_ITEMS
from tools.daily_routine_tool import (
    complete_routine_item_tool,
    uncomplete_routine_item_tool,
    complete_morning_routine_tool,
    complete_night_routine_tool,
    get_todays_routine_status_tool,
)

st.set_page_config(page_title="Daily Routine", page_icon="🗓️", layout="wide")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
VAULT = Path(config["obsidian_vault_daily_routine_path"])


@st.cache_data(ttl=15, show_spinner=False)
def load_history(days: int) -> pd.DataFrame:
    """Return a DataFrame indexed by date with one boolean column per item."""
    rows = []
    today = date.today()
    if VAULT.exists():
        for path in VAULT.glob("*.md"):
            try:
                d = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if (today - d).days > days:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            m = FRONTMATTER_RE.match(text)
            if not m:
                continue
            data = safe_load(m.group(1)) or {}
            row = {"Date": d}
            for item in ALL_ITEMS:
                row[item] = bool(data.get(item, False))
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["Date", *ALL_ITEMS, "Morning %", "Night %"])
    df = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    df["Morning %"] = df[MORNING_ITEMS].sum(axis=1) / len(MORNING_ITEMS) * 100
    df["Night %"] = df[NIGHT_ITEMS].sum(axis=1) / len(NIGHT_ITEMS) * 100
    return df


@st.cache_data(ttl=15, show_spinner=False)
def list_available_dates() -> list[date]:
    """Return every date that has an existing routine note, newest first."""
    dates: list[date] = []
    if VAULT.exists():
        for path in VAULT.glob("*.md"):
            try:
                dates.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
    return sorted(dates, reverse=True)


def _on_checkbox_change(item: str, key: str) -> None:
    if st.session_state[key]:
        complete_routine_item_tool.invoke({"item_name": item})
    else:
        uncomplete_routine_item_tool.invoke({"item_name": item})
    load_history.clear()


def _render_period(period_name: str, items: list[str], today_row: pd.Series) -> None:
    # Reserve a slot for the progress bar; we fill it AFTER the checkboxes so
    # it reflects the current session_state (i.e. the just-clicked value)
    # rather than the stale `today_row` snapshot from before the click.
    progress_slot = st.empty()

    cols = st.columns(2)
    for i, item in enumerate(items):
        with cols[i % 2]:
            key = f"{period_name}-{item}"
            checked = bool(today_row[item])
            # Force the widget's state to mirror the on-disk value on every
            # render. Without this, Streamlit's session_state takes precedence
            # over `value=` and bulk-completes do not visually check the box.
            st.session_state[key] = checked
            st.checkbox(
                item,
                key=key,
                on_change=_on_checkbox_change,
                args=(item, key),
            )

    done = sum(1 for item in items if st.session_state.get(f"{period_name}-{item}"))
    pct = done / len(items) * 100
    progress_slot.progress(
        pct / 100, text=f"{period_name}: {done}/{len(items)} ({pct:.1f}%)"
    )

    bulk_label = f"✅ Complete entire {period_name.lower()} routine"
    if st.button(bulk_label, key=f"bulk-{period_name}"):
        if period_name == "Morning":
            complete_morning_routine_tool.invoke({})
        else:
            complete_night_routine_tool.invoke({})
        load_history.clear()
        # Clear stored widget state so the next render reflects disk truth.
        for item in items:
            st.session_state.pop(f"{period_name}-{item}", None)
        st.rerun()


# ---------------- UI ----------------

st.title("🗓️ Daily Routine")
if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

window = st.sidebar.slider("Trend window (days)", 7, 90, 30)
if st.sidebar.button("🔄 Refresh"):
    load_history.clear()
    list_available_dates.clear()
    st.rerun()

# Ensure today's note exists so it always appears in the picker.
if date.today() not in set(list_available_dates()):
    get_todays_routine_status_tool.invoke({})
    load_history.clear()
    list_available_dates.clear()

available_dates = list_available_dates()
selected = st.selectbox(
    "Date",
    options=available_dates,
    index=0,
    format_func=lambda d: d.isoformat(),
)

df = load_history(window)
known_dates = set(df["Date"]) if not df.empty else set()

if selected not in known_dates:
    # The selected date exists on disk but falls outside the trend window;
    # load just that one note for the editor view.
    from tools.daily_routine_tool import (  # local import to avoid cycles
        _ensure_all_items,
        _note_path,
        _read_note,
    )
    payload = _read_note(_note_path(selected))
    if payload is None:
        st.info(f"No routine note exists for {selected.isoformat()} yet.")
        today_row = None
    else:
        payload = _ensure_all_items(payload)
        today_row = pd.Series({"Date": selected, **{i: bool(payload.get(i)) for i in ALL_ITEMS}})
else:
    today_row = df.loc[df["Date"] == selected].iloc[0]

if today_row is not None:
    morning_tab, night_tab = st.tabs(["🌅 Morning (9 items)", "🌙 Night (14 items)"])
    with morning_tab:
        _render_period("Morning", MORNING_ITEMS, today_row)
    with night_tab:
        _render_period("Night", NIGHT_ITEMS, today_row)

# ---- Trends ----
st.divider()
st.subheader(f"Trends — last {window} days")
if df.empty:
    st.caption("No data yet.")
else:
    long_pct = df.melt(
        id_vars="Date",
        value_vars=["Morning %", "Night %"],
        var_name="Period",
        value_name="Percent",
    )
    x_end = date.today()
    x_start = x_end - timedelta(days=window)
    line = (
        alt.Chart(long_pct)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "Date:T",
                scale=alt.Scale(domain=[x_start.isoformat(), x_end.isoformat()]),
            ),
            y=alt.Y("Percent:Q", scale=alt.Scale(domain=[0, 100])),
            color="Period:N",
            tooltip=["Date:T", "Period:N", "Percent:Q"],
        )
        .properties(height=300)
    )
    st.altair_chart(line, use_container_width=True)

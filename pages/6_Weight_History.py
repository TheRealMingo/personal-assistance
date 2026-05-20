"""Streamlit page for browsing weight history from the Obsidian vault."""

from __future__ import annotations
from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import altair as alt
from yaml import safe_load, dump as yaml_dump

from config.config import config
from tools.obsidian_tool import create_weight_note_tool

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Weight History", page_icon="⚖️", layout="wide")
inject_mobile_css()
render_global_search()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
NUMBER_RE = re.compile(r"([-+]?\d*\.?\d+)")


def _parse_weight(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = NUMBER_RE.search(str(raw))
    return float(match.group(1)) if match else None


@st.cache_data(ttl=60, show_spinner=False)
def load_weights(vault_path: str) -> pd.DataFrame:
    """Read all `Weight *.md` and `Weight-*.md` notes into a tidy DataFrame."""
    folder = Path(vault_path)
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return pd.DataFrame(columns=["Date", "Weight (lbs)", "File"])

    seen: set[Path] = set()
    files = list(folder.glob("Weight *.md")) + list(folder.glob("Weight-*.md"))
    for file in files:
        if file in seen:
            continue
        seen.add(file)
        try:
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            logging.warning("Could not read %s: %s", file, exc)
            continue
        match = FRONTMATTER_RE.match(text)
        if not match:
            continue
        try:
            data = safe_load(match.group(1)) or {}
        except Exception as exc:  # noqa: BLE001
            logging.warning("YAML parse error in %s: %s", file, exc)
            continue

        norm = (
            {str(k).strip().lower(): v for k, v in data.items()}
            if isinstance(data, dict)
            else {}
        )

        weight_lbs = _parse_weight(norm.get("weight"))
        if weight_lbs is None:
            continue

        raw_date = norm.get("date")
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            try:
                parsed_date = pd.to_datetime(file.stat().st_mtime, unit="s")
            except OSError:
                parsed_date = pd.NaT

        rows.append(
            {
                "Date": parsed_date,
                "Weight (lbs)": weight_lbs,
                "File": str(file.resolve()),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Date", ascending=False, na_position="last").reset_index(
            drop=True
        )
    return df


# ---------------------------------------------------------------------------
# Note update / delete helpers
# ---------------------------------------------------------------------------


def _update_weight_note(file_path: str, new_dt: datetime, new_weight: float) -> None:
    """Rewrite the YAML frontmatter of a weight note with updated date and weight."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    text = p.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("No YAML frontmatter found in note.")
    data = safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    key_map = {str(k).strip().lower(): k for k in data.keys()}
    data[key_map.get("date", "Date")] = new_dt.strftime("%Y-%m-%dT%H:%M:%S")
    data[key_map.get("weight", "Weight")] = new_weight
    new_fm = f"---\n{yaml_dump(data, sort_keys=False, allow_unicode=True)}---\n"
    p.write_text(FRONTMATTER_RE.sub(new_fm, text, count=1), encoding="utf-8")


@st.dialog("Edit weight entry")
def _edit_weight_dialog(row: Any, file_path: str) -> None:
    st.caption(f"File: `{Path(file_path).name}`")
    raw_date = row["Date"]
    if pd.notna(raw_date):
        dt_val = pd.Timestamp(raw_date).to_pydatetime()
        date_default = dt_val.date()
        time_default = dt_val.time().replace(second=0, microsecond=0)
    else:
        _now = datetime.now()
        date_default = _now.date()
        time_default = _now.time().replace(second=0, microsecond=0)
    c1, c2 = st.columns(2)
    with c1:
        new_date = st.date_input("Date", value=date_default)
    with c2:
        new_time = st.time_input("Time", value=time_default, step=60)
    new_weight = st.number_input(
        "Weight (lbs)",
        min_value=0.0,
        max_value=1000.0,
        value=float(row["Weight (lbs)"]),
        step=0.1,
        format="%.1f",
    )
    btn_cols = st.columns(2)
    if btn_cols[0].button("💾 Save", type="primary", width='stretch', key="weight_edit_save"):
        try:
            combined_dt = datetime.combine(new_date, new_time)
            _update_weight_note(file_path, combined_dt, new_weight)
            load_weights.clear()
            st.session_state.pop("weight_table", None)
            st.toast("Weight entry updated.", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(f"Failed to update: {exc}")
    if btn_cols[1].button("Cancel", width='stretch', key="weight_edit_cancel"):
        st.session_state.pop("weight_table", None)
        st.rerun()
    st.divider()
    if st.session_state.get("confirm_delete_weight"):
        st.warning("⚠️ **Permanently delete this entry?** This cannot be undone.")
        d_cols = st.columns(2)
        if d_cols[0].button("Yes, delete", type="primary", width='stretch', key="weight_del_confirm"):
            try:
                Path(file_path).unlink()
                load_weights.clear()
                st.session_state.pop("confirm_delete_weight", None)
                st.session_state.pop("weight_table", None)
                st.toast("Weight entry deleted.", icon="🗑️")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete: {exc}")
        if d_cols[1].button("No, keep", width='stretch', key="weight_del_cancel"):
            st.session_state.pop("confirm_delete_weight", None)
            st.rerun()
    else:
        if st.button("🗑️ Delete entry", key="weight_del_btn"):
            st.session_state["confirm_delete_weight"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("⚖️ Weight History")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

vault_path = config["obsidian_vault_weight_path"]
df = load_weights(vault_path)

col_refresh, col_info = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh"):
        load_weights.clear()
        st.rerun()
with col_info:
    st.caption(f"Loaded **{len(df)}** weight notes from `{vault_path}`")

# --- Quick log -------------------------------------------------------------
with st.expander("➕ Log a new weight", expanded=False):
    with st.form("weight_log_form", clear_on_submit=True):
        new_weight = st.number_input(
            "Weight (lbs)",
            min_value=0.0,
            max_value=1000.0,
            value=150.0,
            step=0.1,
            format="%.1f",
        )
        submitted = st.form_submit_button("Log weight")
        if submitted:
            try:
                response = create_weight_note_tool.invoke({"weight": float(new_weight)})
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to log weight")
                st.error(f"Failed to log weight: {exc}")
            else:
                st.success("Weight logged!")
                st.markdown(response)
                load_weights.clear()
                st.rerun()

if df.empty:
    st.info("No weight notes found. Log one above to get started!")
    st.stop()

# --- Filters ---------------------------------------------------------------
st.subheader("Filters")
filter_cols = st.columns(2)

valid_dates = df["Date"].dropna()
min_d = valid_dates.min().date() if not valid_dates.empty else date.today()
max_d = valid_dates.max().date() if not valid_dates.empty else date.today()

with filter_cols[0]:
    date_range = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max(max_d, date.today()),
        key="weight_filter_dates",
    )
with filter_cols[1]:
    min_w, max_w = float(df["Weight (lbs)"].min()), float(df["Weight (lbs)"].max())
    if min_w == max_w:
        max_w = min_w + 1.0
    weight_range = st.slider(
        "Weight range (lbs)",
        min_value=float(min_w),
        max_value=float(max_w),
        value=(float(min_w), float(max_w)),
        step=0.1,
        key="weight_filter_weight",
    )

filtered = df.copy()
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_ts = pd.Timestamp(date_range[0])
    end_ts = pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)
    filtered = filtered[
        filtered["Date"].notna()
        & (filtered["Date"] >= start_ts)
        & (filtered["Date"] < end_ts)
    ]
filtered = filtered[
    (filtered["Weight (lbs)"] >= weight_range[0])
    & (filtered["Weight (lbs)"] <= weight_range[1])
]

# --- Stats -----------------------------------------------------------------
st.subheader("Stats")
if filtered.empty:
    st.info("No weight entries match the current filters.")
else:
    stat_cols = st.columns(4)
    latest_row = filtered.dropna(subset=["Date"]).sort_values("Date", ascending=False)
    latest_weight = (
        latest_row["Weight (lbs)"].iloc[0] if not latest_row.empty else None
    )
    stat_cols[0].metric("Latest", f"{latest_weight:.1f} lbs" if latest_weight else "—")
    stat_cols[1].metric("Average", f"{filtered['Weight (lbs)'].mean():.1f} lbs")
    stat_cols[2].metric("Min", f"{filtered['Weight (lbs)'].min():.1f} lbs")
    stat_cols[3].metric("Max", f"{filtered['Weight (lbs)'].max():.1f} lbs")

# --- Table -----------------------------------------------------------------
st.subheader("All Weights")

if filtered.empty:
    st.info("No weight entries to display.")
else:
    st.caption("Click a row to edit or delete.")
    table_df = filtered.drop(columns=["File"]).reset_index(drop=True)
    sel_state = st.dataframe(
        table_df,
        width='stretch',
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD HH:mm"),
            "Weight (lbs)": st.column_config.NumberColumn(
                "Weight (lbs)", format="%.1f"
            ),
        },
        key="weight_table",
    )
    sel_rows = getattr(getattr(sel_state, "selection", None), "rows", None) or []
    if sel_rows:
        sel_idx = int(sel_rows[0])
        sel_row = filtered.reset_index(drop=True).iloc[sel_idx]
        _edit_weight_dialog(sel_row, str(sel_row["File"]))

# --- Trend chart -----------------------------------------------------------
st.subheader("Progress Over Time")

charted = filtered.dropna(subset=["Date"]).copy()
if charted.empty:
    st.info("No dated weight entries to chart with the current filters.")
else:
    chart_min = charted["Date"].min().date()
    chart_max = charted["Date"].max().date()

    range_choice = st.radio(
        "Time range",
        ["7 days", "30 days", "90 days", "1 year", "All time", "Custom"],
        horizontal=True,
        index=4,
        key="weight_chart_range",
    )

    today = date.today()
    if range_choice == "Custom":
        custom = st.date_input(
            "Custom range",
            value=(chart_min, chart_max),
            min_value=chart_min,
            max_value=max(chart_max, today),
            key="weight_chart_custom_range",
        )
        if isinstance(custom, tuple) and len(custom) == 2:
            start, end = custom
        else:
            start, end = chart_min, chart_max
    else:
        end = max(chart_max, today)
        if range_choice == "All time":
            start = chart_min
        else:
            days = {"7 days": 7, "30 days": 30, "90 days": 90, "1 year": 365}[
                range_choice
            ]
            start = end - timedelta(days=days)

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    chart_df = charted[(charted["Date"] >= start_ts) & (charted["Date"] < end_ts)].copy()

    if chart_df.empty:
        st.info("No data in the selected time range.")
    else:
        chart_df = chart_df.sort_values("Date").set_index("Date")[["Weight (lbs)"]]

        opt_cols = st.columns(2)
        with opt_cols[0]:
            show_chart = st.toggle(
                "Show weight chart", value=True, key="weight_show_chart"
            )
        with opt_cols[1]:
            show_rolling = st.toggle(
                "Show 7-entry rolling average",
                value=True,
                key="weight_show_rolling",
            )

        if show_chart:
            plot_df = chart_df.copy()
            if show_rolling and len(plot_df) >= 2:
                window = min(7, len(plot_df))
                plot_df["Rolling Avg"] = (
                    plot_df["Weight (lbs)"].rolling(window=window, min_periods=1).mean()
                )

            long_df = (
                plot_df.reset_index()
                .melt(id_vars="Date", var_name="Series", value_name="Value")
                .dropna(subset=["Value"])
            )
            chart = (
                alt.Chart(long_df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Date:T", title="Date"),
                    y=alt.Y(
                        "Value:Q",
                        scale=alt.Scale(domain=[135, 185]),
                        title="Weight (lbs)",
                    ),
                    color=alt.Color("Series:N", title=""),
                    tooltip=[
                        alt.Tooltip("Date:T"),
                        alt.Tooltip("Series:N"),
                        alt.Tooltip("Value:Q", format=".1f", title="Weight (lbs)"),
                    ],
                )
                .properties(height=400)
            )
            st.altair_chart(chart, width='stretch')  # altair uses width='stretch'

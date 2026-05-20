"""Streamlit page for browsing exercise history from the Obsidian vault."""

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
from yaml import safe_load, dump as yaml_dump

from config.config import config
from config.exercise_mapping import MUSCLE_GROUPS, get_muscle_group, list_exercises

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Exercise History", page_icon="📈", layout="wide")
inject_mobile_css()
render_global_search()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
WEIGHT_RE = re.compile(r"([-+]?\d*\.?\d+)")


def _parse_weight(raw: Any) -> float:
    """Return weight in lbs as float. Bodyweight / unknown -> 0.0."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text or text.lower().startswith("body"):
        return 0.0
    match = WEIGHT_RE.search(text)
    return float(match.group(1)) if match else 0.0


def _parse_reps(raw: Any) -> float:
    """Best-effort numeric extraction from the 'Duration / Reps' field."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    match = WEIGHT_RE.search(str(raw))
    return float(match.group(1)) if match else 0.0


def _parse_sets(raw: Any) -> int:
    if raw is None:
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _update_exercise_note(file_path, row) -> None:
    """Update the Obsidian markdown frontmatter for an exercise with values from a row."""
    file = Path(file_path)
    if not file.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    text = file.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("No YAML frontmatter found in note.")
    data = safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        data = {}

    # Build a case-insensitive map of original keys to preserve casing/order
    key_map = {str(k).strip().lower(): k for k in data.keys()}

    def set_field(field_name: str, value: Any) -> None:
        target_key = key_map.get(field_name.lower(), field_name)
        data[target_key] = value

    date_val = row["Date"]
    if pd.isna(date_val):
        date_str = ""
    elif hasattr(date_val, "strftime"):
        date_str = date_val.strftime("%Y-%m-%d %H:%M")
    else:
        date_str = str(date_val)

    set_field("Exercise", str(row["Exercise"]))
    set_field("Date", date_str)
    # The reps/duration field name in notes varies; try common variants.
    reps_key = key_map.get("duration / reps") or key_map.get("reps/duration") or "Duration / Reps"
    data[reps_key] = row["Reps/Duration"]
    set_field("Sets", row["Sets"])
    weight_key = key_map.get("weight") or key_map.get("weight (lbs)") or "Weight"
    weight_val = row["Weight (lbs)"]
    data[weight_key] = "Bodyweight" if not weight_val else f"{weight_val} lbs"
    primary_key = key_map.get("primary muscle group") or "Primary Muscle Group"
    if primary_key in data and row.get("Muscle Group") is not None:
        data[primary_key] = row["Muscle Group"]

    new_frontmatter = f"---\n{yaml_dump(data, sort_keys=False, allow_unicode=True)}---\n"
    new_text = FRONTMATTER_RE.sub(new_frontmatter, text, count=1)
    file.write_text(new_text, encoding="utf-8")


@st.cache_data(ttl=60, show_spinner=False)
def load_exercises(vault_path: str) -> pd.DataFrame:
    """Read all `Exercise-*.md` notes and return a tidy DataFrame."""
    folder = Path(vault_path)
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return pd.DataFrame(
            columns=[
                "Exercise",
                "Date",
                "Reps/Duration",
                "Sets",
                "Weight (lbs)",
                "Muscle Group",
                "File",
            ]
        )

    seen: set[Path] = set()
    files = list(folder.glob("Exercise *.md")) + list(folder.glob("Exercise-*.md"))
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

        # Normalize keys for case-insensitive lookup (notes vary: 'weight' vs 'Weight').
        norm = {str(k).strip().lower(): v for k, v in data.items()} if isinstance(data, dict) else {}

        exercise = str(norm.get("exercise", "")).strip()
        if not exercise:
            continue
        raw_date = norm.get("date")
        try:
            parsed_date = pd.to_datetime(raw_date, errors="coerce")
        except Exception:  # noqa: BLE001
            parsed_date = pd.NaT

        muscle_group = (
            str(norm.get("primary muscle group") or get_muscle_group(exercise))
            .strip()
            .lower()
        )

        rows.append(
            {
                "Exercise": exercise,
                "Date": parsed_date,
                "Reps/Duration": _parse_reps(norm.get("duration / reps")),
                "Sets": _parse_sets(norm.get("sets")),
                "Weight (lbs)": _parse_weight(norm.get("weight")),
                "Muscle Group": muscle_group,
                "File": str(file.resolve()),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Date", ascending=False, na_position="last").reset_index(
            drop=True
        )
    return df


def _nearest_weight_option(weight_lbs: float) -> str:
    """Map a weight value to the closest option in the Track Exercise dropdown."""
    if weight_lbs <= 0:
        return "Bodyweight"
    snapped = max(5, min(100, int(round(weight_lbs / 5.0)) * 5))
    return f"{snapped} lbs"


def _prefill_track_exercise(row: pd.Series) -> None:
    """Seed Track Exercise widget keys via session_state, then switch page."""
    exercise = str(row["Exercise"]).strip()
    known = exercise in list_exercises()

    st.session_state["track_exercise_selection"] = exercise if known else "Other"
    if not known:
        st.session_state["track_exercise_custom_name"] = exercise
        muscle = str(row["Muscle Group"]).strip().lower()
        st.session_state["track_exercise_custom_muscle_group"] = (
            muscle if muscle in MUSCLE_GROUPS else MUSCLE_GROUPS[0]
        )

    st.session_state["track_exercise_measurement_type"] = "Number of Reps"
    reps_value = row["Reps/Duration"]
    if pd.notna(reps_value) and float(reps_value) > 0:
        st.session_state["track_exercise_measurement_value"] = str(int(reps_value))
    sets_value = row["Sets"]
    if sets_value:
        st.session_state["track_exercise_num_sets"] = str(int(sets_value))
    st.session_state["track_exercise_weight"] = _nearest_weight_option(
        float(row["Weight (lbs)"])
    )

    st.switch_page("pages/5_Track_Exercise.py")


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("📈 Exercise History")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

vault_path = config["obsidian_vault_exercise_path"]
df = load_exercises(vault_path)

col_refresh, col_info = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh"):
        load_exercises.clear()
        st.rerun()
with col_info:
    st.caption(f"Loaded **{len(df)}** exercise notes from `{vault_path}`")

if df.empty:
    st.info("No exercise notes found. Track an exercise to get started!")
    st.stop()

# --- Filters ---------------------------------------------------------------
st.subheader("Filters")
filter_cols = st.columns(3)

exercise_options = sorted(df["Exercise"].dropna().unique().tolist())
muscle_options = sorted(df["Muscle Group"].dropna().unique().tolist())

with filter_cols[0]:
    selected_exercises = st.multiselect(
        "Exercise name", exercise_options, default=[], key="hist_filter_exercise"
    )
with filter_cols[1]:
    selected_muscles = st.multiselect(
        "Muscle group", muscle_options, default=[], key="hist_filter_muscle"
    )
with filter_cols[2]:
    name_search = st.text_input(
        "Search exercise (contains)", "", key="hist_filter_search"
    )

filtered = df.copy()
if selected_exercises:
    filtered = filtered[filtered["Exercise"].isin(selected_exercises)]
if selected_muscles:
    filtered = filtered[filtered["Muscle Group"].isin(selected_muscles)]
if name_search.strip():
    filtered = filtered[
        filtered["Exercise"].str.contains(name_search.strip(), case=False, na=False)
    ]

# --- Table -----------------------------------------------------------------
st.subheader("All Exercises")

# Week-scoped views. Weeks start on Sunday: Python's weekday() is Mon=0..Sun=6,
# so days since the most recent Sunday is (weekday() + 1) % 7.
today = date.today()
current_week_start = today - timedelta(days=(today.weekday() + 1) % 7)
previous_week_start = current_week_start - timedelta(days=7)
previous_week_end = current_week_start  # exclusive upper bound

view_choice = st.radio(
    "View",
    options=["All", "This week (Sun–Sat)", "Last week (Sun–Sat)"],
    horizontal=True,
    key="hist_view_choice",
    help="Weeks start on Sunday.",
)

view_df = filtered.copy()
if view_choice != "All":
    view_df = view_df.dropna(subset=["Date"])
    if view_choice == "This week (Sun–Sat)":
        start_ts = pd.Timestamp(current_week_start)
        end_ts = pd.Timestamp(current_week_start + timedelta(days=7))
        st.caption(
            f"Showing exercises from **{current_week_start:%a %Y-%m-%d}** "
            f"through **{(current_week_start + timedelta(days=6)):%a %Y-%m-%d}**."
        )
    else:
        start_ts = pd.Timestamp(previous_week_start)
        end_ts = pd.Timestamp(previous_week_end)
        st.caption(
            f"Showing exercises from **{previous_week_start:%a %Y-%m-%d}** "
            f"through **{(previous_week_start + timedelta(days=6)):%a %Y-%m-%d}**."
        )
    view_df = view_df[(view_df["Date"] >= start_ts) & (view_df["Date"] < end_ts)]

editor_key = {
    "All": "hist_table_editor",
    "This week (Sun–Sat)": "hist_table_editor_this_week",
    "Last week (Sun–Sat)": "hist_table_editor_last_week",
}[view_choice]


@st.dialog("Edit exercise")
def _edit_exercise_dialog(row: pd.Series, file_path: str, table_key: str) -> None:
    """Modal that lets the user edit every field of a single exercise row."""
    from pathlib import Path as _Path
    st.caption(f"File: `{_Path(file_path).name}`")

    raw_date = row["Date"]
    if pd.notna(raw_date) and hasattr(raw_date, "to_pydatetime"):
        dt_val = raw_date.to_pydatetime()
        date_default = dt_val.date()
        time_default = dt_val.time().replace(second=0, microsecond=0)
    else:
        dt_now = datetime.now()
        date_default = dt_now.date()
        time_default = dt_now.time().replace(second=0, microsecond=0)

    with st.form(f"edit_form_{table_key}"):
        new_exercise = st.text_input("Exercise", value=str(row["Exercise"]))
        c1, c2 = st.columns(2)
        with c1:
            new_date = st.date_input("Date", value=date_default)
        with c2:
            new_time = st.time_input("Time", value=time_default)
        c3, c4, c5 = st.columns(3)
        with c3:
            new_reps = st.number_input(
                "Reps / Duration",
                min_value=0.0,
                value=float(row["Reps/Duration"] or 0),
                step=1.0,
            )
        with c4:
            new_sets = st.number_input(
                "Sets",
                min_value=0,
                value=int(row["Sets"] or 0),
                step=1,
            )
        with c5:
            new_weight = st.number_input(
                "Weight (lbs)  — 0 = Bodyweight",
                min_value=0.0,
                value=float(row["Weight (lbs)"] or 0),
                step=0.5,
            )

        muscle_options = MUSCLE_GROUPS if isinstance(MUSCLE_GROUPS, (list, tuple)) else list(MUSCLE_GROUPS)
        current_muscle = str(row.get("Muscle Group", "")).strip().lower()
        muscle_options_lc = [str(m).lower() for m in muscle_options]
        try:
            muscle_index = muscle_options_lc.index(current_muscle)
        except ValueError:
            muscle_index = 0
        new_muscle = st.selectbox(
            "Muscle Group",
            options=muscle_options,
            index=muscle_index if muscle_options else 0,
        )

        btn_cols = st.columns(3)
        save_clicked = btn_cols[0].form_submit_button("💾 Save", type="primary", width='stretch')
        repeat_clicked = btn_cols[1].form_submit_button("🔁 Repeat", width='stretch')
        cancel_clicked = btn_cols[2].form_submit_button("Cancel", width='stretch')

    if cancel_clicked:
        st.session_state.pop(table_key, None)
        st.session_state.pop(f"confirm_delete_{table_key}", None)
        st.rerun()

    if save_clicked or repeat_clicked:
        try:
            combined_dt = datetime.combine(new_date, new_time)
        except Exception:  # noqa: BLE001
            combined_dt = datetime.now()
        new_row = pd.Series(
            {
                "Exercise": new_exercise,
                "Date": pd.Timestamp(combined_dt),
                "Reps/Duration": new_reps,
                "Sets": new_sets,
                "Weight (lbs)": new_weight,
                "Muscle Group": new_muscle,
            }
        )
        try:
            _update_exercise_note(file_path, new_row)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to update {file_path}: {exc}")
            return
        load_exercises.clear()
        st.session_state.pop(table_key, None)
        st.session_state.pop(f"confirm_delete_{table_key}", None)
        if repeat_clicked:
            _prefill_track_exercise(new_row)
        else:
            st.toast(f"Updated {file_path}", icon="✅")
            st.rerun()

    # --- Delete section ---
    st.divider()
    if st.session_state.get(f"confirm_delete_{table_key}"):
        st.warning(
            "⚠️ **Permanently delete this exercise note?** This cannot be undone."
        )
        d_cols = st.columns(2)
        if d_cols[0].button("Yes, delete", type="primary", key=f"confirm_yes_{table_key}", width='stretch'):
            try:
                Path(file_path).unlink()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not delete file: {exc}")
                return
            load_exercises.clear()
            st.session_state.pop(f"confirm_delete_{table_key}", None)
            st.session_state.pop(table_key, None)
            st.toast("Exercise deleted.", icon="🗑️")
            st.rerun()
        if d_cols[1].button("No, keep", key=f"confirm_no_{table_key}", width='stretch'):
            st.session_state.pop(f"confirm_delete_{table_key}", None)
            st.rerun()
    else:
        if st.button("🗑️ Delete exercise", key=f"delete_btn_{table_key}"):
            st.session_state[f"confirm_delete_{table_key}"] = True
            st.rerun()


if view_df.empty:
    st.info("No exercises match the current filters.")
else:
    st.caption(
        "Click any cell in a row to open an edit modal with every field for that exercise."
    )

    table_df = view_df.drop(columns=["File"]).reset_index(drop=True)

    selection_state = st.dataframe(
        table_df,
        width='stretch',
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD HH:mm"),
            "Reps/Duration": st.column_config.NumberColumn("Reps/Duration"),
            "Sets": st.column_config.NumberColumn("Sets"),
            "Weight (lbs)": st.column_config.NumberColumn("Weight (lbs)", format="%.1f"),
        },
        key=editor_key,
    )

    selected_rows = (
        getattr(getattr(selection_state, "selection", None), "rows", None)
        or (selection_state.get("selection", {}).get("rows") if isinstance(selection_state, dict) else None)
        or []
    )
    if selected_rows:
        sel_idx = int(selected_rows[0])
        sel_row = view_df.reset_index(drop=True).iloc[sel_idx]
        _edit_exercise_dialog(sel_row, str(sel_row["File"]), editor_key)


# --- Trend chart -----------------------------------------------------------
st.subheader("Progress Over Time")

charted = filtered.dropna(subset=["Date"]).copy()
if charted.empty:
    st.info("No dated exercises to chart with the current filters.")
else:
    min_date = charted["Date"].min().date()
    max_date = charted["Date"].max().date()

    range_choice = st.radio(
        "Time range",
        ["7 days", "30 days", "90 days", "1 year", "All time", "Custom"],
        horizontal=True,
        index=4,
        key="hist_chart_range",
    )

    today = date.today()
    if range_choice == "Custom":
        start, end = st.date_input(
            "Custom range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max(max_date, today),
            key="hist_chart_custom_range",
        )
    else:
        end = max(max_date, today)
        if range_choice == "All time":
            start = min_date
        else:
            days = {"7 days": 7, "30 days": 30, "90 days": 90, "1 year": 365}[
                range_choice
            ]
            start = end - timedelta(days=days)

    chart_exercise_options = sorted(charted["Exercise"].unique().tolist())
    chart_exercises = st.multiselect(
        "Exercises to plot",
        chart_exercise_options,
        default=[],
        key="hist_chart_exercises",
    )

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    chart_df = charted[
        (charted["Date"] >= start_ts)
        & (charted["Date"] < end_ts)
        & (charted["Exercise"].isin(chart_exercises))
    ].copy()

    if chart_df.empty or not chart_exercises:
        st.info("No data in the selected time range / exercises.")
    else:
        weight_pivot = (
            chart_df.pivot_table(
                index="Date",
                columns="Exercise",
                values="Weight (lbs)",
                aggfunc="max",
            )
            .sort_index()
        )
        reps_pivot = (
            chart_df.pivot_table(
                index="Date",
                columns="Exercise",
                values="Reps/Duration",
                aggfunc="max",
            )
            .sort_index()
        )

        chart_cols = st.columns(2)
        with chart_cols[0]:
            show_weight = st.toggle(
                "Show weight chart", value=True, key="hist_show_weight_chart"
            )
            if show_weight:
                st.markdown("**Weight (lbs) over time**")
                st.line_chart(weight_pivot)
        with chart_cols[1]:
            show_reps = st.toggle(
                "Show reps/duration chart", value=True, key="hist_show_reps_chart"
            )
            if show_reps:
                st.markdown("**Reps / Duration over time**")
                st.line_chart(reps_pivot)

# --- Re-track / pre-fill ---------------------------------------------------
# (Per-row "Repeat" buttons live in the All Exercises table above.)

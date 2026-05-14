"""Streamlit page for browsing exercise history from the Obsidian vault."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from yaml import safe_load

from config.config import config
from config.exercise_mapping import MUSCLE_GROUPS, get_muscle_group, list_exercises

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Exercise History", page_icon="📈", layout="wide")

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
                "File": file.name,
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

    st.switch_page("pages/4_Track_Exercise.py")


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

if view_df.empty:
    st.info("No exercises match the current filters.")
else:
    st.caption(
        "Click a column header to sort. Select a row to repeat that exercise."
    )

    table_df = view_df.drop(columns=["File"]).reset_index(drop=True).copy()
    table_df.insert(0, "Repeat", False)

    edited_df = st.data_editor(
        table_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in table_df.columns if c != "Repeat"],
        column_config={
            "Repeat": st.column_config.CheckboxColumn(
                "Repeat",
                help="Check a row to open Track Exercise pre-filled with its details.",
                default=False,
            ),
            "Date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD HH:mm"),
            "Reps/Duration": st.column_config.NumberColumn("Reps/Duration"),
            "Sets": st.column_config.NumberColumn("Sets"),
            "Weight (lbs)": st.column_config.NumberColumn(
                "Weight (lbs)", format="%.1f"
            ),
        },
        key=editor_key,
    )

    repeat_rows = edited_df.index[edited_df["Repeat"]].tolist()
    if repeat_rows:
        _prefill_track_exercise(view_df.reset_index(drop=True).iloc[repeat_rows[0]])

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

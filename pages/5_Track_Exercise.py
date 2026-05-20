from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search
"""Streamlit page for tracking an exercise via the exercise tool."""

import logging
import re as _re

import streamlit as st

from config.exercise_mapping import MUSCLE_GROUPS, get_muscle_group, list_exercises
from tools.obsidian_tool import (
    create_exercise_duration_note_tool,
    create_exercise_reps_note_tool,
)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


MEASUREMENT_REPS = "Number of Reps"
MEASUREMENT_DURATION = "Duration"

WEIGHT_OPTIONS = ["Bodyweight"] + [f"{lbs} lbs" for lbs in range(5, 105, 5)]

st.set_page_config(page_title="Track Exercise", page_icon="🏋️‍♂️")
inject_mobile_css()
render_global_search()

def _weight_to_float(weight_str: str) -> float:
    """Convert weight selectbox label to float lbs (0.0 for Bodyweight)."""
    if weight_str == "Bodyweight":
        return 0.0
    m = _re.search(r"(\d+\.?\d*)", weight_str)
    return float(m.group(1)) if m else 0.0


st.title("Track Exercise")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

OTHER_OPTION = "Other"
exercises = list_exercises() + [OTHER_OPTION]
exercise_selection = st.selectbox(
    "Exercise", exercises, key="track_exercise_selection"
)

if exercise_selection == OTHER_OPTION:
    custom_exercise = st.text_input(
        "Custom Exercise Name", key="track_exercise_custom_name"
    )
    custom_muscle_group = st.selectbox(
        "Muscle Group", MUSCLE_GROUPS, key="track_exercise_custom_muscle_group"
    )
    exercise = custom_exercise.strip() or "<exercise>"
    muscle_group = custom_muscle_group
else:
    exercise = exercise_selection
    muscle_group = get_muscle_group(exercise)

measurement_type = st.selectbox(
    "Measurement Type",
    [MEASUREMENT_REPS, MEASUREMENT_DURATION],
    key="track_exercise_measurement_type",
)

if measurement_type == MEASUREMENT_REPS:
    measurement_value = st.text_input(
        "Number of Reps", key="track_exercise_measurement_value"
    )
    dur_h, dur_m, dur_s = 0, 0, 0
else:
    dur_cols = st.columns(3)
    with dur_cols[0]:
        dur_h = st.number_input(
            "Hours", min_value=0, max_value=23, value=0, step=1,
            key="track_exercise_dur_h",
        )
    with dur_cols[1]:
        dur_m = st.number_input(
            "Minutes", min_value=0, max_value=59, value=30, step=1,
            key="track_exercise_dur_m",
        )
    with dur_cols[2]:
        dur_s = st.number_input(
            "Seconds", min_value=0, max_value=59, value=0, step=1,
            key="track_exercise_dur_s",
        )
    measurement_value = f"{dur_h} hr {dur_m} min {dur_s} secs"
    # Keep the shared session-state key in sync for Exercise History prefill
    st.session_state["track_exercise_measurement_value"] = measurement_value

num_sets = st.text_input("Number of Sets", key="track_exercise_num_sets")

weight = st.selectbox(
    "Weight Used", WEIGHT_OPTIONS, key="track_exercise_weight"
)

st.caption(f"Muscle group: {muscle_group}")

if measurement_type == MEASUREMENT_REPS:
    _value_ok = bool(measurement_value.strip())
else:
    _value_ok = dur_h > 0 or dur_m > 0 or dur_s > 0

submit_disabled = not (
    _value_ok
    and num_sets.strip()
    and (exercise_selection != OTHER_OPTION or custom_exercise.strip())
)

if st.button("Track Exercise", disabled=submit_disabled, type="primary"):
    weight_float = _weight_to_float(weight)
    try:
        num_sets_int = int(num_sets.strip())
    except ValueError:
        st.error("Number of Sets must be a whole number.")
        st.stop()
    with st.spinner("Saving exercise…"):
        try:
            if measurement_type == MEASUREMENT_REPS:
                try:
                    reps_int = int(measurement_value.strip())
                except ValueError:
                    st.error("Number of Reps must be a whole number.")
                    st.stop()
                response = create_exercise_reps_note_tool.invoke(
                    {
                        "exercise_name": exercise,
                        "reps": reps_int,
                        "sets": num_sets_int,
                        "weight": weight_float,
                        "muscle_group": muscle_group,
                    }
                )
            else:
                response = create_exercise_duration_note_tool.invoke(
                    {
                        "exercise_name": exercise,
                        "duration": measurement_value,
                        "sets": num_sets_int,
                        "weight": weight_float,
                        "muscle_group": muscle_group,
                    }
                )
        except Exception as exc:  # surface failures to the user
            logging.exception("Exercise tool invocation failed")
            st.error(f"Failed to track exercise: {exc}")
        else:
            st.success("✅ Exercise tracked!")
            st.markdown(response)

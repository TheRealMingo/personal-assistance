"""Streamlit page for tracking an exercise via the exercise agent."""

import logging

import streamlit as st

from config.config import config
from config.exercise_mapping import MUSCLE_GROUPS, get_muscle_group, list_exercises
from subagents.subagent_tools import exercise_agent_tool

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


MEASUREMENT_REPS = "Number of Reps"
MEASUREMENT_DURATION = "Duration"

WEIGHT_OPTIONS = ["Bodyweight"] + [f"{lbs} lbs" for lbs in range(5, 105, 5)]

st.set_page_config(page_title="Track Exercise", page_icon="🏋️‍♂️")

def _build_prompt(
    exercise: str,
    measurement_type: str,
    measurement_value: str,
    num_sets: str,
    weight: str,
    muscle_group: str,
) -> str:
    weight_phrase = (
        "Bodyweight" if weight == "Bodyweight" else f"{weight}"
    )
    sets_clause = (
        f"{num_sets} Sets with Bodyweight"
        if weight == "Bodyweight"
        else f"{num_sets} Sets with {weight_phrase}"
    )

    if measurement_type == MEASUREMENT_REPS:
        return (
            f"Track Exercise {exercise}: {measurement_value} Reps for "
            f"{sets_clause} for {muscle_group}"
        )
    return (
        f"Track Exercise {exercise}: {measurement_value} for "
        f"{sets_clause} for {muscle_group}"
    )


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

measurement_label = (
    "Number of Reps"
    if measurement_type == MEASUREMENT_REPS
    else "Duration (e.g. 30 seconds, 5 minutes)"
)
measurement_value = st.text_input(
    measurement_label, key="track_exercise_measurement_value"
)

num_sets = st.text_input("Number of Sets", key="track_exercise_num_sets")

weight = st.selectbox(
    "Weight Used", WEIGHT_OPTIONS, key="track_exercise_weight"
)

st.caption(f"Muscle group: {muscle_group}")

preview_prompt = _build_prompt(
    exercise=exercise,
    measurement_type=measurement_type,
    measurement_value=measurement_value or "<value>",
    num_sets=num_sets or "<sets>",
    weight=weight,
    muscle_group=muscle_group,
)

st.text_area(
    "Prompt Preview",
    value=preview_prompt,
    height=120,
    disabled=True,
)

submit_disabled = not (
    measurement_value.strip()
    and num_sets.strip()
    and (exercise_selection != OTHER_OPTION or custom_exercise.strip())
)

if st.button("Submit to Exercise Agent", disabled=submit_disabled):
    final_prompt = _build_prompt(
        exercise=exercise,
        measurement_type=measurement_type,
        measurement_value=measurement_value.strip(),
        num_sets=num_sets.strip(),
        weight=weight,
        muscle_group=muscle_group,
    )
    logging.info("Track Exercise page submitting prompt: %s", final_prompt)
    with st.spinner("Exercise agent is tracking your exercise ..."):
        try:
            response = exercise_agent_tool.invoke({"prompt": final_prompt})
        except Exception as exc:  # surface failures to the user
            logging.exception("Exercise agent invocation failed")
            st.error(f"Failed to track exercise: {exc}")
        else:
            st.success("Exercise tracked!")
            st.markdown(response)
            download_tag = config["download_markdown_tag"]
            st.download_button(
                "Download markdown",
                data=f"{download_tag}\n\n{response}",
                file_name="exercise-tracked.md",
                mime="text/markdown",
                key="track_exercise_download",
            )

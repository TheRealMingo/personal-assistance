"""Streamlit page for browsing and managing the Obsidian task list."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt  # noqa: F401  (reserved for future charts)
import pandas as pd
import streamlit as st
from streamlit_calendar import calendar
from yaml import safe_load, dump

from config.config import config
from tools.obsidian_tool import (
    add_task_tool,
    complete_a_task_tool,
    uncomplete_a_task_tool,
)

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

st.set_page_config(page_title="Task List", page_icon="✅", layout="wide")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
PROJECT_LINK_RE = re.compile(r"\[\[(.*?)\]\]")


def _strip_project(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    match = PROJECT_LINK_RE.search(text)
    return match.group(1).strip() if match else text


def _parse_priority(raw: Any) -> int:
    if raw is None:
        return 5
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 5


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"true", "yes", "1", "completed", "done"}


@st.cache_data(ttl=30, show_spinner=False)
def load_tasks(vault_path: str) -> pd.DataFrame:
    """Read all task `.md` notes into a tidy DataFrame."""
    columns = [
        "Task",
        "Project",
        "Priority",
        "Due Date",
        "Date Created",
        "Date Completed",
        "Completed",
        "File",
    ]
    folder = Path(vault_path)
    if not folder.exists():
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for file in folder.glob("*.md"):
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

        # Treat every note in the task folder as a task (folder = source of truth).
        # If a `tags` field exists and explicitly excludes 'task', skip it.
        tags = norm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tags_lower = [str(t).lstrip("#").lower() for t in tags if t]
        if tags_lower and "task" not in tags_lower:
            continue

        # Title: prefer explicit Task field, otherwise use the filename stem.
        raw_title = norm.get("task")
        title = str(raw_title).strip() if raw_title else file.stem

        rows.append(
            {
                "Task": title,
                "Project": _strip_project(norm.get("project")),
                "Priority": _parse_priority(norm.get("priority")),
                "Due Date": pd.to_datetime(norm.get("due date"), errors="coerce"),
                "Date Created": pd.to_datetime(
                    norm.get("date created"), errors="coerce"
                ),
                "Date Completed": pd.to_datetime(
                    norm.get("date completed"), errors="coerce"
                ),
                "Completed": _parse_bool(norm.get("completed")),
                "File": file.name,
            }
        )

    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        df = df.sort_values(
            ["Completed", "Priority", "Due Date"],
            ascending=[True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    return df


def _set_completed(file_name: str, completed: bool) -> None:
    """Rewrite a task note's frontmatter to update the Completed flag."""
    folder = Path(config["obsidian_vault_task_list_path"])
    path = folder / file_name
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No frontmatter found in {file_name}")
    body = text[match.end():]
    data = safe_load(match.group(1)) or {}

    # Find the actual key (case-insensitive) for "Completed" and "Date Completed".
    completed_key = next(
        (k for k in data if str(k).strip().lower() == "completed"), "Completed"
    )
    date_completed_key = next(
        (k for k in data if str(k).strip().lower() == "date completed"),
        "Date Completed",
    )
    data[completed_key] = bool(completed)
    if completed:
        data[date_completed_key] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    else:
        data.pop(date_completed_key, None)

    new_yaml = dump(data, default_flow_style=False, sort_keys=False, indent=2)
    path.write_text(f"---\n{new_yaml}---{body}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("✅ Task List")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")

vault_path = config["obsidian_vault_task_list_path"]
df = load_tasks(vault_path)

col_refresh, col_info = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh"):
        load_tasks.clear()
        st.rerun()
with col_info:
    st.caption(f"Loaded **{len(df)}** task notes from `{vault_path}`")

# --- Quick add -------------------------------------------------------------
with st.expander("➕ Add a new task", expanded=False):
    # Get all existing projects
    existing_projects = sorted(
        [p for p in df["Project"].unique() if p and str(p).strip()]
    )
    project_options = list(existing_projects) + ["Other"]

    # Note: We use individual widgets + a regular button (not st.form) so the
    # "Other" text input can appear reactively when selected.
    c1, c2 = st.columns(2)
    with c1:
        new_task = st.text_input("Task", key="task_add_task")
        selected_project = st.selectbox(
            "Project (optional)",
            options=project_options,
            index=None,
            placeholder="Select a project or choose Other",
            key="task_add_project_select",
        )
        new_project = ""
        if selected_project == "Other":
            new_project = st.text_input(
                "New project name", key="task_add_new_project"
            )
    with c2:
        new_due = st.date_input(
            "Due date (optional)", value=None, key="task_add_due"
        )
        new_priority = st.number_input(
            "Priority (0 = highest, 5 = default)",
            min_value=0,
            max_value=5,
            value=5,
            step=1,
            key="task_add_priority",
        )

    if st.button("Add task", type="primary", key="task_add_submit"):
        if not new_task.strip():
            st.error("Task description is required.")
        elif selected_project == "Other" and not new_project.strip():
            st.error("Please enter a project name when selecting 'Other'.")
        else:
            payload: dict[str, Any] = {"task": new_task.strip()}
            if selected_project and selected_project != "Other":
                payload["project"] = selected_project.strip()
            elif new_project.strip():
                payload["project"] = new_project.strip()

            if new_due:
                payload["due_date"] = (
                    datetime.combine(new_due, datetime.min.time())
                    .strftime("%Y-%m-%dT%H:%M:%S")
                )
            payload["priority"] = int(new_priority)
            try:
                response = add_task_tool.invoke(payload)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to add task")
                st.error(f"Failed to add task: {exc}")
            else:
                st.success("Task added!")
                st.markdown(response)
                # Clear the inputs by removing their session state keys.
                for k in (
                    "task_add_task",
                    "task_add_project_select",
                    "task_add_new_project",
                    "task_add_due",
                    "task_add_priority",
                ):
                    st.session_state.pop(k, None)
                load_tasks.clear()
                st.rerun()

if df.empty:
    st.info("No tasks found. Add one above to get started!")
    st.stop()

# --- Calendar view --------------------------------------------------------
show_calendar = st.toggle(
    "Show due-date calendar", value=True, key="task_calendar_visible"
)

if show_calendar:
    st.subheader("📅 Due-Date Calendar")
    cal_source = df.dropna(subset=["Due Date"]).copy()
    if cal_source.empty:
        st.info("No tasks with a due date in the current filter.")
    else:
        # Color events by priority (0 = highest = red).
        priority_colors = {
            0: "#d62728",
            1: "#ff7f0e",
            2: "#ffbb33",
            3: "#2ca02c",
            4: "#1f77b4",
            5: "#9467bd",
        }

        events: list[dict[str, Any]] = []
        for _, row in cal_source.iterrows():
            due = row["Due Date"]
            completed = bool(row["Completed"])
            priority = int(row["Priority"]) if pd.notna(row["Priority"]) else 5
            color = "#888888" if completed else priority_colors.get(priority, "#1f77b4")
            title = row["Task"]
            if row["Project"]:
                title = f"[{row['Project']}] {title}"
            if completed:
                title = f"✓ {title}"
            events.append(
                {
                    "title": title,
                    "start": due.strftime("%Y-%m-%dT%H:%M:%S"),
                    "allDay": False,
                    "color": color,
                    "extendedProps": {
                        "file": row["File"],
                        "priority": priority,
                        "completed": completed,
                    },
                }
            )

        initial_date = date.today().strftime("%Y-%m-%d")

        calendar_options = {
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek,timeGridDay,listMonth",
            },
            "initialView": "dayGridMonth",
            "initialDate": initial_date,
            "selectable": True,
            "editable": False,
            "navLinks": True,
            "dayMaxEvents": True,
            "height": 650,
        }

        cal_state = calendar(
            events=events,
            options=calendar_options,
            key="task_calendar",
        )

        # streamlit-calendar returns the most recent interaction; show details for
        # whichever day or event the user last clicked.
        selected_day: date | None = None
        if isinstance(cal_state, dict):
            click_info = cal_state.get("dateClick") or cal_state.get("select")
            if click_info and click_info.get("date"):
                try:
                    selected_day = pd.Timestamp(click_info["date"]).date()
                except Exception:  # noqa: BLE001
                    selected_day = None
            event_click = cal_state.get("eventClick")
            if event_click and event_click.get("event", {}).get("start"):
                try:
                    selected_day = pd.Timestamp(event_click["event"]["start"]).date()
                except Exception:  # noqa: BLE001
                    pass

        st.markdown("---")
        if selected_day is None:
            st.caption("Click any date or event in the calendar to see its tasks.")
        else:
            day_ts = pd.Timestamp(selected_day)
            day_tasks = cal_source[cal_source["Due Date"].dt.normalize() == day_ts]
            if day_tasks.empty:
                st.info(f"No tasks due on {selected_day.strftime('%Y-%m-%d')}.")
            else:
                st.markdown(
                    f"**{len(day_tasks)} task(s) due on {selected_day.strftime('%A, %B %d, %Y')}**"
                )
                day_table = day_tasks[
                    ["Completed", "Task", "Project", "Priority", "Due Date", "File"]
                ].reset_index(drop=True)

                day_edited = st.data_editor(
                    day_table,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    disabled=[c for c in day_table.columns if c != "Completed"],
                    column_config={
                        "Completed": st.column_config.CheckboxColumn(
                            "Completed", help="Toggle to mark done/undone."
                        ),
                        "Task": st.column_config.TextColumn("Task", width="large"),
                        "Project": st.column_config.TextColumn("Project"),
                        "Priority": st.column_config.NumberColumn("Priority"),
                        "Due Date": st.column_config.DatetimeColumn(
                            "Due Date", format="YYYY-MM-DD HH:mm"
                        ),
                        "File": None,
                    },
                    key=f"task_calendar_day_editor_{selected_day.isoformat()}",
                )

                day_changes: list[tuple[str, bool]] = []
                for idx, row in day_edited.iterrows():
                    original = bool(day_table.loc[idx, "Completed"])
                    new_val = bool(row["Completed"])
                    if original != new_val:
                        day_changes.append(
                            (str(day_table.loc[idx, "File"]), new_val)
                        )

                if day_changes:
                    day_errors: list[str] = []
                    for file_name, new_val in day_changes:
                        try:
                            task_name = Path(file_name).stem
                            if new_val:
                                complete_a_task_tool.invoke({"task": task_name})
                            else:
                                uncomplete_a_task_tool.invoke({"task": task_name})
                        except Exception as exc:  # noqa: BLE001
                            logging.exception("Failed to update %s", file_name)
                            day_errors.append(f"{file_name}: {exc}")
                    if day_errors:
                        st.error(
                            "Some tasks could not be updated:\n"
                            + "\n".join(day_errors)
                        )
                    else:
                        st.success(f"Updated {len(day_changes)} task(s).")
                    load_tasks.clear()
                    st.rerun()

# --- Filters ---------------------------------------------------------------
st.subheader("Filters")
filter_cols = st.columns(4)

project_options = sorted(p for p in df["Project"].dropna().unique() if p)
priority_options = sorted(df["Priority"].dropna().unique().tolist())

with filter_cols[0]:
    selected_projects = st.multiselect(
        "Project", project_options, default=[], key="task_filter_projects"
    )
with filter_cols[1]:
    selected_priorities = st.multiselect(
        "Priority", priority_options, default=[], key="task_filter_priorities"
    )
with filter_cols[2]:
    status_choice = st.selectbox(
        "Status",
        ["All", "Incomplete only", "Completed only"],
        index=1,
        key="task_filter_status",
    )
with filter_cols[3]:
    search = st.text_input("Search task (contains)", "", key="task_filter_search")

filtered = df.copy()
if selected_projects:
    filtered = filtered[filtered["Project"].isin(selected_projects)]
if selected_priorities:
    filtered = filtered[filtered["Priority"].isin(selected_priorities)]
if status_choice == "Incomplete only":
    filtered = filtered[~filtered["Completed"]]
elif status_choice == "Completed only":
    filtered = filtered[filtered["Completed"]]
if search.strip():
    filtered = filtered[
        filtered["Task"].str.contains(search.strip(), case=False, na=False)
    ]

# --- Table -----------------------------------------------------------------
st.subheader("All Tasks")

if filtered.empty:
    st.info("No tasks match the current filters.")
else:
    st.caption(
        "Click a column header to sort. "
        "Toggle the **Completed** checkbox to mark a task done/undone."
    )

    table_df = filtered.reset_index(drop=True).copy()
    # Order columns for display.
    display_cols = [
        "Completed",
        "Task",
        "Project",
        "Priority",
        "Due Date",
        "Date Created",
        "Date Completed",
    ]
    display_df = table_df[display_cols + ["File"]]

    edited = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in display_df.columns if c != "Completed"],
        column_config={
            "Completed": st.column_config.CheckboxColumn(
                "Completed", help="Toggle to mark done/undone."
            ),
            "Task": st.column_config.TextColumn("Task", width="large"),
            "Project": st.column_config.TextColumn("Project"),
            "Priority": st.column_config.NumberColumn(
                "Priority", help="0 = highest"
            ),
            "Due Date": st.column_config.DatetimeColumn(
                "Due Date", format="YYYY-MM-DD"
            ),
            "Date Created": st.column_config.DatetimeColumn(
                "Date Created", format="YYYY-MM-DD"
            ),
            "Date Completed": st.column_config.DatetimeColumn(
                "Date Completed", format="YYYY-MM-DD HH:mm"
            ),
            "File": None,  # hide
        },
        key="task_table_editor",
    )

    # Detect rows whose Completed flag changed; persist them.
    changes: list[tuple[str, bool]] = []
    for idx, row in edited.iterrows():
        original = bool(table_df.loc[idx, "Completed"])
        new_val = bool(row["Completed"])
        if original != new_val:
            changes.append((str(table_df.loc[idx, "File"]), new_val))

    if changes:
        errors: list[str] = []
        for file_name, new_val in changes:
            try:
                task_name = Path(file_name).stem
                if new_val:
                    complete_a_task_tool.invoke({"task": task_name})
                else:
                    uncomplete_a_task_tool.invoke({"task": task_name})
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to update %s", file_name)
                errors.append(f"{file_name}: {exc}")
        if errors:
            st.error("Some tasks could not be updated:\n" + "\n".join(errors))
        else:
            st.success(f"Updated {len(changes)} task(s).")
        load_tasks.clear()
        st.rerun()

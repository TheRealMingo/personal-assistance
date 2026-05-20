"""Streamlit page for browsing and managing the Obsidian task list."""

from __future__ import annotations
from utils.mobile_css import inject_mobile_css
from utils.global_search_sidebar import render_global_search

import logging
import re
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt  # noqa: F401  (reserved for future charts)
import pandas as pd
import streamlit as st
from streamlit_calendar import calendar
from yaml import safe_load, dump, dump as yaml_dump

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
inject_mobile_css()
render_global_search()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
PROJECT_LINK_RE = re.compile(r"\[\[(.*?)\]\]")
RECURRENCE_OPTIONS = ["none", "daily", "weekly", "monthly"]


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


def _parse_recurrence(raw: Any) -> str:
    if raw is None:
        return "none"
    val = str(raw).strip().lower()
    return val if val in RECURRENCE_OPTIONS else "none"


def _parse_depends_on(raw: Any) -> str:
    """Return a comma-separated string of dependency task names."""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return ", ".join(str(x).strip() for x in raw if str(x).strip())
    return str(raw).strip()


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
        "Recurrence",
        "Depends On",
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
                "Recurrence": _parse_recurrence(norm.get("recurrence")),
                "Depends On": _parse_depends_on(norm.get("depends on")),
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
    """Rewrite a task note's frontmatter to update the Completed flag.

    When completing a recurring task a new instance is auto-created with the
    next due date so the recurrence chain continues.
    """
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

    # Auto-create next instance for recurring tasks when being marked complete.
    if completed:
        recurrence_key = next(
            (k for k in data if str(k).strip().lower() == "recurrence"), None
        )
        recurrence = (
            str(data[recurrence_key]).strip().lower() if recurrence_key else "none"
        )
        if recurrence in ("daily", "weekly", "monthly"):
            due_key = next(
                (k for k in data if str(k).strip().lower() == "due date"), None
            )
            raw_due = data.get(due_key) if due_key else None
            try:
                base_due = pd.Timestamp(raw_due) if raw_due else pd.Timestamp.now()
            except Exception:  # noqa: BLE001
                base_due = pd.Timestamp.now()
            if recurrence == "daily":
                next_due = base_due + timedelta(days=1)
            elif recurrence == "weekly":
                next_due = base_due + timedelta(weeks=1)
            else:  # monthly
                next_due = base_due + pd.DateOffset(months=1)
            next_due_str = next_due.strftime("%Y-%m-%dT%H:%M:%S")
            # Build new note data with reset completed state and updated due date.
            new_data = {k: v for k, v in data.items()}
            new_data[completed_key] = False
            new_data.pop(date_completed_key, None)
            if due_key:
                new_data[due_key] = next_due_str
            else:
                new_data["Due Date"] = next_due_str
            # Strip date-completed from new instance
            new_yaml2 = dump(new_data, default_flow_style=False, sort_keys=False, indent=2)
            # Derive new file name from stem + timestamp
            stem = Path(file_name).stem
            from uuid import uuid4
            new_file = folder / f"{stem}-{next_due.strftime('%Y%m%d')}.md"
            counter = 0
            while new_file.exists():
                counter += 1
                new_file = folder / f"{stem}-{next_due.strftime('%Y%m%d')}-{counter}.md"
            try:
                new_file.write_text(f"---\n{new_yaml2}---{body}", encoding="utf-8")
                logging.info("Created recurring task instance: %s", new_file.name)
            except OSError as exc:
                logging.error("Failed to create recurring task instance: %s", exc)


def _update_task_note(file_name: str, row: dict) -> None:
    """Rewrite a task note's frontmatter with updated field values from *row*."""
    folder = Path(config["obsidian_vault_task_list_path"])
    path = folder / file_name
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No frontmatter found in {file_name}")
    body = text[match.end():]
    data = safe_load(match.group(1)) or {}

    key_map = {str(k).strip().lower(): k for k in data.keys()}

    def _set(field: str, value: Any) -> None:
        target = key_map.get(field.lower(), field)
        data[target] = value

    _set("Task", str(row["Task"]).strip())
    project = str(row.get("Project", "")).strip()
    _set("Project", f"[[{project}]]" if project else "")
    due = row.get("Due Date")
    if pd.notna(due) and due is not None:
        due_str = pd.Timestamp(due).strftime("%Y-%m-%dT%H:%M:%S")
    else:
        due_str = None
    _set("Due Date", due_str)
    _set("priority", int(row["Priority"]))
    completed = bool(row.get("Completed", False))
    completed_key = key_map.get("completed", "Completed")
    date_completed_key = key_map.get("date completed", "Date Completed")
    data[completed_key] = completed
    if completed:
        existing_dc = data.get(date_completed_key)
        if not existing_dc:
            data[date_completed_key] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    else:
        data.pop(date_completed_key, None)
    # Recurrence
    recurrence = str(row.get("Recurrence", "none")).strip().lower()
    if recurrence in RECURRENCE_OPTIONS:
        _set("recurrence", recurrence)
    # Depends On
    depends_on_raw = str(row.get("Depends On", "")).strip()
    depends_on_list = [d.strip() for d in depends_on_raw.split(",") if d.strip()]
    _set("depends on", depends_on_list if depends_on_list else None)

    new_yaml = yaml_dump(data, default_flow_style=False, sort_keys=False, indent=2)
    path.write_text(f"---\n{new_yaml}---{body}", encoding="utf-8")


@st.dialog("Edit task")
def _edit_task_dialog(row: Any, file_name: str) -> None:
    """Modal dialog for editing all fields of a single task note."""
    from pathlib import Path as _Path
    st.caption(f"File: `{file_name}`")

    existing_projects = sorted(
        [p for p in load_tasks(config["obsidian_vault_task_list_path"])["Project"].unique() if p and str(p).strip()]
    )
    project_options = list(existing_projects) + ["Other"]

    current_task = str(row.get("Task", "")).strip()
    current_project = str(row.get("Project", "")).strip()
    current_priority = int(row["Priority"]) if pd.notna(row.get("Priority")) else 5
    raw_due = row.get("Due Date")
    current_due: date | None = pd.Timestamp(raw_due).date() if pd.notna(raw_due) else None
    current_completed = bool(row.get("Completed", False))
    current_recurrence = str(row.get("Recurrence", "none")).strip().lower()
    if current_recurrence not in RECURRENCE_OPTIONS:
        current_recurrence = "none"
    current_depends_on = str(row.get("Depends On", "")).strip()

    # All task names for dependency selection
    all_tasks_df = load_tasks(config["obsidian_vault_task_list_path"])
    all_task_names = sorted(
        t for t in all_tasks_df["Task"].tolist()
        if t and t != current_task
    )
    current_dep_list = [d.strip() for d in current_depends_on.split(",") if d.strip()]

    with st.form(f"edit_task_form_{file_name}"):
        new_task = st.text_input("Task", value=current_task)

        if current_project in existing_projects:
            proj_index: int | None = project_options.index(current_project)
        elif current_project:
            proj_index = project_options.index("Other")
        else:
            proj_index = None

        selected_project = st.selectbox(
            "Project (optional)",
            options=project_options,
            index=proj_index,
            placeholder="Select a project or choose Other",
        )
        new_project = ""
        if selected_project == "Other":
            new_project = st.text_input("New project name", value=current_project if current_project not in existing_projects else "")

        c1, c2 = st.columns(2)
        with c1:
            new_due = st.date_input("Due date (optional)", value=current_due)
        with c2:
            new_priority = st.number_input(
                "Priority (0 = highest, 5 = default)",
                min_value=0,
                max_value=5,
                value=current_priority,
                step=1,
            )
        c3, c4 = st.columns(2)
        with c3:
            new_recurrence = st.selectbox(
                "Recurrence",
                options=RECURRENCE_OPTIONS,
                index=RECURRENCE_OPTIONS.index(current_recurrence),
                help="Auto-create next instance when this task is completed.",
            )
        with c4:
            new_completed = st.checkbox("Completed", value=current_completed)
        new_depends_on = st.multiselect(
            "Depends on (tasks that must be completed first)",
            options=all_task_names,
            default=[d for d in current_dep_list if d in all_task_names],
        )

        btn_cols = st.columns(3)
        save_clicked = btn_cols[0].form_submit_button("💾 Save", type="primary", width="stretch")
        cancel_clicked = btn_cols[2].form_submit_button("Cancel", width="stretch")

    if cancel_clicked:
        st.session_state.pop("task_table_editor", None)
        st.session_state.pop(f"confirm_delete_task_{file_name}", None)
        st.rerun()

    if save_clicked:
        if not new_task.strip():
            st.error("Task description is required.")
            return
        if selected_project == "Other" and not new_project.strip():
            st.error("Please enter a project name when selecting 'Other'.")
            return
        project_val = (
            new_project.strip()
            if selected_project == "Other"
            else (selected_project or "")
        )
        updated: dict[str, Any] = {
            "Task": new_task.strip(),
            "Project": project_val,
            "Due Date": new_due,
            "Priority": int(new_priority),
            "Completed": new_completed,
            "Recurrence": new_recurrence,
            "Depends On": ", ".join(new_depends_on),
        }
        try:
            _update_task_note(file_name, updated)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to update task: {exc}")
            return
        load_tasks.clear()
        st.session_state.pop("task_table_editor", None)
        st.session_state.pop(f"confirm_delete_task_{file_name}", None)
        st.toast("Task updated.", icon="✅")
        st.rerun()

    # --- Delete section ---
    st.divider()
    if st.session_state.get(f"confirm_delete_task_{file_name}"):
        st.warning("⚠️ **Permanently delete this task note?** This cannot be undone.")
        d_cols = st.columns(2)
        if d_cols[0].button("Yes, delete", type="primary", width="stretch", key=f"task_del_yes_{file_name}"):
            try:
                (_Path(config["obsidian_vault_task_list_path"]) / file_name).unlink()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not delete file: {exc}")
                return
            load_tasks.clear()
            st.session_state.pop(f"confirm_delete_task_{file_name}", None)
            st.session_state.pop("task_table_editor", None)
            st.toast("Task deleted.", icon="🗑️")
            st.rerun()
        if d_cols[1].button("No, keep", width="stretch", key=f"task_del_no_{file_name}"):
            st.session_state.pop(f"confirm_delete_task_{file_name}", None)
            st.rerun()
    else:
        if st.button("🗑️ Delete task", key=f"task_del_btn_{file_name}"):
            st.session_state[f"confirm_delete_task_{file_name}"] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Page UI
# ---------------------------------------------------------------------------

st.title("✅ Task List")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")


# ---------------------------------------------------------------------------
# NL Task Parser Helper
# ---------------------------------------------------------------------------

def _parse_nl_task(text: str) -> dict[str, Any]:
    """Extract task name, due date, and priority from free-form text.

    Uses simple heuristics + dateutil fuzzy parsing when available.
    """
    cleaned = text.strip()

    # Priority detection
    _PRIORITY_PATTERNS = [
        (r"\b(critical|urgent|asap)\b", 0),
        (r"\b(high[\s\-]*priority|very\s+important)\b", 1),
        (r"\b(high|important)\b", 1),
        (r"\b(medium[\s\-]*priority|normal[\s\-]*priority)\b", 2),
        (r"\b(low[\s\-]*priority|low|whenever|eventually|someday)\b", 4),
    ]
    priority = 5
    for pat, prio in _PRIORITY_PATTERNS:
        if re.search(pat, cleaned, re.IGNORECASE):
            priority = prio
            cleaned = re.sub(r",?\s*" + pat + r"\s*,?", " ", cleaned, flags=re.IGNORECASE).strip()
            break

    # Strip common lead-in phrases
    cleaned = re.sub(
        r"^(?:remind me to|remember to|i need to|i should|todo\s*:?\s*|task\s*:?\s*)\s*",
        "", cleaned, flags=re.IGNORECASE,
    ).strip()

    # Try dateutil fuzzy date extraction
    due_date: datetime | None = None
    task_text = cleaned
    try:
        from dateutil import parser as _dtparser  # type: ignore
        default_dt = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        parsed_dt, tokens = _dtparser.parse(
            cleaned, fuzzy_with_tokens=True, default=default_dt
        )
        token_text = " ".join(t.strip(" ,;") for t in tokens if t.strip(" ,;"))
        if token_text.strip():
            task_text = token_text.strip()
        due_date = parsed_dt
    except Exception:  # noqa: BLE001
        pass

    task_text = re.sub(r"\s{2,}", " ", task_text).strip(" ,.;")
    if not task_text:
        task_text = cleaned

    # Capitalize first letter
    if task_text:
        task_text = task_text[0].upper() + task_text[1:]

    return {"task": task_text, "priority": priority, "due_date": due_date}

vault_path = config["obsidian_vault_task_list_path"]
df = load_tasks(vault_path)

col_refresh, col_info = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Refresh"):
        load_tasks.clear()
        st.rerun()
with col_info:
    st.caption(f"Loaded **{len(df)}** task notes from `{vault_path}`")

# --- NL Quick Add ----------------------------------------------------------
with st.expander("🤖 AI Quick Add (Natural Language)", expanded=False):
    st.caption(
        "Describe your task naturally — due date and priority are extracted automatically.\n\n"
        "Examples: *\"Call the dentist next Tuesday at 2pm, high priority\"* · "
        "*\"Remind me to buy groceries tomorrow\"* · "
        "*\"Submit report by Friday, urgent\"*"
    )
    nl_input = st.text_input(
        "Task description",
        key="nl_task_input",
        placeholder="e.g. Call the dentist next Tuesday at 2pm, high priority",
    )
    if st.button("Parse & Add", key="nl_task_submit", type="primary"):
        if not nl_input.strip():
            st.error("Please enter a task description.")
        else:
            parsed = _parse_nl_task(nl_input.strip())
            if not parsed["task"]:
                st.error("Could not extract a task name. Please try the regular form.")
            else:
                nl_payload: dict[str, Any] = {
                    "task": parsed["task"],
                    "priority": parsed["priority"],
                }
                if parsed["due_date"]:
                    nl_payload["due_date"] = parsed["due_date"].strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    )
                try:
                    response = add_task_tool.invoke(nl_payload)
                except Exception as exc:  # noqa: BLE001
                    logging.exception("NL task add failed")
                    st.error(f"Failed to add task: {exc}")
                else:
                    st.success(
                        f"Added: **{parsed['task']}** | "
                        f"Priority: {parsed['priority']} | "
                        f"Due: {parsed['due_date'].strftime('%A, %b %d') if parsed['due_date'] else 'none'}"
                    )
                    st.session_state.pop("nl_task_input", None)
                    load_tasks.clear()
                    st.rerun()

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
        new_recurrence = st.selectbox(
            "Recurrence",
            options=RECURRENCE_OPTIONS,
            index=0,
            key="task_add_recurrence",
            help="Auto-create next occurrence when task is completed.",
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
        all_task_names_add = sorted(
            t for t in df["Task"].tolist() if t and str(t).strip()
        )
        new_depends_on_add = st.multiselect(
            "Depends on (optional)",
            options=all_task_names_add,
            default=[],
            key="task_add_depends_on",
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
                # Write recurrence and depends_on directly to the created file.
                if new_recurrence != "none" or new_depends_on_add:
                    try:
                        _folder = Path(config["obsidian_vault_task_list_path"])
                        _fname = f"{new_task.strip().title()}.md"
                        _fpath = _folder / _fname
                        if _fpath.exists():
                            _text = _fpath.read_text(encoding="utf-8")
                            _match = FRONTMATTER_RE.match(_text)
                            if _match:
                                _body = _text[_match.end():]
                                _data = safe_load(_match.group(1)) or {}
                                if new_recurrence != "none":
                                    _data["recurrence"] = new_recurrence
                                if new_depends_on_add:
                                    _data["depends on"] = new_depends_on_add
                                _new_yaml = dump(_data, default_flow_style=False, sort_keys=False, indent=2)
                                _fpath.write_text(f"---\n{_new_yaml}---{_body}", encoding="utf-8")
                    except Exception as exc2:  # noqa: BLE001
                        logging.warning("Could not write recurrence/deps to task: %s", exc2)
                st.success("Task added!")
                st.markdown(response)
                # Clear the inputs by removing their session state keys.
                for k in (
                    "task_add_task",
                    "task_add_project_select",
                    "task_add_new_project",
                    "task_add_due",
                    "task_add_priority",
                    "task_add_recurrence",
                    "task_add_depends_on",
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
                    width='stretch',
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

# --- Weekly Review ---------------------------------------------------------
with st.expander("📋 Weekly Review", expanded=False):
    _today = date.today()
    _week_start = _today - timedelta(days=_today.weekday())  # Monday
    _week_end = _week_start + timedelta(days=6)              # Sunday

    _week_start_ts = pd.Timestamp(_week_start)
    _week_end_ts = pd.Timestamp(_week_end)
    _today_ts = pd.Timestamp(_today)
    _completed_week = df[
        df["Completed"]
        & df["Date Completed"].notna()
        & (df["Date Completed"].dt.normalize() >= _week_start_ts)
        & (df["Date Completed"].dt.normalize() <= _today_ts)
    ]
    _overdue = df[
        ~df["Completed"]
        & df["Due Date"].notna()
        & (df["Due Date"].dt.normalize() < _today_ts)
    ]
    _due_this_week = df[
        ~df["Completed"]
        & df["Due Date"].notna()
        & (df["Due Date"].dt.normalize() >= _today_ts)
        & (df["Due Date"].dt.normalize() <= _week_end_ts)
    ]
    _total_incomplete = int((~df["Completed"]).sum())

    _wr_cols = st.columns(4)
    _wr_cols[0].metric("✅ Completed This Week", len(_completed_week))
    _wr_cols[1].metric("⚠️ Overdue", len(_overdue))
    _wr_cols[2].metric("📅 Due This Week", len(_due_this_week))
    _wr_cols[3].metric("📝 Total Open", _total_incomplete)

    st.markdown(f"**Week: {_week_start.strftime('%b %d')} – {_week_end.strftime('%b %d, %Y')}**")

    if not _completed_week.empty:
        st.markdown("### ✅ Completed This Week")
        st.dataframe(
            _completed_week[["Task", "Project", "Date Completed"]].reset_index(drop=True),
            hide_index=True,
            use_container_width=True,
        )
    if not _overdue.empty:
        st.markdown("### ⚠️ Overdue Tasks")
        st.dataframe(
            _overdue[["Task", "Project", "Priority", "Due Date"]].reset_index(drop=True),
            hide_index=True,
            use_container_width=True,
        )
    if not _due_this_week.empty:
        st.markdown("### 📅 Due This Week")
        st.dataframe(
            _due_this_week[["Task", "Project", "Priority", "Due Date"]].reset_index(drop=True),
            hide_index=True,
            use_container_width=True,
        )
    if _completed_week.empty and _overdue.empty and _due_this_week.empty:
        st.info("Nothing to review — you're all caught up! 🎉")

# --- Pomodoro Timer --------------------------------------------------------
with st.expander(
    "⏱️ Pomodoro Timer"
    + (" 🔴 Running" if st.session_state.get("pomo_active") else ""),
    expanded=st.session_state.get("pomo_active", False),
):
    _POMO_WORK = 25 * 60
    _POMO_SHORT = 5 * 60
    _POMO_LONG = 15 * 60

    # Initialize state
    for _k, _v in [
        ("pomo_active", False),
        ("pomo_start", None),
        ("pomo_duration", _POMO_WORK),
        ("pomo_sessions", 0),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    _pc1, _pc2 = st.columns(2)
    with _pc1:
        _incomplete_tasks = ["(no task)"] + df[~df["Completed"]]["Task"].tolist()
        _pomo_task = st.selectbox(
            "Linked task", _incomplete_tasks, key="pomo_task_select",
            disabled=bool(st.session_state.pomo_active),
        )
    with _pc2:
        _mode_map = {
            "Work (25 min)": _POMO_WORK,
            "Short Break (5 min)": _POMO_SHORT,
            "Long Break (15 min)": _POMO_LONG,
        }
        _pomo_mode = st.selectbox(
            "Mode", list(_mode_map.keys()), key="pomo_mode_select",
            disabled=bool(st.session_state.pomo_active),
        )

    st.metric("🍅 Completed Sessions", st.session_state.pomo_sessions)

    if st.session_state.pomo_active and st.session_state.pomo_start is not None:
        _elapsed = int(_time.time() - st.session_state.pomo_start)
        _remaining = max(0, st.session_state.pomo_duration - _elapsed)
        _mins, _secs = divmod(_remaining, 60)
        st.metric(
            "⏳ Time Remaining",
            f"{_mins:02d}:{_secs:02d}",
            delta=f"Task: {_pomo_task}" if _pomo_task != '(no task)' else None,
        )
        if _remaining == 0:
            st.success("🎉 Timer complete! Take a break.")
            st.session_state.pomo_active = False
            st.session_state.pomo_sessions += 1
        _btn1, _btn2 = st.columns(2)
        if _btn1.button("⏸️ Stop", key="pomo_stop"):
            st.session_state.pomo_active = False
            st.rerun()
        if _btn2.button("🔄 Reset", key="pomo_reset"):
            st.session_state.pomo_active = False
            st.session_state.pomo_start = None
            st.rerun()
        # Tick the timer every second
        _time.sleep(1)
        st.rerun()
    else:
        _sel_duration = _mode_map[_pomo_mode]
        _dm, _ds = divmod(_sel_duration, 60)
        st.metric("⏱️ Duration", f"{_dm:02d}:{_ds:02d}")
        if st.button("▶️ Start", key="pomo_start_btn", type="primary"):
            st.session_state.pomo_active = True
            st.session_state.pomo_start = _time.time()
            st.session_state.pomo_duration = _sel_duration
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
        "Click any row to open an edit modal. "
        "Toggle the **Completed** checkbox in the modal to mark a task done/undone."
    )

    table_df = filtered.reset_index(drop=True).copy()

    # Add dependency warning column
    _completed_set = set(df[df["Completed"]]["Task"].tolist())

    def _deps_met(row: Any) -> str:
        deps_raw = str(row.get("Depends On", "")).strip()
        if not deps_raw:
            return ""
        deps = [d.strip() for d in deps_raw.split(",") if d.strip()]
        unmet = [d for d in deps if d not in _completed_set]
        return "⚠️ " + ", ".join(unmet) if unmet else "✅"

    table_df["Deps"] = table_df.apply(_deps_met, axis=1)

    display_cols = [
        "Completed",
        "Task",
        "Project",
        "Priority",
        "Due Date",
        "Recurrence",
        "Deps",
        "Date Created",
        "Date Completed",
    ]
    display_df = table_df[display_cols + ["File"]].reset_index(drop=True)

    selection_state = st.dataframe(
        display_df.drop(columns=["File"]),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Completed": st.column_config.CheckboxColumn("Completed"),
            "Task": st.column_config.TextColumn("Task", width="large"),
            "Project": st.column_config.TextColumn("Project"),
            "Priority": st.column_config.NumberColumn("Priority", help="0 = highest"),
            "Due Date": st.column_config.DatetimeColumn("Due Date", format="YYYY-MM-DD"),
            "Recurrence": st.column_config.TextColumn("🔁", help="Recurrence schedule"),
            "Deps": st.column_config.TextColumn("Deps", help="⚠️ = has unmet dependencies"),
            "Date Created": st.column_config.DatetimeColumn("Date Created", format="YYYY-MM-DD"),
            "Date Completed": st.column_config.DatetimeColumn("Date Completed", format="YYYY-MM-DD HH:mm"),
        },
        key="task_table_editor",
    )

    selected_rows = (
        getattr(getattr(selection_state, "selection", None), "rows", None)
        or (selection_state.get("selection", {}).get("rows") if isinstance(selection_state, dict) else None)
        or []
    )
    if selected_rows:
        sel_idx = int(selected_rows[0])
        sel_row = display_df.iloc[sel_idx]
        _edit_task_dialog(sel_row, str(sel_row["File"]))

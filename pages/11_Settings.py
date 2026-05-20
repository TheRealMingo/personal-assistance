"""Settings page: configure notifications and reminder times."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from yaml import safe_load as yaml_load

from config.config import config
from config.runtime_settings import (
    DEFAULT_SETTINGS,
    load_settings,
    save_settings,
)
from tools.api_call_tracker import (
    API_DISPLAY_NAMES,
    get_daily_counts,
    get_monthly_counts,
)
from utils.mobile_css import inject_mobile_css
from utils.notification_log import get_notification_log
from utils.global_search_sidebar import render_global_search

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Paths to the legacy per-tool CTA counter files.
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CTA_BUS_COUNT_PATH = _DATA_DIR / "cta_call_count.json"
_CTA_TRAIN_COUNT_PATH = _DATA_DIR / "cta_train_call_count.json"

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
inject_mobile_css()
render_global_search()
st.title("⚙️ Settings")

if st.button("Back to Assistant"):
    st.switch_page("0_Personal_Assistant.py")


def _parse_time(value: str) -> time:
    try:
        hh, mm = value.split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        hh, mm = DEFAULT_SETTINGS["morning_routine_time"].split(":")
        return time(int(hh), int(mm))


# ---------------------------------------------------------------------------
# Helper functions (defined before tabs so all tabs can use them)
# ---------------------------------------------------------------------------

_now_utc = datetime.now(timezone.utc)
_today_str = _now_utc.strftime("%Y-%m-%d")
_month_label = _now_utc.strftime("%B %Y")


def _cta_legacy_today(path: Path, api_key: str) -> int:
    """Read today's count from a legacy CTA single-day counter file."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("date") == _today_str:
            return int(data.get("count", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return 0


def _build_counts_df(
    counts: dict[str, int],
    cta_bus_override: int | None = None,
    cta_train_override: int | None = None,
) -> pd.DataFrame:
    """Convert a {api_name: count} dict into a display DataFrame."""
    rows = []
    all_keys = set(counts.keys()) | set(API_DISPLAY_NAMES.keys())
    for key in sorted(all_keys):
        display = API_DISPLAY_NAMES.get(key, key.replace("_", " ").title())
        if key == "cta_bus" and cta_bus_override is not None:
            count = cta_bus_override
        elif key == "cta_train" and cta_train_override is not None:
            count = cta_train_override
        else:
            count = counts.get(key, 0)
        rows.append({"API": display, "Calls": count})
    return pd.DataFrame(rows)


_VAULT_SCAN_LABELS: dict[str, str] = {
    "obsidian_vault_exercise_path": "Exercise",
    "obsidian_vault_task_list_path": "Tasks",
    "obsidian_vault_shopping_list_path": "Shopping",
    "obsidian_vault_daily_routine_path": "Routine",
    "obsidian_vault_weight_path": "Weight",
    "obsidian_vault_book_path": "Books",
}


@st.cache_data(ttl=60, show_spinner=False)
def _scan_vault_errors() -> dict[str, list[str]]:
    """Return a dict of label -> list of file paths with YAML parse errors."""
    errors: dict[str, list[str]] = {}
    for cfg_key, label in _VAULT_SCAN_LABELS.items():
        vault_path = Path(config.get(cfg_key, "."))
        if not vault_path.is_dir():
            continue
        bad_files: list[str] = []
        for md_file in sorted(vault_path.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                bad_files.append(f"{md_file.name} (unreadable)")
                continue
            if not text.startswith("---"):
                continue  # No frontmatter — skip, not an error.
            parts = text.split("---", 2)
            if len(parts) < 3:
                bad_files.append(f"{md_file.name} (incomplete frontmatter)")
                continue
            try:
                yaml_load(parts[1])
            except Exception as exc:  # noqa: BLE001
                bad_files.append(f"{md_file.name} ({exc})")
        if bad_files:
            errors[label] = bad_files
    return errors


settings = load_settings()

# ---------------------------------------------------------------------------
# Top-level Settings tabs
# ---------------------------------------------------------------------------
(
    tab_general,
    tab_api,
    tab_notifications,
    tab_validation,
    tab_logs,
) = st.tabs(["⚙️ General", "📊 API Usage", "🔔 Notifications", "🗂️ Data Validation", "📋 App Logs"])

# ── Tab: General ──────────────────────────────────────────────────────────
with tab_general:
    with st.form("settings_form"):
        st.subheader("Browser notifications")
        browser_enabled = st.checkbox(
            "Enable browser notifications",
            value=bool(settings.get("browser_notifications_enabled", True)),
            help="When enabled, the app will request browser notification "
            "permission and pop up reminders at the configured routine times "
            "while the app is open.",
        )

        st.divider()
        st.subheader("Email reminders")
        email_enabled = st.checkbox(
            "Enable email reminders",
            value=bool(settings.get("email_notifications_enabled", False)),
        )
        notification_email = st.text_input(
            "Notification email address",
            value=settings.get("notification_email", ""),
            placeholder="you@example.com",
        )

        st.divider()
        st.subheader("Routine reminder times")
        morning_time = st.time_input(
            "Morning routine reminder time",
            value=_parse_time(settings.get("morning_routine_time", "07:00")),
            step=300,
        )
        evening_time = st.time_input(
            "Evening routine reminder time",
            value=_parse_time(settings.get("evening_routine_time", "21:00")),
            step=300,
        )

        st.divider()
        st.subheader("Task reminders")
        lead_minutes = st.number_input(
            "Remind me this many minutes before a task is due",
            min_value=0,
            max_value=24 * 60,
            value=int(settings.get("task_reminder_lead_minutes", 60)),
            step=5,
        )

        st.divider()
        st.subheader("CTA Tracker notifications")
        cta_notify_minutes = st.number_input(
            "Notify when bus/train arrives within (minutes)",
            min_value=1,
            max_value=30,
            value=int(settings.get("cta_arrival_notify_minutes", 5)),
            step=1,
            help="When auto-refresh is on, a browser notification fires for any arrival within this many minutes.",
        )

        st.divider()
        st.subheader("Global Search")
        global_search_enabled = st.checkbox(
            "Enable Global Search in sidebar",
            value=bool(settings.get("global_search_enabled", True)),
            help="When enabled, a 🔍 Global Search panel appears in the sidebar on every page.",
        )

        submitted = st.form_submit_button("Save settings", type="primary")
        if submitted:
            if email_enabled and "@" not in (notification_email or ""):
                st.error("Please enter a valid email address to enable email reminders.")
            else:
                new_settings = {
                    "browser_notifications_enabled": bool(browser_enabled),
                    "email_notifications_enabled": bool(email_enabled),
                    "notification_email": notification_email.strip(),
                    "morning_routine_time": morning_time.strftime("%H:%M"),
                    "evening_routine_time": evening_time.strftime("%H:%M"),
                    "task_reminder_lead_minutes": int(lead_minutes),
                    "cta_arrival_notify_minutes": int(cta_notify_minutes),
                    "global_search_enabled": bool(global_search_enabled),
                }
                save_settings(new_settings)
                logger.info(f"Settings updated: {new_settings}")
                st.success("Settings saved.")

    st.caption(
        "Browser notifications fire only while the assistant is open in your browser. "
        "Email reminders require the cron agent to be scheduled (see docs)."
    )

# ── Tab: API Usage ────────────────────────────────────────────────────────
with tab_api:
    tab_daily, tab_monthly = st.tabs([f"📅 Today ({_today_str})", f"🗓️ This Month ({_month_label})"])

    with tab_daily:
        if st.button("🔄 Refresh", key="api_refresh_daily"):
            st.rerun()

        daily_counts = get_daily_counts(_today_str)
        cta_bus_today = _cta_legacy_today(_CTA_BUS_COUNT_PATH, "cta_bus") or daily_counts.get("cta_bus", 0)
        cta_train_today = _cta_legacy_today(_CTA_TRAIN_COUNT_PATH, "cta_train") or daily_counts.get("cta_train", 0)

        df_daily = _build_counts_df(daily_counts, cta_bus_today, cta_train_today)
        total_today = df_daily["Calls"].sum()
        st.metric("Total API calls today", total_today)
        st.dataframe(
            df_daily,
            width="stretch",
            hide_index=True,
            column_config={
                "API": st.column_config.TextColumn("API"),
                "Calls": st.column_config.NumberColumn("Calls Today", format="%d"),
            },
        )

    with tab_monthly:
        if st.button("🔄 Refresh", key="api_refresh_monthly"):
            st.rerun()

        monthly_counts = get_monthly_counts(_now_utc.year, _now_utc.month)
        df_monthly = _build_counts_df(monthly_counts)
        total_month = df_monthly["Calls"].sum()
        st.metric(f"Total API calls in {_month_label}", total_month)
        st.dataframe(
            df_monthly,
            width="stretch",
            hide_index=True,
            column_config={
                "API": st.column_config.TextColumn("API"),
                "Calls": st.column_config.NumberColumn(f"Calls in {_month_label}", format="%d"),
            },
        )
        st.caption(
            "Monthly totals are based on the centralized tracker (`data/api_call_counts.json`). "
            "CTA bus/train monthly history accumulates from the first time the app is used "
            "after this update."
        )

# ── Tab: Notifications ────────────────────────────────────────────────────
with tab_notifications:
    st.subheader("🔔 Notification Delivery Status")
    notif_log = get_notification_log()  # newest first
    if notif_log:
        if st.button("🔄 Refresh", key="notif_refresh"):
            st.rerun()
        _status_icons = {"sent": "✅", "failed": "❌", "skipped": "⏭️"}
        notif_rows = [
            {
                "Time": entry.get("timestamp", ""),
                "Channel": entry.get("channel", ""),
                "Subject": entry.get("subject", ""),
                "Status": f"{_status_icons.get(entry.get('status', ''), '')} {entry.get('status', '')}",
                "Detail": entry.get("detail", ""),
            }
            for entry in notif_log[:50]
        ]
        st.dataframe(
            pd.DataFrame(notif_rows),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No notification events recorded yet. Notifications will appear here after the first delivery attempt.")

# ── Tab: Data Validation ──────────────────────────────────────────────────
with tab_validation:
    st.subheader("🗂️ Data Validation")
    st.caption("Scans all vault directories for notes with YAML frontmatter parse errors.")

    if st.button("🔍 Scan for YAML errors", key="vault_scan_btn"):
        _scan_vault_errors.clear()

    with st.spinner("Scanning vault…"):
        vault_errors = _scan_vault_errors()

    if vault_errors:
        total_errors = sum(len(v) for v in vault_errors.values())
        st.warning(f"Found **{total_errors}** note(s) with YAML parse errors:")
        for label, bad_files in vault_errors.items():
            with st.expander(f"{label} — {len(bad_files)} error(s)"):
                for fname in bad_files:
                    st.code(fname)
    else:
        st.success("All vault notes parsed successfully — no YAML errors found.")

# ── Tab: App Logs ─────────────────────────────────────────────────────────
with tab_logs:
    st.subheader("📋 App Logs")

    _LOG_FILE = Path(__file__).resolve().parent.parent / "personal_assistant_tool.log"
    _LOG_LINE_OPTIONS = [50, 100, 200, 500]

    col_lines, col_refresh = st.columns([3, 1])
    with col_lines:
        log_lines_n = st.selectbox(
            "Lines to show",
            options=_LOG_LINE_OPTIONS,
            index=1,
            key="log_lines_select",
            label_visibility="collapsed",
        )
    with col_refresh:
        if st.button("🔄 Refresh", key="log_refresh_btn"):
            st.rerun()

    if _LOG_FILE.exists():
        try:
            all_lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = all_lines[-log_lines_n:]
            st.code("\n".join(tail), language="text")
            st.caption(f"Showing last {len(tail)} of {len(all_lines)} lines from `{_LOG_FILE.name}`")
        except OSError as exc:
            st.error(f"Could not read log file: {exc}")
    else:
        st.info(f"`{_LOG_FILE.name}` not found — no logs written yet.")


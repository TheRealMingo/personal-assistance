"""Runtime-mutable settings persisted to ``data/settings.json``.

These settings are user-editable from the Settings page and consumed by the
cron agent (for email reminders) and the Streamlit UI (for browser notifications).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "browser_notifications_enabled": True,
    "email_notifications_enabled": False,
    "notification_email": "",
    "morning_routine_time": "07:00",
    "evening_routine_time": "21:00",
    "task_reminder_lead_minutes": 60,
    "cta_arrival_notify_minutes": 5,
    "global_search_enabled": True,
}


def load_settings() -> dict[str, Any]:
    """Load settings, merging with defaults for any missing keys."""
    data: dict[str, Any] = {}
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse settings file {_SETTINGS_PATH}: {e}")
            data = {}
        except OSError as e:
            logger.error(f"Failed to read settings file {_SETTINGS_PATH}: {e}")
            data = {}
    else:
        logger.debug("Settings file not found; using defaults.")
    merged = {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}
    logger.debug(f"Loaded settings: {merged}")
    return merged


def save_settings(data: dict[str, Any]) -> None:
    """Persist settings to ``data/settings.json``."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULT_SETTINGS, **data}
    try:
        _SETTINGS_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        logger.info(f"Settings saved to {_SETTINGS_PATH}")
    except OSError as e:
        logger.error(f"Failed to save settings to {_SETTINGS_PATH}: {e}")
        raise


def get_setting(key: str, default: Any = None) -> Any:
    value = load_settings().get(key, default)
    if value is default:
        logger.debug(f"Setting '{key}' not found; using default: {default}")
    return value

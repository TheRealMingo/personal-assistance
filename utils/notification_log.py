"""Notification delivery log utilities.

Tracks notifications fired by the app (email, browser triggers, etc.) so the
Settings page can display a recent delivery-status panel.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "notification_log.json"
_MAX_ENTRIES = 100

logger = logging.getLogger(__name__)

NotifStatus = Literal["sent", "failed", "skipped"]


def log_notification(
    channel: str,
    subject: str,
    status: NotifStatus,
    detail: str = "",
) -> None:
    """Append a notification delivery event to the log.

    Args:
        channel: Delivery channel, e.g. ``"email"`` or ``"browser"``.
        subject: Short description / subject line of the notification.
        status:  ``"sent"``, ``"failed"``, or ``"skipped"``.
        detail:  Optional extra context (e.g. error message, recipient).
    """
    entries = _load_entries()
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel": channel,
        "subject": subject,
        "status": status,
        "detail": detail,
    }
    entries.append(entry)
    # Keep only the most recent entries.
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOG_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write notification log: %s", exc)


def get_notification_log() -> list[dict]:
    """Return all notification log entries, newest first."""
    return list(reversed(_load_entries()))


def _load_entries() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    try:
        data = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read notification log: %s", exc)
        return []

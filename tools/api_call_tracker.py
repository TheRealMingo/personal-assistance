"""Centralized API call tracking utility.

Stores per-API, per-day call counts in data/api_call_counts.json.
Structure:
    {
        "google_weather": {"2026-05-19": 5, "2026-05-18": 3},
        "google_maps":    {"2026-05-19": 10},
        ...
    }

Retains the last MAX_DAYS days of history per API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COUNTS_PATH = DATA_DIR / "api_call_counts.json"
MAX_DAYS = 31

# Human-readable display names used by the Settings page.
API_DISPLAY_NAMES: dict[str, str] = {
    "google_weather": "Google Weather API",
    "google_maps": "Google Maps API",
    "wolfram_alpha": "Wolfram Alpha API",
    "tavily": "Tavily Search API",
    "brave_search": "Brave Search API",
    "cta_bus": "CTA Bus Tracker API",
    "cta_train": "CTA Train Tracker API",
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict[str, dict[str, int]]:
    if not COUNTS_PATH.exists():
        return {}
    try:
        data = json.loads(COUNTS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, dict[str, int]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        COUNTS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist API call counts: %s", exc)


def record_api_call(api_name: str) -> int:
    """Increment today's call count for *api_name* and return the new total."""
    today = _today()
    data = _load()
    api_data: dict[str, int] = data.get(api_name) or {}
    if not isinstance(api_data, dict):
        api_data = {}
    api_data[today] = int(api_data.get(today, 0)) + 1

    # Prune old dates to stay within MAX_DAYS.
    if len(api_data) > MAX_DAYS:
        for old in sorted(api_data.keys())[: len(api_data) - MAX_DAYS]:
            del api_data[old]

    data[api_name] = api_data
    _save(data)
    return api_data[today]


def get_all_counts() -> dict[str, dict[str, int]]:
    """Return the full counts dict: {api_name: {date_str: count}}."""
    return _load()


def get_daily_counts(date_str: str | None = None) -> dict[str, int]:
    """Return {api_name: count} for the given date (default: today)."""
    target = date_str or _today()
    data = _load()
    return {api: dates.get(target, 0) for api, dates in data.items()}


def get_monthly_counts(year: int | None = None, month: int | None = None) -> dict[str, int]:
    """Return {api_name: total_calls} for the given month (default: current month)."""
    now = datetime.now(timezone.utc)
    y = year or now.year
    m = month or now.month
    prefix = f"{y:04d}-{m:02d}-"
    data = _load()
    result: dict[str, int] = {}
    for api, dates in data.items():
        result[api] = sum(v for k, v in dates.items() if k.startswith(prefix))
    return result

"""Daily Routine Tracker tools (Obsidian-backed)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, date as date_cls
from pathlib import Path
from typing import Any

from langchain.tools import tool
from pytz import timezone
from yaml import dump, safe_load

from config.config import config
from config.daily_routine import (
    ALL_ITEMS,
    MORNING_ITEMS,
    NIGHT_ITEMS,
    empty_routine_payload,
    normalize_item,
    period_of,
)

logging.basicConfig(
    filename="personal_assistant_tool.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)


# ---------- helpers (not exposed as tools) ----------

def _vault_dir() -> Path:
    return Path(config["obsidian_vault_daily_routine_path"])


def _now_local() -> datetime:
    return datetime.now(timezone(config["timezone"]))


def _note_path(d: date_cls) -> Path:
    return _vault_dir() / f"{d.isoformat()}.md"


def _read_note(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    return safe_load(match.group(1)) or {}


def _write_note(path: Path, payload: dict[str, Any]) -> None:
    body = dump(payload, default_flow_style=False, sort_keys=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{body}---\n", encoding="utf-8")


def _ensure_all_items(payload: dict[str, Any]) -> dict[str, Any]:
    """Backfill any missing item keys as False, preserving canonical order."""
    fixed: dict[str, Any] = {
        "Date": payload.get("Date"),
        "tags": payload.get("tags", ["#daily-routine", "#routine", "#personal-assistant"]),
    }
    for item in ALL_ITEMS:
        fixed[item] = bool(payload.get(item, False))
    return fixed


def _load_or_create(d: date_cls) -> tuple[Path, dict[str, Any]]:
    path = _note_path(d)
    payload = _read_note(path)
    if payload is None:
        if d == _now_local().date():
            iso = _now_local().strftime("%Y-%m-%dT%H:%M")
        else:
            iso = f"{d.isoformat()}T00:00"
        payload = empty_routine_payload(iso)
        _write_note(path, payload)
        return path, payload
    return path, _ensure_all_items(payload)


def _percentages(payload: dict[str, Any]) -> dict[str, float]:
    morning_done = sum(1 for k in MORNING_ITEMS if payload.get(k))
    night_done = sum(1 for k in NIGHT_ITEMS if payload.get(k))
    return {
        "morning_pct": round(morning_done / len(MORNING_ITEMS) * 100, 2),
        "night_pct": round(night_done / len(NIGHT_ITEMS) * 100, 2),
    }


def _format_status(d: date_cls, payload: dict[str, Any]) -> str:
    pct = _percentages(payload)
    lines = [
        f"Daily Routine for **{d.isoformat()}**",
        f"- Morning: **{pct['morning_pct']}%**",
        f"- Night: **{pct['night_pct']}%**",
        "",
        "**Morning items**",
    ]
    lines += [f"- [{'x' if payload.get(i) else ' '}] {i}" for i in MORNING_ITEMS]
    lines += ["", "**Night items**"]
    lines += [f"- [{'x' if payload.get(i) else ' '}] {i}" for i in NIGHT_ITEMS]
    return "  \n".join(lines)


# ---------- LangChain tools ----------

@tool
def get_todays_routine_status_tool() -> str:
    """Return today's morning and night routine completion status and percentages."""
    today = _now_local().date()
    _, payload = _load_or_create(today)
    return _format_status(today, payload)


@tool
def get_routine_status_for_date_tool(date_iso: str) -> str:
    """Return the routine status for a specific date.

    Args:
        date_iso: Date in YYYY-MM-DD format.
    """
    d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    path = _note_path(d)
    payload = _read_note(path)
    if payload is None:
        return f"No routine note exists for {date_iso}."
    return _format_status(d, _ensure_all_items(payload))


def _set_item(item_name: str, value: bool) -> str:
    canonical = normalize_item(item_name)
    if canonical is None:
        return (
            f"'{item_name}' is not a recognized routine item. Valid items: "
            f"{', '.join(ALL_ITEMS)}"
        )
    today = _now_local().date()
    path, payload = _load_or_create(today)
    payload[canonical] = value
    _write_note(path, payload)
    pct = _percentages(payload)
    period = period_of(canonical)
    state = "complete" if value else "incomplete"
    return (
        f"Marked **{canonical}** as {state} for {today.isoformat()}. "
        f"{period.title()} routine is now {pct[period + '_pct']}%."
    )


@tool
def complete_routine_item_tool(item_name: str) -> str:
    """Mark a single routine item as complete for today.

    Args:
        item_name: Name of the routine item (e.g. 'Drink Water'). Case insensitive.
    """
    return _set_item(item_name, True)


@tool
def uncomplete_routine_item_tool(item_name: str) -> str:
    """Revert a single routine item back to incomplete for today.

    Args:
        item_name: Name of the routine item.
    """
    return _set_item(item_name, False)


@tool
def complete_morning_routine_tool() -> str:
    """Mark every morning-routine item as complete for today."""
    today = _now_local().date()
    path, payload = _load_or_create(today)
    for item in MORNING_ITEMS:
        payload[item] = True
    _write_note(path, payload)
    return f"All morning routine items marked complete for {today.isoformat()} (100%)."


@tool
def complete_night_routine_tool() -> str:
    """Mark every night-routine item as complete for today."""
    today = _now_local().date()
    path, payload = _load_or_create(today)
    for item in NIGHT_ITEMS:
        payload[item] = True
    _write_note(path, payload)
    return f"All night routine items marked complete for {today.isoformat()} (100%)."


@tool
def list_incomplete_routine_items_tool(period: str = "all") -> str:
    """List today's incomplete routine items.

    Args:
        period: 'morning', 'night', or 'all' (default).
    """
    period = period.strip().lower()
    if period not in {"morning", "night", "all"}:
        return "period must be 'morning', 'night', or 'all'."
    today = _now_local().date()
    _, payload = _load_or_create(today)
    items = (
        MORNING_ITEMS if period == "morning"
        else NIGHT_ITEMS if period == "night"
        else ALL_ITEMS
    )
    pending = [i for i in items if not payload.get(i)]
    if not pending:
        return f"All {period} routine items are already complete for today."
    return (
        f"Incomplete {period} items for {today.isoformat()}:\n- "
        + "\n- ".join(pending)
    )

"""Shopping list tools backed by Obsidian markdown notes.

Each shopping list item is a single markdown file with YAML frontmatter using
the format below (per spec):

    ---
    item:
    description:
    url:
    bought:
    price:
    category:
    Date Created:
    tags:
      - shopping-list
      - shopping-list-item
    ---

The note's filename is derived from the item name so it can be looked up later.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.tools import tool
from pytz import timezone
from yaml import dump, safe_load

from config.config import config

logging.basicConfig(
    filename="personal_assistant_tool.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

SHOPPING_TAGS = ["shopping-list", "shopping-list-item"]
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_\- ]+")


def _vault_dir() -> Path:
    return Path(config["obsidian_vault_shopping_list_path"])


def _slugify(name: str) -> str:
    name = _FILENAME_SAFE_RE.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name or f"item-{uuid4().hex[:8]}"


def _now_str() -> str:
    tz = timezone(config["timezone"])
    return datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S")


def _build_item(
    item: str,
    description: str | None,
    url: str | None,
    bought: bool,
    price: float | None,
    category: str | None,
    date_created: str | None = None,
) -> dict[str, Any]:
    return {
        "item": item.strip(),
        "description": (description or "").strip(),
        "url": (url or "").strip(),
        "bought": bool(bought),
        "price": float(price) if price not in (None, "") else None,
        "category": (category or "").strip(),
        "Date Created": date_created or _now_str(),
        "tags": SHOPPING_TAGS,
    }


def _write_note(data: dict[str, Any], path: Path) -> None:
    yaml_text = dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml_text}---\n", encoding="utf-8")


def _read_note(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logging.warning("Could not read shopping note %s: %s", path, exc)
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = safe_load(parts[1]) or {}
    except Exception as exc:  # noqa: BLE001
        logging.warning("YAML parse error in %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    tags = data.get("tags") or []
    if not any(t in tags for t in SHOPPING_TAGS):
        return None
    data["_file"] = str(path)
    return data


def _find_item_file(item_name: str) -> Path | None:
    """Locate an item's note file by exact item name (case-insensitive)."""
    folder = _vault_dir()
    if not folder.exists():
        return None
    target = item_name.strip().lower()
    # Fast path: exact filename match.
    candidate = folder / f"{_slugify(item_name)}.md"
    if candidate.exists():
        return candidate
    for path in folder.glob("*.md"):
        data = _read_note(path)
        if data and str(data.get("item", "")).strip().lower() == target:
            return path
    return None


@tool
def create_shopping_list_item_tool(
    item: str,
    description: str = "",
    url: str = "",
    price: float | None = None,
    category: str = "",
) -> str:
    """Create a new shopping list item in the Obsidian vault.

    Args:
        item: Name of the item to add (required).
        description: Optional description / notes about the item.
        url: Optional URL where the item can be purchased.
        price: Optional price as a number.
        category: Optional category (e.g. Groceries, Electronics).

    Returns:
        Confirmation string describing what was added.
    """
    item = (item or "").strip()
    if not item:
        return "❌ Cannot create shopping list item: 'item' is required."

    existing = _find_item_file(item)
    if existing is not None:
        return f"⚠️ Shopping list item '{item}' already exists at {existing}."

    data = _build_item(item, description, url, False, price, category)
    path = _vault_dir() / f"{_slugify(item)}.md"
    _write_note(data, path)
    logging.info("Created shopping list item %s", path)
    return f"✓ Added shopping list item '{item}' at {path}."


@tool
def delete_shopping_list_item_tool(item: str) -> str:
    """Delete a shopping list item by name.

    Args:
        item: Name of the item to delete.

    Returns:
        Confirmation string.
    """
    path = _find_item_file(item)
    if path is None:
        return f"❌ Shopping list item '{item}' not found."
    try:
        path.unlink()
    except OSError as exc:
        logging.exception("Failed to delete %s", path)
        return f"❌ Could not delete '{item}': {exc}"
    return f"✓ Deleted shopping list item '{item}'."


@tool
def complete_shopping_list_item_tool(item: str) -> str:
    """Mark a shopping list item as bought.

    Args:
        item: Name of the item to mark as bought.

    Returns:
        Confirmation string.
    """
    path = _find_item_file(item)
    if path is None:
        return f"❌ Shopping list item '{item}' not found."
    data = _read_note(path) or {}
    data.pop("_file", None)
    data["bought"] = True
    _write_note(data, path)
    return f"✓ Marked '{item}' as bought."


@tool
def update_shopping_list_item_tool(
    item: str,
    description: str | None = None,
    url: str | None = None,
    price: float | None = None,
    category: str | None = None,
    bought: bool | None = None,
    new_name: str | None = None,
) -> str:
    """Update an existing shopping list item. Only provided fields are changed.

    Args:
        item: Current name of the item to update.
        description: New description (optional).
        url: New URL (optional).
        price: New price (optional).
        category: New category (optional).
        bought: New bought status (optional).
        new_name: New item name (optional). If provided, the note is renamed.

    Returns:
        Confirmation string.
    """
    path = _find_item_file(item)
    if path is None:
        return f"❌ Shopping list item '{item}' not found."
    data = _read_note(path) or {}
    data.pop("_file", None)
    if description is not None:
        data["description"] = str(description).strip()
    if url is not None:
        data["url"] = str(url).strip()
    if price is not None:
        try:
            data["price"] = float(price) if str(price) != "" else None
        except (TypeError, ValueError):
            data["price"] = None
    if category is not None:
        data["category"] = str(category).strip()
    if bought is not None:
        data["bought"] = bool(bought)
    if new_name and str(new_name).strip():
        data["item"] = str(new_name).strip()
        new_path = _vault_dir() / f"{_slugify(new_name)}.md"
        _write_note(data, new_path)
        if new_path != path:
            try:
                path.unlink()
            except OSError:
                pass
        return f"✓ Updated and renamed item to '{data['item']}'."
    _write_note(data, path)
    return f"✓ Updated shopping list item '{item}'."


@tool(return_direct=True)
def view_all_shopping_list_items_tool() -> Any:
    """View all shopping list items.

    Returns:
        A list of all shopping list items (dicts) in the Obsidian vault.
    """
    folder = _vault_dir()
    if not folder.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in folder.glob("*.md"):
        data = _read_note(path)
        if data is not None:
            items.append(data)
    items.sort(key=lambda d: (bool(d.get("bought")), str(d.get("item", "")).lower()))
    return items if items else "No shopping list items found."


@tool(return_direct=True)
def view_shopping_list_items_by_category_tool(category: str) -> Any:
    """View shopping list items filtered by category (case-insensitive).

    Args:
        category: Category to filter by.

    Returns:
        A list of matching shopping list items.
    """
    target = (category or "").strip().lower()
    if not target:
        return "❌ A category is required."
    all_items = view_all_shopping_list_items_tool.invoke({})
    if not isinstance(all_items, list):
        return all_items
    matches = [i for i in all_items if str(i.get("category", "")).strip().lower() == target]
    return matches if matches else f"No shopping list items found in category '{category}'."


def list_shopping_items_raw() -> list[dict[str, Any]]:
    """Non-tool helper used by the Streamlit page."""
    result = view_all_shopping_list_items_tool.invoke({})
    return result if isinstance(result, list) else []


def save_shopping_item_raw(
    original_name: str | None,
    item: str,
    description: str = "",
    url: str = "",
    price: float | None = None,
    category: str = "",
    bought: bool = False,
    date_created: str | None = None,
) -> str:
    """Create-or-update a shopping list item from the UI.

    If ``original_name`` is provided and an existing item matches, that item is
    updated (and renamed if ``item`` differs). Otherwise, a new item is created.
    """
    item = (item or "").strip()
    if not item:
        raise ValueError("Item name is required.")

    existing_path = _find_item_file(original_name) if original_name else None
    if existing_path is not None:
        data = _read_note(existing_path) or {}
        created = data.get("Date Created") or date_created or _now_str()
        new_data = _build_item(item, description, url, bought, price, category, created)
        new_path = _vault_dir() / f"{_slugify(item)}.md"
        _write_note(new_data, new_path)
        if new_path != existing_path:
            try:
                existing_path.unlink()
            except OSError:
                pass
        return str(new_path)

    data = _build_item(item, description, url, bought, price, category, date_created)
    path = _vault_dir() / f"{_slugify(item)}.md"
    if path.exists():
        raise FileExistsError(f"Shopping list item '{item}' already exists.")
    _write_note(data, path)
    return str(path)


def delete_shopping_item_raw(item: str) -> bool:
    path = _find_item_file(item)
    if path is None:
        return False
    path.unlink()
    return True

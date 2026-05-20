"""Tools for managing the book reading list in the Obsidian vault."""

from __future__ import annotations

from pathlib import Path

from langchain.tools import tool
from yaml import dump, safe_load

from config.config import config

import logging
logging.basicConfig(
    filename="personal_assistant_tool.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

BOOK_STATUSES = ["To Be Read", "Currently Reading", "Read", "Did not finish"]


def _get_vault() -> Path:
    return Path(config.get("obsidian_vault_book_path", "."))


def _format_author(author) -> str:
    """Format an author value that may be a list, a stringified list, or a plain string."""
    if isinstance(author, str) and author.startswith("["):
        import ast
        try:
            author = ast.literal_eval(author)
        except (ValueError, SyntaxError):
            pass
    if isinstance(author, list):
        names = [str(n).strip() for n in author if str(n).strip()]
        if len(names) == 0:
            return ""
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} & {names[1]}"
        return ", ".join(names[:-1]) + f", & {names[-1]}"
    return str(author).strip() if author else ""


def _find_book(folder: Path, title: str) -> Path | None:
    """Return the first .md file whose stem matches *title* (case-insensitive)."""
    for f in folder.glob("*.md"):
        if f.stem.lower() == title.strip().lower():
            return f
    return None


def _build_note_content(
    author: str = "",
    genre: str = "",
    notes: str = "",
    status: str = "To Be Read",
) -> str:
    if status not in BOOK_STATUSES:
        status = "To Be Read"
    book_data = {
        "author": author or "",
        "genre": genre or "",
        "read": status == "Read",
        "Notes": notes or "",
        "tags": ["#book"],
        "status": status,
    }
    return f"---\n{dump(book_data, default_flow_style=False, sort_keys=False, indent=2)}---"


@tool
def add_book_tool(
    title: str,
    author: str = "",
    genre: str = "",
    notes: str = "",
    status: str = "To Be Read",
) -> str:
    """
    Add a new book to the reading list in the Obsidian vault.

    Args:
        title: The title of the book.
        author: The author of the book (optional).
        genre: The genre of the book (optional).
        notes: Any notes about the book (optional).
        status: Reading status. One of "To Be Read", "Currently Reading",
                "Read", "Did not finish". Defaults to "To Be Read".

    Returns:
        A confirmation message.
    """
    logging.info("Adding book: %s", title)
    if status not in BOOK_STATUSES:
        return (
            f"Invalid status '{status}'. Valid options: {', '.join(BOOK_STATUSES)}"
        )
    folder = _get_vault()
    if not folder.exists():
        return f"Book vault path '{folder}' does not exist. Please configure OBSIDIAN_VAULT_BOOK_PATH."
    safe_title = title.strip().replace("/", "-").replace("\\", "-")
    new_file = folder / f"{safe_title}.md"
    content = _build_note_content(author, genre, notes, status)
    try:
        with open(new_file, "x", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        return f"Book '{title}' already exists in the vault."
    logging.info("Book '%s' created successfully.", title)
    return f"Book '{title}' has been added to your reading list with status '{status}'."


@tool
def update_book_status_tool(title: str, status: str) -> str:
    """
    Update the reading status of a book.

    Args:
        title: The title of the book.
        status: New status. One of "To Be Read", "Currently Reading",
                "Read", "Did not finish".

    Returns:
        A confirmation message.
    """
    if status not in BOOK_STATUSES:
        return (
            f"Invalid status '{status}'. Valid options: {', '.join(BOOK_STATUSES)}"
        )
    folder = _get_vault()
    path = _find_book(folder, title)
    if path is None:
        return f"Book '{title}' not found in the vault."
    try:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2) if text.startswith("---") else None
        if parts and len(parts) >= 3:
            data = safe_load(parts[1]) or {}
            data["status"] = status
            data["read"] = status == "Read"
            new_yaml = dump(data, default_flow_style=False, sort_keys=False, indent=2)
            path.write_text(f"---\n{new_yaml}---{parts[2]}", encoding="utf-8")
            return f"Book '{path.stem}' status updated to '{status}'."
    except OSError as exc:
        return f"Error updating book '{title}': {exc}"
    return f"Could not update book '{title}': invalid file format."


@tool
def update_book_tool(
    title: str,
    new_title: str = "",
    author: str = "",
    genre: str = "",
    notes: str = "",
    status: str = "",
) -> str:
    """
    Update one or more fields of an existing book note.

    Args:
        title: The current title of the book (used to locate the file).
        new_title: New title for the book (renames the file). Optional.
        author: New author value. Optional.
        genre: New genre value. Optional.
        notes: New notes value. Optional.
        status: New reading status. Optional. One of "To Be Read",
                "Currently Reading", "Read", "Did not finish".

    Returns:
        A confirmation message.
    """
    folder = _get_vault()
    path = _find_book(folder, title)
    if path is None:
        return f"Book '{title}' not found in the vault."
    if status and status not in BOOK_STATUSES:
        return (
            f"Invalid status '{status}'. Valid options: {', '.join(BOOK_STATUSES)}"
        )
    try:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2) if text.startswith("---") else None
        if not (parts and len(parts) >= 3):
            return f"Could not update book '{title}': invalid file format."
        data = safe_load(parts[1]) or {}
        if author:
            data["author"] = author
        if genre:
            data["genre"] = genre
        if notes:
            data["Notes"] = notes
        if status:
            data["status"] = status
            data["read"] = status == "Read"
        new_yaml = dump(data, default_flow_style=False, sort_keys=False, indent=2)
        new_content = f"---\n{new_yaml}---{parts[2]}"

        if new_title and new_title.strip() and new_title.strip().lower() != path.stem.lower():
            safe_new = new_title.strip().replace("/", "-").replace("\\", "-")
            new_path = folder / f"{safe_new}.md"
            if new_path.exists():
                return f"A book named '{new_title}' already exists."
            path.write_text(new_content, encoding="utf-8")
            path.rename(new_path)
            return f"Book '{title}' updated and renamed to '{new_title}'."
        else:
            path.write_text(new_content, encoding="utf-8")
            return f"Book '{path.stem}' updated successfully."
    except OSError as exc:
        return f"Error updating book '{title}': {exc}"


@tool
def list_books_tool(status: str = "") -> str:
    """
    List all books in the reading list, optionally filtered by status.

    Args:
        status: Optional filter. One of "To Be Read", "Currently Reading",
                "Read", "Did not finish". Leave empty for all books.

    Returns:
        A formatted list of books.
    """
    folder = _get_vault()
    if not folder.exists():
        return "Book vault not found."

    books: list[dict] = []
    for md_file in sorted(folder.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 2:
            continue
        try:
            data = safe_load(parts[1]) or {}
        except Exception:  # noqa: BLE001
            continue
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        tags_lower = [str(t).lstrip("#").lower() for t in tags]
        if tags_lower and "book" not in tags_lower:
            continue
        book_status = data.get("status", "To Be Read")
        if status and book_status.lower() != status.lower():
            continue
        books.append(
            {
                "title": md_file.stem,
                "author": _format_author(data.get("author", "")),
                "genre": data.get("genre", ""),
                "status": book_status,
            }
        )

    if not books:
        filter_msg = f" with status '{status}'" if status else ""
        return f"No books found{filter_msg}."

    lines = [f"Found {len(books)} book(s):"]
    for b in books:
        line = f"- **{b['title']}**"
        if b["author"]:
            line += f" by {b['author']}"
        line += f" [{b['status']}]"
        if b["genre"]:
            line += f" ({b['genre']})"
        lines.append(line)
    return "\n".join(lines)


@tool
def delete_book_tool(title: str) -> str:
    """
    Delete a book from the reading list.

    Args:
        title: The title of the book to delete.

    Returns:
        A confirmation message.
    """
    folder = _get_vault()
    path = _find_book(folder, title)
    if path is None:
        return f"Book '{title}' not found in the vault."
    stem = path.stem
    path.unlink()
    logging.info("Book '%s' deleted.", stem)
    return f"Book '{stem}' has been deleted from your reading list."

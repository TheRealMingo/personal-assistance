"""Convert a PDF file to a Markdown file.

Usage:
    python tools/pdf_to_markdown.py input.pdf
    python tools/pdf_to_markdown.py input.pdf -o output.md --page-breaks
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pypdf import PdfReader

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def pdf_to_markdown_text(pdf_path: Path, include_page_breaks: bool = False) -> str:
    """Extract text from each PDF page and format it as Markdown."""
    logger.info(f"Converting PDF to Markdown: {pdf_path} (page_breaks={include_page_breaks})")
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []

    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()

        parts.append(f"## Page {page_index}\n")
        if text:
            parts.append(text)
        else:
            parts.append("_(No extractable text on this page)_")

        if include_page_breaks and page_index < len(reader.pages):
            parts.append("\n\n---\n")
        else:
            parts.append("\n")

    return "\n".join(parts).strip() + "\n"


def build_output_path(input_path: Path, output_path: str | None) -> Path:
    if output_path:
        return Path(output_path).expanduser().resolve()
    return input_path.with_suffix(".md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a PDF file to Markdown.")
    parser.add_argument("pdf", help="Path to input PDF file.")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output Markdown file path. Defaults to <input>.md",
    )
    parser.add_argument(
        "--page-breaks",
        action="store_true",
        help="Insert Markdown separators between pages.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()

    if not pdf_path.exists() or not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a .pdf file: {pdf_path}")

    output_path = build_output_path(pdf_path, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    markdown = pdf_to_markdown_text(
        pdf_path=pdf_path,
        include_page_breaks=args.page_breaks,
    )
    output_path.write_text(markdown, encoding="utf-8")

    logger.info(f"Markdown written to: {output_path}")
    print(f"Markdown written to: {output_path}")


if __name__ == "__main__":
    main()

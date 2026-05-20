"""Web search and content extraction tools.

Primary provider: Tavily (search + extract).
Fallback provider: Brave LLM Context API (search only).
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
from langchain.tools import tool

from config.config import config
from tools.api_call_tracker import record_api_call

logging.basicConfig(
    filename="app.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
_BRAVE_LLM_URL = "https://api.search.brave.com/res/v1/llm/context"
_REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tavily_search(query: str, max_results: int = 5) -> str:
    """Return formatted results from Tavily Search."""
    api_key = config.get("tavily_api_key", "")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not configured")

    record_api_call("tavily")
    logging.info("Tavily search POST %s query=%r max_results=%d", _TAVILY_SEARCH_URL, query, max_results)
    resp = requests.post(
        _TAVILY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        },
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    logging.info("Tavily search response status=%d results=%d", resp.status_code, len(data.get("results", [])))

    lines: list[str] = []
    answer = data.get("answer")
    if answer:
        lines.append(f"**Summary:** {answer}\n")
    for result in data.get("results", []):
        lines.append(f"**{result.get('title', 'Untitled')}**")
        lines.append(f"URL: {result.get('url', '')}")
        content = result.get("content", "").strip()
        if content:
            lines.append(content)
        lines.append("")
    return "\n".join(lines).strip() if lines else "No results found."


def _brave_search(query: str, max_results: int = 5) -> str:
    """Return formatted results from the Brave LLM Context API."""
    api_key = config.get("brave_search_api_key", "")
    if not api_key:
        raise ValueError("BRAVE_SEARCH_API_KEY not configured")

    record_api_call("brave_search")
    logging.info("Brave search GET %s query=%r max_results=%d", _BRAVE_LLM_URL, query, max_results)
    resp = requests.get(
        _BRAVE_LLM_URL,
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
        params={"q": query, "count": max_results},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    logging.info("Brave search response status=%d", resp.status_code)

    lines: list[str] = []
    sources = data.get("sources", {})
    for item in data.get("grounding", {}).get("generic", []):
        url = item.get("url", "")
        title = (sources.get(url) or {}).get("title") or item.get("title", "Untitled")
        lines.append(f"**{title}**")
        lines.append(f"URL: {url}")
        for snippet in item.get("snippets", []):
            lines.append(snippet.strip())
        lines.append("")
    return "\n".join(lines).strip() if lines else "No results found."


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool
def web_search_tool(query: str, max_results: int = 5) -> str:
    """Search the web for up-to-date information.

    Uses Tavily Search as the primary provider. Falls back to the Brave LLM
    Context API if Tavily is unavailable or not configured.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 5).

    Returns:
        Formatted search results with titles, URLs, and content snippets.
    """
    logging.info("web_search_tool called with query: %s", query)
    tavily_key = config.get("tavily_api_key", "")
    brave_key = config.get("brave_search_api_key", "")

    if tavily_key:
        try:
            return _tavily_search(query, max_results)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Tavily search failed (%s); falling back to Brave Search.", exc)

    if brave_key:
        try:
            return _brave_search(query, max_results)
        except Exception as exc:  # noqa: BLE001
            logging.error("Brave search also failed: %s", exc)
            return f"Web search failed: {exc}"

    return (
        "Web search is unavailable. "
        "Please configure TAVILY_API_KEY or BRAVE_SEARCH_API_KEY in your .env file."
    )


@tool
def web_extract_tool(url: str, query: Optional[str] = None) -> str:
    """Extract and return the content of a specific web page.

    Uses Tavily Extract.

    Args:
        url: The URL of the page to extract content from.
        query: Optional query string used to rerank extracted chunks by relevance.

    Returns:
        Extracted page content in markdown format.
    """
    logging.info("web_extract_tool called for URL: %s", url)
    api_key = config.get("tavily_api_key", "")
    if not api_key:
        return (
            "Web extraction is unavailable. "
            "Please configure TAVILY_API_KEY."
        )

    payload: dict = {"urls": url, "extract_depth": "basic", "format": "markdown"}
    if query:
        payload["query"] = query

    try:
        logging.info("Tavily extract POST %s url=%r", _TAVILY_EXTRACT_URL, url)
        resp = requests.post(
            _TAVILY_EXTRACT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        logging.info("Tavily extract response status=%d results=%d failed=%d",
                     resp.status_code,
                     len(data.get("results", [])),
                     len(data.get("failed_results", [])))

        lines: list[str] = []
        for result in data.get("results", []):
            lines.append(f"**URL:** {result.get('url', url)}")
            content = result.get("raw_content", "").strip()
            if content:
                lines.append(content)
            lines.append("")

        failed = data.get("failed_results", [])
        if failed:
            lines.append(f"*Could not extract {len(failed)} URL(s).*")

        return "\n".join(lines).strip() if lines else "No content extracted."
    except Exception as exc:  # noqa: BLE001
        logging.error("web_extract_tool failed for %s: %s", url, exc)
        return f"Failed to extract content from {url}: {exc}"

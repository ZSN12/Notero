"""Optional web-search augmentation for RAG and quiz generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import (
    BRAVE_SEARCH_API_KEY,
    TAVILY_API_KEY,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PROVIDER,
    WEB_SEARCH_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    content: str = ""
    score: float = 0.0

    def to_source(self, index: int) -> dict[str, Any]:
        text = (self.content or self.snippet or "").strip()
        return {
            "chunk_id": f"web-{index}",
            "notebook_id": "web",
            "notebook_title": "联网资料",
            "session_id": "web",
            "session_title": self.title or "网页资料",
            "source_type": "web",
            "snippet": text[:800],
            "score": self.score,
            "page": None,
            "block_id": self.url,
            "chunk_index": index,
            "metadata": {
                "url": self.url,
                "title": self.title,
                "provider": WEB_SEARCH_PROVIDER,
                "external": True,
            },
        }


def is_web_search_configured() -> bool:
    if not WEB_SEARCH_ENABLED:
        return False
    if WEB_SEARCH_PROVIDER == "tavily":
        return bool(TAVILY_API_KEY)
    if WEB_SEARCH_PROVIDER == "brave":
        return bool(BRAVE_SEARCH_API_KEY)
    return False


def search_web(query: str, max_results: int | None = None) -> list[WebSearchResult]:
    """Search the public web.

    Failures are logged and converted to an empty result set so callers can
    safely fall back to local-only behavior.
    """
    query = query.strip()
    if not query or not is_web_search_configured():
        return []
    limit = max(1, min(max_results or WEB_SEARCH_MAX_RESULTS, 10))
    try:
        if WEB_SEARCH_PROVIDER == "brave":
            return _search_brave(query, limit)
        return _search_tavily(query, limit)
    except Exception:
        logger.exception("web_search_failed provider=%s query=%s", WEB_SEARCH_PROVIDER, query[:120])
        return []


def format_web_results(results: list[WebSearchResult], max_chars: int = 4000) -> str:
    """Render search results as compact LLM context."""
    lines: list[str] = []
    used = 0
    for i, result in enumerate(results, 1):
        text = (result.content or result.snippet or "").strip()
        if not text:
            continue
        entry = (
            f"[W{i}] 标题：{result.title or '网页资料'}\n"
            f"URL：{result.url}\n"
            f"摘要：{text[:900]}\n"
        )
        if used + len(entry) > max_chars:
            break
        lines.append(entry)
        used += len(entry)
    return "\n".join(lines)


def _search_tavily(query: str, max_results: int) -> list[WebSearchResult]:
    payload = {
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
        "max_results": max_results,
    }
    with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS) as client:
        response = client.post(
            "https://api.tavily.com/search",
            json=payload,
            headers={
                "Authorization": f"Bearer {TAVILY_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

    items = data.get("results") or []
    results: list[WebSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        content = str(item.get("content") or item.get("raw_content") or "").strip()
        results.append(
            WebSearchResult(
                title=str(item.get("title") or url).strip(),
                url=url,
                snippet=content[:500],
                content=content,
                score=float(item.get("score") or 0.0),
            )
        )
    return results


def _search_brave(query: str, max_results: int) -> list[WebSearchResult]:
    with httpx.Client(timeout=WEB_SEARCH_TIMEOUT_SECONDS) as client:
        response = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results, "text_decorations": "false"},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
            },
        )
        response.raise_for_status()
        data = response.json()

    items = ((data.get("web") or {}).get("results") or [])
    results: list[WebSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        snippet = str(item.get("description") or "").strip()
        results.append(
            WebSearchResult(
                title=str(item.get("title") or url).strip(),
                url=url,
                snippet=snippet,
                content=snippet,
                score=0.0,
            )
        )
    return results

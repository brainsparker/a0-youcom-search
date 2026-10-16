"""Minimal async You.com search client for the Agent Zero youcom_search plugin.

Framework-independent: depends only on aiohttp so it can be unit tested
without an Agent Zero checkout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aiohttp

KEYLESS_URL = "https://api.you.com/v1/agents/search"
KEYED_URL = "https://ydc-index.io/v1/search"
USER_AGENT = "youdotcom-integration/agent0ai-agent-zero"
LIMIT_MESSAGE = (
    "You.com free tier limit reached for today; use search_engine (SearXNG) "
    "or set YDC_API_KEY."
)


class YouComError(Exception):
    """Non-rate-limit failure talking to You.com."""


class YouComRateLimited(YouComError):
    """HTTP 429 from You.com (free daily limit reached)."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    keyed: bool = False


def build_request(query: str, count: int, api_key: str | None) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (url, params, headers) for a keyless or keyed search."""
    params = {"query": query, "count": str(int(count))}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
        return KEYED_URL, params, headers
    return KEYLESS_URL, params, headers


def parse_results(data: Any, limit: int) -> list[SearchResult]:
    """Map results.web[] (url, title, description, snippets) to SearchResult."""
    web = ((data or {}).get("results") or {}).get("web") or []
    out: list[SearchResult] = []
    for item in web:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        snippets = [s for s in (item.get("snippets") or []) if isinstance(s, str) and s.strip()]
        snippet = (item.get("description") or "").strip()
        if snippets:
            first = snippets[0].strip()
            snippet = f"{snippet} {first}".strip() if snippet and first not in snippet else (snippet or first)
        out.append(SearchResult(title=(item.get("title") or "").strip(), url=item["url"], snippet=snippet))
        if len(out) >= limit:
            break
    return out


def format_results(results: list[SearchResult]) -> str:
    """Same plain-text shape as Agent Zero's search_engine: title\\nurl\\nsnippet blocks."""
    return "\n\n".join(f"{r.title}\n{r.url}\n{r.snippet}" for r in results).strip()


async def search(
    query: str,
    *,
    count: int = 10,
    api_key: str | None = None,
    timeout: float = 15,
    session: aiohttp.ClientSession | None = None,
) -> SearchResponse:
    url, params, headers = build_request(query, count, api_key)
    own = session is None
    sess = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
    try:
        async with sess.get(url, params=params, headers=headers) as resp:
            if resp.status == 429:
                raise YouComRateLimited(LIMIT_MESSAGE)
            if resp.status >= 400:
                body = (await resp.text())[:300]
                raise YouComError(f"You.com search failed: HTTP {resp.status} {body}".strip())
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as e:
        raise YouComError(f"You.com search failed: {e}") from e
    finally:
        if own:
            await sess.close()
    return SearchResponse(results=parse_results(data, count), keyed=bool(api_key))

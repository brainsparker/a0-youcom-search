"""Minimal async You.com search client for the Agent Zero youcom_search plugin.

Framework-independent: depends only on aiohttp so it can be unit tested
without an Agent Zero checkout.
"""
from __future__ import annotations

import datetime
import re
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


class InvalidFreshness(YouComError):
    """The freshness argument is not a window or date range You.com accepts."""


# Canonical windows, narrowest first, with how each one reads in a message.
FRESHNESS_WINDOWS = {
    "day": "the past day",
    "week": "the past week",
    "month": "the past month",
    "year": "the past year",
}
# Next wider window, used when a window comes back empty.
WIDER_FRESHNESS = {"day": "week", "week": "month", "month": "year"}
_FRESHNESS_ALIASES = {
    "d": "day", "24h": "day", "today": "day", "pd": "day",
    "w": "week", "7d": "week", "pw": "week",
    "m": "month", "30d": "month", "pm": "month",
    "y": "year", "365d": "year", "py": "year",
}
_DATE_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*(?:to|\.\.|/)\s*(\d{4}-\d{2}-\d{2})$")
FRESHNESS_HELP = (
    "freshness must be one of day, week, month, year, "
    "or a date range like 2026-11-01to2026-11-10"
)


def normalize_freshness(value: Any) -> str | None:
    """Return the freshness value You.com expects, or None when no window was asked for.

    Accepts day/week/month/year, common short forms (d, w, m, y, 24h, 7d, 30d),
    and a date range (YYYY-MM-DDtoYYYY-MM-DD; ".." and "/" also separate the dates).
    Raises InvalidFreshness for anything else, so a typo costs no search.
    """
    text = str(value or "").strip().lower()
    if not text or text in ("any", "all", "none", "anytime"):
        return None
    for prefix in ("past ", "last "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    text = _FRESHNESS_ALIASES.get(text, text)
    if text in FRESHNESS_WINDOWS:
        return text
    match = _DATE_RANGE.match(text)
    if match:
        try:
            start, end = (datetime.date.fromisoformat(d) for d in match.groups())
        except ValueError as e:
            raise InvalidFreshness(f"Error: {FRESHNESS_HELP} ({e})") from e
        if start > end:
            start, end = end, start
        return f"{start.isoformat()}to{end.isoformat()}"
    raise InvalidFreshness(f"Error: {FRESHNESS_HELP}; got {str(value).strip()!r}")


def describe_freshness(freshness: str) -> str:
    """Human wording for a normalized freshness value."""
    if freshness in FRESHNESS_WINDOWS:
        return FRESHNESS_WINDOWS[freshness]
    start, _, end = freshness.partition("to")
    return f"{start} to {end}"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    date: str = ""  # YYYY-MM-DD from the result's page_age, when You.com has one


@dataclass
class SearchResponse:
    results: list[SearchResult] = field(default_factory=list)
    keyed: bool = False


def build_request(
    query: str, count: int, api_key: str | None, freshness: str | None = None
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (url, params, headers) for a keyless or keyed search.

    freshness is a value from normalize_freshness(); it is left out when empty.
    """
    params = {"query": query, "count": str(int(count))}
    if freshness:
        params["freshness"] = freshness
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
        return KEYED_URL, params, headers
    return KEYLESS_URL, params, headers


def _page_date(value: Any) -> str:
    """page_age is an ISO timestamp (2026-11-14T13:28:53); keep the date, drop anything else."""
    text = str(value or "").strip()[:10]
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def parse_results(data: Any, limit: int) -> list[SearchResult]:
    """Map results.web[] (url, title, description, snippets, page_age) to SearchResult."""
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
        out.append(SearchResult(
            title=(item.get("title") or "").strip(),
            url=item["url"],
            snippet=snippet,
            date=_page_date(item.get("page_age")),
        ))
        if len(out) >= limit:
            break
    return out


def format_results(results: list[SearchResult], show_dates: bool = False) -> str:
    """Same plain-text shape as Agent Zero's search_engine: title\\nurl\\nsnippet blocks.

    With show_dates, a result that has a page date gets it after the title:
    "Title (2026-11-14)". Results without a date are unchanged.
    """
    blocks = []
    for r in results:
        title = f"{r.title} ({r.date})" if show_dates and r.date else r.title
        blocks.append(f"{title}\n{r.url}\n{r.snippet}")
    return "\n\n".join(blocks).strip()


async def search(
    query: str,
    *,
    count: int = 10,
    api_key: str | None = None,
    timeout: float = 15,
    freshness: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> SearchResponse:
    url, params, headers = build_request(query, count, api_key, normalize_freshness(freshness))
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

import os
import re
import types

import pytest

from conftest import client, tool, plugins_mod, secrets_mod

KEYLESS = re.compile(r"^https://api\.you\.com/v1/agents/search\?.*$")
KEYED = re.compile(r"^https://ydc-index\.io/v1/search\?.*$")
SAMPLE = {"results": {"web": [
    {"url": "https://a.example", "title": "A", "description": "desc a", "snippets": ["snip a"]},
    {"url": "https://b.example", "title": "B", "description": "", "snippets": ["snip b"]},
    {"title": "no url"},
]}}
DATED = {"results": {"web": [
    {"url": "https://a.example", "title": "A", "description": "desc a", "page_age": "2026-11-14T13:28:53"},
    {"url": "https://b.example", "title": "B", "description": "desc b", "page_age": None},
    {"url": "https://c.example", "title": "C", "description": "desc c", "page_age": "3 days ago"},
    {"url": "https://d.example", "title": "D", "description": "desc d", "page_age": "2026-11-09"},
]}}
EMPTY = {"results": {}}  # what You.com returns when a freshness window has nothing


class _Resp:
    def __init__(self, status, payload, body):
        self.status, self._payload, self._body = status, payload, body

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class MockHTTP:
    """Tiny mocked-HTTP harness: patches aiohttp.ClientSession in the client module."""

    def __init__(self):
        self.routes, self.requests = [], {}

    def get(self, pattern, status=200, payload=None, body=""):
        self.routes.append((pattern, status, payload, body))

    def __enter__(self):
        harness = self

        class FakeSession:
            def __init__(self, *a, **k):
                pass

            def get(self, url, params=None, headers=None):
                from urllib.parse import urlencode
                full = f"{url}?{urlencode(params or {})}"
                harness.requests.setdefault(("GET", full), []).append(
                    types.SimpleNamespace(kwargs={"params": params, "headers": headers}))
                for i, (pat, status, payload, body) in enumerate(harness.routes):
                    if pat.match(full):
                        harness.routes.pop(i)
                        return _Resp(status, payload, body)
                raise AssertionError(f"unexpected request {full}")

            async def close(self):
                pass

        self._orig = client.aiohttp.ClientSession
        client.aiohttp.ClientSession = FakeSession
        return self

    def __exit__(self, *a):
        client.aiohttp.ClientSession = self._orig
        return False


def test_parse_and_format():
    res = client.parse_results(SAMPLE, 10)
    assert [r.url for r in res] == ["https://a.example", "https://b.example"]
    assert res[0].snippet == "desc a snip a"
    assert res[1].snippet == "snip b"
    assert client.format_results(res) == "A\nhttps://a.example\ndesc a snip a\n\nB\nhttps://b.example\nsnip b"
    assert len(client.parse_results(SAMPLE, 1)) == 1
    assert client.parse_results({}, 5) == []


def test_build_request():
    url, params, headers = client.build_request("q", 5, None)
    assert url == client.KEYLESS_URL and "X-API-Key" not in headers
    assert params == {"query": "q", "count": "5"}
    assert headers["User-Agent"] == "youdotcom-integration/agent0ai-agent-zero"
    url, _, headers = client.build_request("q", 5, "k")
    assert url == client.KEYED_URL and headers["X-API-Key"] == "k"


@pytest.mark.asyncio
async def test_keyless_search():
    with MockHTTP() as m:
        m.get(KEYLESS, payload=SAMPLE)
        res = await client.search("hello", count=3)
        (key, calls), = m.requests.items()
        assert str(key[1]).startswith(client.KEYLESS_URL)
        assert "X-API-Key" not in calls[0].kwargs["headers"]
        assert calls[0].kwargs["headers"]["User-Agent"] == client.USER_AGENT
    assert not res.keyed and len(res.results) == 2


@pytest.mark.asyncio
async def test_keyed_search():
    with MockHTTP() as m:
        m.get(KEYED, payload=SAMPLE)
        res = await client.search("hello", api_key="secret")
        (_, calls), = m.requests.items()
        assert calls[0].kwargs["headers"]["X-API-Key"] == "secret"
    assert res.keyed


@pytest.mark.asyncio
async def test_429_and_errors():
    with MockHTTP() as m:
        m.get(KEYLESS, status=429)
        with pytest.raises(client.YouComRateLimited):
            await client.search("x")
        m.get(KEYLESS, status=500, body="boom")
        with pytest.raises(client.YouComError, match="HTTP 500"):
            await client.search("x")


def test_normalize_freshness():
    n = client.normalize_freshness
    assert n(None) is None and n("") is None and n("  ") is None and n("any") is None
    assert [n(v) for v in ("day", "Week", " MONTH ", "year")] == ["day", "week", "month", "year"]
    assert [n(v) for v in ("d", "24h", "today", "w", "7d", "m", "30d", "y")] == [
        "day", "day", "day", "week", "week", "month", "month", "year"]
    assert n("past week") == "week" and n("last month") == "month"
    assert n("2026-11-01to2026-11-10") == "2026-11-01to2026-11-10"
    assert n("2026-11-01 to 2026-11-10") == "2026-11-01to2026-11-10"
    assert n("2026-11-01..2026-11-10") == "2026-11-01to2026-11-10"
    assert n("2026-11-10/2026-11-01") == "2026-11-01to2026-11-10"  # reversed range is put in order
    for bad in ("fortnight", "2026-13-01to2026-13-02", "2026-11-01", "hour"):
        with pytest.raises(client.InvalidFreshness, match="freshness must be one of"):
            n(bad)
    assert issubclass(client.InvalidFreshness, client.YouComError)


def test_describe_freshness():
    assert client.describe_freshness("day") == "the past day"
    assert client.describe_freshness("2026-11-01to2026-11-10") == "2026-11-01 to 2026-11-10"
    # every window but the widest has a wider one, and it is a real window
    assert set(client.WIDER_FRESHNESS) == set(client.FRESHNESS_WINDOWS) - {"year"}
    assert set(client.WIDER_FRESHNESS.values()) <= set(client.FRESHNESS_WINDOWS)


def test_build_request_freshness():
    _, params, _ = client.build_request("q", 5, None, "week")
    assert params == {"query": "q", "count": "5", "freshness": "week"}
    url, params, _ = client.build_request("q", 5, "k", "2026-11-01to2026-11-10")
    assert url == client.KEYED_URL and params["freshness"] == "2026-11-01to2026-11-10"
    assert "freshness" not in client.build_request("q", 5, None, None)[1]


def test_page_dates():
    res = client.parse_results(DATED, 10)
    assert [r.date for r in res] == ["2026-11-14", "", "", "2026-11-09"]
    assert client.format_results(res) == (
        "A\nhttps://a.example\ndesc a\n\nB\nhttps://b.example\ndesc b\n\n"
        "C\nhttps://c.example\ndesc c\n\nD\nhttps://d.example\ndesc d")
    assert client.format_results(res, show_dates=True) == (
        "A (2026-11-14)\nhttps://a.example\ndesc a\n\nB\nhttps://b.example\ndesc b\n\n"
        "C\nhttps://c.example\ndesc c\n\nD (2026-11-09)\nhttps://d.example\ndesc d")


@pytest.mark.asyncio
async def test_search_sends_freshness():
    with MockHTTP() as m:
        m.get(KEYLESS, payload=DATED)
        res = await client.search("hello", freshness="W")
        (key, calls), = m.requests.items()
        assert calls[0].kwargs["params"]["freshness"] == "week"
    assert res.results[0].date == "2026-11-14"
    with MockHTTP() as m:  # an invalid window never reaches the network
        with pytest.raises(client.InvalidFreshness):
            await client.search("hello", freshness="fortnight")
        assert m.requests == {}


async def _noop(*a, **k):
    return None


def _agent():
    return types.SimpleNamespace(context=None, handle_intervention=_noop)


@pytest.mark.asyncio
async def test_tool_keyless_then_secret_key(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {"api_key": "", "results": 10, "timeout": 15}
    secrets_mod.SECRETS = {}
    with MockHTTP() as m:
        m.get(KEYLESS, payload=SAMPLE)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi")
    assert r.message.startswith("A\nhttps://a.example") and r.break_loop is False
    secrets_mod.SECRETS = {"YDC_API_KEY": "fromsecrets"}
    with MockHTTP() as m:
        m.get(KEYED, payload=SAMPLE)
        await tool.YouComSearch(agent=_agent()).execute(query="hi")
        (_, calls), = m.requests.items()
        assert calls[0].kwargs["headers"]["X-API-Key"] == "fromsecrets"
    secrets_mod.SECRETS = {}


@pytest.mark.asyncio
async def test_tool_429_falls_back_to_searxng(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {"fallback_to_searxng": True}
    with MockHTTP() as m:
        m.get(KEYLESS, status=429)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi")
    assert r.message.startswith(client.LIMIT_MESSAGE)
    assert "https://sx.example" in r.message
    plugins_mod.CONFIG = {"fallback_to_searxng": False}
    with MockHTTP() as m:
        m.get(KEYLESS, status=429)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi")
    assert r.message == client.LIMIT_MESSAGE


def _sent(m):
    """Freshness value of every request, in order."""
    return [c.kwargs["params"].get("freshness") for calls in m.requests.values() for c in calls]


@pytest.mark.asyncio
async def test_tool_freshness_and_dates(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {}
    with MockHTTP() as m:
        m.get(KEYLESS, payload=DATED)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="week")
        assert _sent(m) == ["week"]
    assert r.message.startswith("A (2026-11-14)\nhttps://a.example")
    plugins_mod.CONFIG = {"show_dates": False}
    with MockHTTP() as m:
        m.get(KEYLESS, payload=DATED)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi")
        assert _sent(m) == [None]  # no freshness arg, no freshness param
    assert r.message.startswith("A\nhttps://a.example")


@pytest.mark.asyncio
async def test_tool_invalid_freshness_costs_no_search(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {}
    with MockHTTP() as m:
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="fortnight")
        assert m.requests == {}
    assert "freshness must be one of day, week, month, year" in r.message and "'fortnight'" in r.message
    assert r.break_loop is False


@pytest.mark.asyncio
async def test_tool_widens_an_empty_window(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {}
    with MockHTTP() as m:  # day is empty, week has results
        m.get(re.compile(r".*freshness=day.*"), payload=EMPTY)
        m.get(re.compile(r".*freshness=week.*"), payload=DATED)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="day")
        assert _sent(m) == ["day", "week"]
    assert r.message.startswith("No You.com results from the past day; showing the past week instead.\n\nA (2026-11-14)")
    with MockHTTP() as m:  # both empty: one widening step only, then say so
        m.get(re.compile(r".*freshness=month.*"), payload=EMPTY)
        m.get(re.compile(r".*freshness=year.*"), payload={"results": {"web": []}})
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="month")
        assert _sent(m) == ["month", "year"]
    assert r.message.startswith("No You.com results from the past month or the past year.")
    with MockHTTP() as m:  # year is the widest window
        m.get(KEYLESS, payload=EMPTY)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="year")
        assert _sent(m) == ["year"]
    assert r.message.startswith("No You.com results from the past year.")
    with MockHTTP() as m:  # a date range is exact and is never widened
        m.get(KEYLESS, payload=EMPTY)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="2026-11-01to2026-11-02")
        assert _sent(m) == ["2026-11-01to2026-11-02"]
    assert r.message.startswith("No You.com results from 2026-11-01 to 2026-11-02.")
    plugins_mod.CONFIG = {"widen_freshness": False}
    with MockHTTP() as m:  # widening switched off
        m.get(KEYLESS, payload=EMPTY)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="day")
        assert _sent(m) == ["day"]
    assert r.message.startswith("No You.com results from the past day.")
    plugins_mod.CONFIG = {}
    with MockHTTP() as m:  # no window asked for: plain empty message, one request
        m.get(KEYLESS, payload=EMPTY)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi")
        assert _sent(m) == [None]
    assert r.message == "No results from You.com."


@pytest.mark.asyncio
async def test_tool_429_during_freshness(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    plugins_mod.CONFIG = {"fallback_to_searxng": True}
    with MockHTTP() as m:  # limit hit on the first call
        m.get(KEYLESS, status=429)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="day")
    assert "SearXNG results instead (not time-filtered):" in r.message and "https://sx.example" in r.message
    with MockHTTP() as m:  # limit hit on the widening call
        m.get(re.compile(r".*freshness=day.*"), payload=EMPTY)
        m.get(re.compile(r".*freshness=week.*"), status=429)
        r = await tool.YouComSearch(agent=_agent()).execute(query="hi", freshness="day")
    assert r.message.startswith(client.LIMIT_MESSAGE) and "not time-filtered" in r.message


@pytest.mark.asyncio
async def test_tool_empty_query():
    r = await tool.YouComSearch(agent=_agent()).execute(query="")
    assert "no query" in r.message


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("YDC_LIVE") != "1", reason="set YDC_LIVE=1 for the live keyless smoke test")
async def test_live_keyless_smoke():
    try:
        res = await client.search("Agent Zero AI framework", count=3)
    except client.YouComRateLimited:
        pytest.skip("free daily limit reached")
    assert res.results and all(r.url.startswith("http") for r in res.results)


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("YDC_LIVE") != "1", reason="set YDC_LIVE=1 for the live keyless smoke test")
async def test_live_keyless_freshness():
    import datetime
    try:
        res = await client.search("AI agents news", count=5, freshness="week")
    except client.YouComRateLimited:
        pytest.skip("free daily limit reached")
    dated = [r.date for r in res.results if r.date]
    assert dated, "expected page dates on a freshness=week search"
    # generous bound: the window is a week, pages can be re-dated a little either side
    oldest = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    assert all(d >= oldest for d in dated), dated

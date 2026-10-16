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

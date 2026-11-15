import os

from helpers import plugins
from helpers.errors import handle_error
from helpers.tool import Tool, Response

from usr.plugins.youcom_search.helpers import youcom_client

PLUGIN_NAME = "youcom_search"


def _resolve_api_key(agent, config: dict) -> str:
    key = (config.get("api_key") or "").strip()
    if key:
        return key
    try:
        from helpers.secrets import get_secrets_manager

        key = (get_secrets_manager(agent.context).load_secrets().get("YDC_API_KEY") or "").strip()
    except Exception:  # secrets unavailable: fall through to env
        key = ""
    return key or os.environ.get("YDC_API_KEY", "").strip()


class YouComSearch(Tool):
    async def execute(self, query="", freshness="", **kwargs):
        if not query:
            return Response(message="Error: no query provided", break_loop=False)
        try:
            window = youcom_client.normalize_freshness(freshness)
        except youcom_client.InvalidFreshness as e:
            # Tell the agent what to send instead; a typo should not cost a search.
            return Response(message=str(e), break_loop=False)

        config = plugins.get_plugin_config(PLUGIN_NAME, agent=self.agent) or {}
        count = int(config.get("results", 10) or 10)
        timeout = float(config.get("timeout", 15) or 15)
        show_dates = bool(config.get("show_dates", True))
        api_key = _resolve_api_key(self.agent, config)

        async def run(freshness_value):
            res = await youcom_client.search(
                query, count=count, api_key=api_key or None, timeout=timeout, freshness=freshness_value
            )
            return youcom_client.format_results(res.results, show_dates=show_dates)

        try:
            message = await run(window)
            if not message and window:
                message = await self._widen(run, window, bool(config.get("widen_freshness", True)))
            message = message or "No results from You.com."
        except youcom_client.YouComRateLimited:
            message = youcom_client.LIMIT_MESSAGE
            if config.get("fallback_to_searxng", True):
                label = "SearXNG results instead (not time-filtered):" if window else "SearXNG results instead:"
                message = f"{message}\n\n{label}\n\n{await self._searxng(query, count)}"
        except youcom_client.YouComError as e:
            message = str(e)

        await self.agent.handle_intervention(message)
        return Response(message=message, break_loop=False)

    async def _widen(self, run, window: str, allowed: bool) -> str:
        """Nothing came back inside the window: say so, and try the next wider one once."""
        asked = youcom_client.describe_freshness(window)
        wider = youcom_client.WIDER_FRESHNESS.get(window) if allowed else None
        if not wider:
            return f"No You.com results from {asked}. Search again with a wider freshness, or without one."
        tried = youcom_client.describe_freshness(wider)
        results = await run(wider)
        if not results:
            return f"No You.com results from {asked} or {tried}. Search again with a wider freshness, or without one."
        return f"No You.com results from {asked}; showing {tried} instead.\n\n{results}"

    async def _searxng(self, query: str, count: int) -> str:
        try:
            from helpers.searxng import search as searxng

            result = await searxng(query)
        except Exception as e:  # pylint: disable=broad-exception-caught
            handle_error(e)
            return f"SearXNG search failed: {e}"
        blocks = [f"{i['title']}\n{i['url']}\n{i.get('content', '')}" for i in (result or {}).get("results", [])]
        return "\n\n".join(blocks[:count]).strip() or "No results from SearXNG."

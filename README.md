# You.com Search for Agent Zero

Adds one agent tool, `youcom_search`, next to Agent Zero's built-in SearXNG `search_engine`.
It doesn't change `search_engine`, the bundled SearXNG instance, or any core file. **SearXNG stays the default**; the agent can use either.

- **No key needed.** Calls the [You.com](https://you.com/?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme) keyless endpoint `https://api.you.com/v1/agents/search`. No account, 100 searches a day.
- **Optional key.** Set `YDC_API_KEY` in Agent Zero secrets (or the plugin settings) to use the keyed Search API at `https://ydc-index.io/v1/search`. Get a key at the [You.com platform](https://you.com/platform?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme).
- Returns title, URL and snippet per result, in the same plain-text shape as `search_engine`.
- Past the free 100 a day, the tool says so and (by default) runs the built-in SearXNG search instead.

Requests to You.com send `User-Agent: youdotcom-integration/agent0ai-agent-zero`. Nothing else is sent anywhere.

## Install

Install from the Plugin Hub, or copy this repository to `usr/plugins/youcom_search/` and enable it.

## Settings

| key | default | meaning |
| --- | --- | --- |
| `api_key` | `""` | optional; otherwise `YDC_API_KEY` from secrets/env; otherwise keyless |
| `results` | `10` | max results |
| `timeout` | `15` | HTTP timeout (s) |
| `fallback_to_searxng` | `true` | use SearXNG when the free limit is hit |

## Remove

Disable it in the Plugin Hub or delete `usr/plugins/youcom_search/`. It leaves nothing outside its own folder.

## Development

```
pip install -r requirements-dev.txt
pytest                 # mocked HTTP
YDC_LIVE=1 pytest      # also runs one live keyless smoke test
```

Tested against Agent Zero v2.14. Learn more at [you.com](https://you.com/?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme).

## License

MIT

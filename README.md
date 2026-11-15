# You.com Search for Agent Zero

Adds one agent tool, `youcom_search`, next to Agent Zero's built-in SearXNG `search_engine`.
It doesn't change `search_engine`, the bundled SearXNG instance, or any core file. **SearXNG stays the default**; the agent can use either.

- **No key needed.** Calls the [You.com](https://you.com/?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme) keyless endpoint `https://api.you.com/v1/agents/search`. No account, 100 searches a day.
- **Optional key.** Set `YDC_API_KEY` in Agent Zero secrets (or the plugin settings) to use the keyed Search API at `https://ydc-index.io/v1/search`. Get a key at the [You.com platform](https://you.com/platform?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme).
- Returns title, URL and snippet per result, in the same plain-text shape as `search_engine`.
- **Time-scoped search.** An optional `freshness` argument limits results to the past day, week, month or year, or to a date range. `search_engine` has no time filter. Each result shows its page date after the title when You.com has one.
- Past the free 100 a day, the tool says so and (by default) runs the built-in SearXNG search instead.

Requests to You.com send `User-Agent: youdotcom-integration/agent0ai-agent-zero`. Nothing else is sent anywhere.

## Install

Install from the Plugin Hub, or copy this repository to `usr/plugins/youcom_search/` and enable it.

## Time-scoped search

`search_engine` takes a query and nothing else, so a question about this week can come back with pages from last year. `youcom_search` takes an optional `freshness`:

| `freshness` | results from |
| --- | --- |
| `day`, `week`, `month`, `year` | that window, counted back from now |
| `2026-11-01to2026-11-10` | that date range |
| left out | any time (same as before) |

```json
{ "tool_name": "youcom_search", "tool_args": { "query": "open source agent framework release", "freshness": "week" } }
```

```
Example Framework 3.2 released (2026-11-14)
https://example.com/blog/framework-3-2
Release notes for Example Framework 3.2 ...
```

- The date after the title is the page date You.com reports (`page_age`). Results without one are shown as before.
- If a window has no results, the tool says so and shows the next wider window once (day, then week, then month, then year). A date range is exact and is never widened.
- A value You.com would not accept (`fortnight`) returns a one-line error naming the valid values, without spending a search.
- Short forms work too: `d`, `w`, `m`, `y`, `24h`, `7d`, `30d`, `past week`.
- When your query has its own time words ("this week") and you also set `freshness`, You.com uses the wider of the two. Keep time words out of the query.
- The SearXNG fallback is not time-filtered (Agent Zero's SearXNG helper takes a query only). The tool labels it that way.

## Settings

| key | default | meaning |
| --- | --- | --- |
| `api_key` | `""` | optional; otherwise `YDC_API_KEY` from secrets/env; otherwise keyless |
| `results` | `10` | max results |
| `timeout` | `15` | HTTP timeout (s) |
| `fallback_to_searxng` | `true` | use SearXNG when the free limit is hit |
| `show_dates` | `true` | show the page date after each title when known |
| `widen_freshness` | `true` | when a `freshness` window is empty, try the next wider window once (one more search) |

## Remove

Disable it in the Plugin Hub or delete `usr/plugins/youcom_search/`. It leaves nothing outside its own folder.

## Development

Dev-only files (tests, pytest config, dev requirements) live in `dev/`, outside the plugin's runtime layout.

```
pip install -r dev/requirements-dev.txt
pytest -c dev/pytest.ini                 # mocked HTTP
YDC_LIVE=1 pytest -c dev/pytest.ini      # also runs two live keyless smoke tests
```

Tested against Agent Zero v2.14. Learn more at [you.com](https://you.com/?utm_source=agent0ai-agent-zero&utm_medium=oss_integration&utm_campaign=2026-10-oss-integrations&utm_content=plugin-readme).

## License

MIT

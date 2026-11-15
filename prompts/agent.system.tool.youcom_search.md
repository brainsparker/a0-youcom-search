### youcom_search
web search via You.com. returns title, url and snippet per result, with the page date after the title when known.
use when search_engine returns nothing or errors, when results must be recent, or when the user asks for You.com.
works without a key (100 searches a day); past that limit it says so and falls back to SearXNG.
args: `query`, `freshness` (optional)

freshness limits results to a time window. search_engine cannot do this.
- `day`, `week`, `month`, `year`, or a date range `YYYY-MM-DDtoYYYY-MM-DD`
- use it for news, prices, releases, outages, anything where an old page would be a wrong answer
- leave it out for definitions, how-tos, history
- keep time words ("today", "this week", "latest") out of `query` when you set freshness; the wider of the two wins
- if the window has no results, the tool says so and shows the next wider window

usage:
~~~json
{
    "thoughts": ["The user wants this week's news, so results older than a week would be wrong."],
    "headline": "Searching recent news with You.com",
    "tool_name": "youcom_search",
    "tool_args": {
        "query": "open source agent framework release",
        "freshness": "week"
    }
}
~~~

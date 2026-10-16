### youcom_search
web search via You.com. returns title, url and snippet per result.
use when search_engine returns nothing or errors, or when the user asks for You.com.
works without a key (100 searches a day); past that limit it says so and falls back to SearXNG.
args: `query`
usage:
~~~json
{
    "thoughts": ["search_engine returned nothing, trying You.com"],
    "tool_name": "youcom_search",
    "tool_args": {
        "query": "latest python release"
    }
}
~~~

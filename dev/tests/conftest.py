"""Test setup: load plugin modules without an Agent Zero checkout.

Agent Zero modules the tool imports (helpers.tool, helpers.plugins, ...) are
stubbed in sys.modules here, in tests only. The plugin itself uses normal
usr.plugins.youcom_search imports, as Agent Zero requires.
"""
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pkg(name):
    mod = sys.modules.get(name) or types.ModuleType(name)
    mod.__path__ = []
    sys.modules[name] = mod
    return mod


client = _load("usr.plugins.youcom_search.helpers.youcom_client", ROOT / "helpers" / "youcom_client.py")
for p in ("usr", "usr.plugins", "usr.plugins.youcom_search", "usr.plugins.youcom_search.helpers"):
    _pkg(p)
sys.modules["usr.plugins.youcom_search.helpers"].youcom_client = client

# --- Agent Zero stubs ---
_pkg("helpers")


class Response:
    def __init__(self, message, break_loop, **kw):
        self.message, self.break_loop = message, break_loop


class Tool:
    def __init__(self, agent=None, **kw):
        self.agent = agent


tool_mod = types.ModuleType("helpers.tool"); tool_mod.Tool, tool_mod.Response = Tool, Response
errors_mod = types.ModuleType("helpers.errors"); errors_mod.handle_error = lambda e: None
plugins_mod = types.ModuleType("helpers.plugins"); plugins_mod.CONFIG = {}
plugins_mod.get_plugin_config = lambda name, agent=None, **kw: dict(plugins_mod.CONFIG)
searxng_mod = types.ModuleType("helpers.searxng")


async def _searxng(q):
    return {"results": [{"title": "SX", "url": "https://sx.example", "content": "from searxng"}]}


searxng_mod.search = _searxng
secrets_mod = types.ModuleType("helpers.secrets")
secrets_mod.SECRETS = {}
secrets_mod.get_secrets_manager = lambda ctx=None: types.SimpleNamespace(load_secrets=lambda: dict(secrets_mod.SECRETS))
for n, m in {"helpers.tool": tool_mod, "helpers.errors": errors_mod, "helpers.plugins": plugins_mod,
             "helpers.searxng": searxng_mod, "helpers.secrets": secrets_mod}.items():
    sys.modules[n] = m
    setattr(sys.modules["helpers"], n.split(".")[1], m)

tool = _load("usr.plugins.youcom_search.tools.youcom_search", ROOT / "tools" / "youcom_search.py")

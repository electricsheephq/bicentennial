"""The Hermes config and worker environment (R12 Decisions 4 and 6). Every model route points at the director on
loopback with a placeholder key; the run layout is fresh and isolated, never the user's own Hermes home."""

import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.director.core import AUX_TASKS

PLACEHOLDER_KEY = "placeholder-not-a-key"
T1_TOOLSETS = ("memory", "session_search", "todo")  # PREREG-v0-completion line 27
HERMES_TOOLSETS = T1_TOOLSETS + ("terminal",)
CONTEXT_LENGTH = 65536  # the pin refuses a custom-provider window below 64,000 tokens (agent_init.py 2043-2083)
THRESHOLD_TOKENS = 16384  # C-5: W = 16K, so compaction fires at W through the absolute threshold
SHIM = Path(__file__).resolve().with_name("clockshim")
_PLUGIN = re.compile(r"[a-z0-9][a-z0-9_-]*")
_PASSED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")  # copied when set; nothing else is inherited
_PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")
# Disclosed harness deviations from Hermes's defaults, beyond routing (recorded in the adapter's harness record)
# Main window also overrides Hermes's default: the loopback custom provider has a 64,000-token floor.
CONFIG_DEVIATIONS = ("model.context_length", "auxiliary.compression.context_length", "agent.environment_probe")
# Scripted-tier deviations, written by the T1 adapter only. #191: the pin defers session_search and every plug-in and
# MCP tool behind its tool_call bridge (hermes_cli/config_defaults.py tools.tool_search; tools/tool_search.py
# is_deferrable_tool_name), so scripted write and recall turns would not find their tools. #192: the logical clock
# freezes time.time() inside a turn, and the pin's retry and auto-recovery waits loop on it
# (agent/turn_recovery.py interruptible_backoff_sleep), so a failed main call would stall until the turn timeout.
SCRIPTED_DEVIATIONS = ("tools.tool_search.enabled", "agent.api_max_retries", "agent.auto_recovery_cycles")
_SCRIPTED_AGENT = {"api_max_retries": 1, "auto_recovery_cycles": 0}
# Hermes d923a5e: hermes_cli/fallback_config.py:get_fallback_chain, agent/auxiliary_client.py route readers,
# and hermes_cli/config_providers.py:get_compatible_custom_providers (named providers and endpoint/key settings).
# Same pin: agent/curator.py:_resolve_review_runtime reads legacy curator.auxiliary;
# tools/delegate_tool_config.py:_load_config reads top-level delegation routes.
_OWNED_ROUTE_KEYS = {"model", "auxiliary", "fallback_providers", "fallback_model", "providers",
                     "custom_providers", "moa", "curator", "delegation", "context", "plugins"}


def hermes_config(port: int, alias: str, *, plugin: str | None = None, plugin_config: dict | None = None,
                  memory: bool = True, toolsets=T1_TOOLSETS, mcp_servers=None, window=None,
                  context_engine: str | None = None, plugins_enabled: tuple = (),
                  scripted: bool = False) -> dict:
    if window is not None and (type(window) is not int or window < THRESHOLD_TOKENS):
        raise ValueError("window must be an int of at least 16384")
    if type(port) is not int or not 0 < port < 65536 or not isinstance(alias, str) or not alias:
        raise ValueError("a port and an alias are required")
    if plugin is not None and (not isinstance(plugin, str) or not _PLUGIN.fullmatch(plugin)):
        raise ValueError("a memory plug-in is named by ^[a-z0-9][a-z0-9_-]*$")
    if context_engine is not None and (not isinstance(context_engine, str)
            or not _PLUGIN.fullmatch(context_engine) or context_engine == "compressor"):
        raise ValueError("invalid context engine")
    if type(plugins_enabled) is not tuple or any(not isinstance(d, str) or not _PLUGIN.fullmatch(d)
                                               for d in plugins_enabled):
        raise ValueError("invalid enabled plug-in directories")
    if type(memory) is not bool:
        raise ValueError("memory is a bool")
    if type(scripted) is not bool:
        raise ValueError("scripted is a bool")
    if type(toolsets) is not tuple or any(type(t) is not str or not re.fullmatch(r"[a-z0-9_-]+", t) for t in toolsets):
        raise ValueError("toolsets must be a tuple of toolset names")
    if not memory and (plugin is not None or plugin_config or context_engine is not None or plugins_enabled):
        raise ValueError("a memory plug-in or plugin_config requires memory enabled")
    base = f"http://127.0.0.1:{port}"
    aux = {t: {"provider": "auto", "model": "bicentennial-summariser" if t == "compression"
               else f"bicentennial-aux-{t}", "base_url": f"{base}/aux/{t}/v1", "api_key": PLACEHOLDER_KEY}
           for t in AUX_TASKS}
    # Deviation: on a loopback base URL the pin's compression check probes an Ollama-style /api/show, which the
    # director refuses as unknown; a remote provider would give the length from model metadata instead
    # (conversation_compression.py 2075-2084; model_metadata.py 2239-2241 returns a configured value first)
    aux["compression"]["context_length"] = CONTEXT_LENGTH
    cfg = {"model": {"default": alias, "provider": "custom", "base_url": f"{base}/main/v1",
                      "api_key": PLACEHOLDER_KEY, "context_length": CONTEXT_LENGTH},
            "auxiliary": aux,
            "memory": {"memory_enabled": True, "user_profile_enabled": True, "provider": plugin or ""},
            "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
            "updates": {"check": False}, "auth": {"adopt_external_logins": False},
            # Deviation: the toolchain probe is warmed off-thread, so the system prompt's toolchain line depends on
            # timing, and it fingerprints the machine (agent_init.py 1417-1427)
            "agent": {"environment_probe": False},
            "platform_toolsets": {"acp": list(toolsets)},
            "compression": {"enabled": True, "threshold_tokens": THRESHOLD_TOKENS, "micro_compact": False}}
    if context_engine is not None:
        cfg["context"] = {"engine": context_engine}
    if plugins_enabled:
        cfg["plugins"] = {"enabled": list(plugins_enabled)}
    if scripted:
        cfg["tools"] = {"tool_search": {"enabled": "off"}}
        cfg["agent"].update(_SCRIPTED_AGENT)
    if plugin_config is not None:
        if not isinstance(plugin_config, dict):
            raise ValueError("plugin_config must be a dict")
        if _OWNED_ROUTE_KEYS & plugin_config.keys():
            raise ValueError("plugin_config touches adapter-owned routes")
        if ((isinstance(plugin_config.get("tools"), dict) and "tool_search" in plugin_config["tools"])
                or (isinstance(plugin_config.get("agent"), dict) and _SCRIPTED_AGENT.keys() & plugin_config["agent"].keys())):
            raise ValueError("plugin_config touches adapter-owned scripted settings")
        _merge_plugin(cfg, plugin_config)
    if not memory:
        cfg["memory"] = {"memory_enabled": False, "user_profile_enabled": False, "provider": ""}
        cfg["platform_toolsets"] = {"acp": [t for t in toolsets if t not in ("memory", "session_search")]}
    if mcp_servers is not None:
        cfg["mcp_servers"] = deepcopy(mcp_servers)
    if window is not None:
        cfg["compression"]["threshold_tokens"] = window
        cfg["model"]["context_length"] = cfg["auxiliary"]["compression"]["context_length"] = 4 * window
    canon(cfg)  # preserve the canonical, no-float contract for plug-in settings too
    return cfg


def _merge_plugin(target, settings):
    for key, value in settings.items():
        if key in {"temperature", "top_p", "top_k", "mcp_servers"}:
            raise ValueError("plugin_config touches adapter-owned protocol settings")
        if key in target and not (isinstance(target[key], dict) and isinstance(value, dict)):
            raise ValueError("plugin_config touches an adapter-owned key")
        if isinstance(value, dict):
            _merge_plugin(target.setdefault(key, {}), value)
        else:
            target[key] = deepcopy(value)


def write_config(hermes_home, cfg: dict) -> Path:
    """config.yaml as canonical JSON (JSON is YAML), written atomically."""
    path = Path(hermes_home) / "config.yaml"
    fd, name = tempfile.mkstemp(prefix=".config.yaml.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canon(cfg) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


def layout(root, scratch) -> dict:
    """Create the run's directories under root; refuse the user's Hermes home, a reused home or a stray root."""
    root, scratch, user = Path(root).resolve(), Path(scratch).resolve(), Path.home() / ".hermes"
    if root.is_relative_to(user) or root.is_relative_to(user.resolve()):
        raise ValueError("the run root is inside the user's Hermes home")
    if root == scratch or not root.is_relative_to(scratch):
        raise ValueError("the run root is not inside the scratch directory")
    paths = {"root": root, "hermes_home": root / "hermes-home", "home": root / "home",
             "workspace": root / "workspace", "logs": root / "logs", "tmp": root / "tmp"}
    validate_paths(paths)
    if paths["hermes_home"].exists():
        raise ValueError("hermes-home exists: every run starts from fresh directories")
    paths["hermes_home"].mkdir(parents=True)
    for key in ("home", "workspace", "logs", "tmp"):
        paths[key].mkdir(exist_ok=True)
    return paths


def validate_paths(paths: dict) -> None:
    root = paths["root"].resolve()
    for key in ("tmp", "workspace", "home", "hermes_home", "logs"):
        path = paths[key]
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"{key} is a symlink or resolves outside the run root")


def worker_env(paths: dict, port: int, clock_path, checkout, extra=None) -> dict:
    """Built from an allowlist, never a filtered copy: no inherited provider key or credential reaches Hermes."""
    env = {k: os.environ[k] for k in _PASSED if k in os.environ}
    env.update(HERMES_HOME=str(paths["hermes_home"]), HOME=str(paths["home"]), TMPDIR=str(paths["tmp"]),
               PYTHONPATH=os.pathsep.join([str(SHIM)] + ([str(Path(checkout).resolve())] if checkout else [])),
               BICENTENNIAL_CLOCK_FILE=str(Path(clock_path).resolve()), PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1",
               HERMES_DISABLE_LAZY_INSTALLS="1", HERMES_ACP_SKIP_CONFIGURED_MCP="1",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
               **dict.fromkeys(_PROXIES, f"http://127.0.0.1:{port}"))
    env.update(extra or {})
    return env

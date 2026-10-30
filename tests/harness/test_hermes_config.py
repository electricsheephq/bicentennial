"""R12 acceptance: the Hermes config writer, the isolated layout and the allowlisted worker environment."""

import os
from pathlib import Path

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.director.core import AUX_TASKS
from bicentennial.harness.hermes import config
from bicentennial.harness.hermes.config import (
    hermes_config,
    layout,
    worker_env,
    write_config,
)

KEY = "placeholder-not-a-key"


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


def test_exact_values_at_port_4321():
    cfg = hermes_config(4321, "bicentennial-main")
    assert len(AUX_TASKS) == 18 and set(cfg["auxiliary"]) == set(AUX_TASKS)
    aux = {t: {"provider": "auto", "model": f"bicentennial-aux-{t}", "api_key": KEY,
               "base_url": f"http://127.0.0.1:4321/aux/{t}/v1"} for t in AUX_TASKS}
    aux["compression"].update(model="bicentennial-summariser", context_length=65536)  # no /api/show probe
    assert cfg == {
        "model": {"default": "bicentennial-main", "provider": "custom", "base_url": "http://127.0.0.1:4321/main/v1",
                  "api_key": KEY, "context_length": 65536},
        "auxiliary": aux,
        "memory": {"memory_enabled": True, "user_profile_enabled": True, "provider": ""},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
        "updates": {"check": False},
        "auth": {"adopt_external_logins": False},
        "agent": {"environment_probe": False},
        "platform_toolsets": {"acp": ["memory", "session_search", "todo"]},
        "compression": {"enabled": True, "threshold_tokens": 16384, "micro_compact": False},
    }
    assert (config.PLACEHOLDER_KEY, config.T1_TOOLSETS) == (KEY, ("memory", "session_search", "todo"))
    assert (config.CONTEXT_LENGTH, config.THRESHOLD_TOKENS) == (65536, 16384)
    canon(cfg)  # no float at any depth
    assert not {"temperature", "top_p", "top_k", "mcp_servers"} & set(keys(cfg))


def test_scripted_switch():
    # #191 and #192: only the scripted tier's adapter writes these settings; the default output is unchanged
    default = hermes_config(4321, "bicentennial-main")
    assert "tools" not in default and default["agent"] == {"environment_probe": False}
    on = hermes_config(4321, "bicentennial-main", scripted=True)
    assert on["tools"] == {"tool_search": {"enabled": "off"}}
    assert on["agent"] == {"environment_probe": False, "api_max_retries": 1, "auto_recovery_cycles": 0}
    assert {k: v for k, v in on.items() if k not in ("tools", "agent")} == {
        k: v for k, v in default.items() if k != "agent"}
    assert config.SCRIPTED_DEVIATIONS == (
        "tools.tool_search.enabled", "agent.api_max_retries", "agent.auto_recovery_cycles")
    merged = hermes_config(4321, "bicentennial-main", scripted=True, plugin="holographic",
                           plugin_config={"tools": {"fixture": {"depth": 1}}, "agent": {"fixture": 2}})
    assert merged["tools"] == {"tool_search": {"enabled": "off"}, "fixture": {"depth": 1}}
    assert merged["agent"]["fixture"] == 2 and merged["agent"]["api_max_retries"] == 1
    for flag in (False, True):
        for owned in ({"tools": {"tool_search": {"enabled": "on"}}}, {"agent": {"api_max_retries": 3}},
                      {"agent": {"auto_recovery_cycles": 5}}):
            with pytest.raises(ValueError, match="scripted settings"):
                hermes_config(4321, "bicentennial-main", scripted=flag, plugin="holographic", plugin_config=owned)
    with pytest.raises(ValueError, match="adapter-owned key"):
        hermes_config(4321, "bicentennial-main", scripted=True, plugin="holographic", plugin_config={"tools": "on"})
    for bad in (0, 1, "on", None):
        with pytest.raises(ValueError, match="^scripted is a bool$"):
            hermes_config(4321, "bicentennial-main", scripted=bad)


def test_plugin_by_name_only():
    assert hermes_config(4321, "bicentennial-main", plugin="holographic")["memory"]["provider"] == "holographic"
    for bad in ("Bad Name", "-x", "", "a\n", "a/b"):
        with pytest.raises(ValueError):
            hermes_config(4321, "bicentennial-main", plugin=bad)


def test_window_matches_base_golden_and_sets_full_threshold():
    default = hermes_config(1234, "bicentennial-main")
    assert sha256_canon(default) == "c6e1612d6953ce9be177a81aca16f024efedfcd584e51dbfe6e1d0f47d843d9d"
    assert canon(default) == canon(hermes_config(1234, "bicentennial-main", window=None))
    full = hermes_config(1234, "bicentennial-main", window=131072)
    assert full["compression"]["threshold_tokens"] == 131072
    assert full["model"]["context_length"] == full["auxiliary"]["compression"]["context_length"] == 524288
    for bad in (True, 0, 16383, "131072", 131072.0):
        with pytest.raises(ValueError, match="^window must be an int of at least 16384$"):
            hermes_config(1234, "bicentennial-main", window=bad)


@pytest.mark.parametrize("memory", [True, False])
def test_window_combines_with_toolsets_and_mcp_servers(memory):
    toolsets = config.HERMES_TOOLSETS + ("envserver",)
    servers = {"envserver": {"command": "python"}}
    base = hermes_config(4321, "main", memory=memory, toolsets=toolsets, mcp_servers=servers)
    assert canon(base) == canon(hermes_config(4321, "main", memory=memory, toolsets=toolsets,
                                            mcp_servers=servers, window=None))
    full = hermes_config(4321, "main", memory=memory, toolsets=toolsets, mcp_servers=servers, window=131072)
    base["compression"]["threshold_tokens"] = 131072
    base["model"]["context_length"] = base["auxiliary"]["compression"]["context_length"] = 524288
    assert full == base


def test_written_bytes_are_canonical_and_repeatable(tmp_path):
    cfg = hermes_config(4321, "bicentennial-swap")
    path = write_config(tmp_path, cfg)
    first = path.read_bytes()
    write_config(tmp_path, hermes_config(4321, "bicentennial-swap"))
    assert first == path.read_bytes() == canon(cfg) + b"\n"
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]  # no temporary file left behind


def test_worker_env_is_the_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "planted-provider-key")
    monkeypatch.setenv("LANG", "C.UTF-8")
    paths = layout(tmp_path / "root", tmp_path)
    env = worker_env(paths, 4321, tmp_path / "root" / "clock.json", tmp_path / "checkout")
    passed = {k for k in ("PATH", "LANG", "LC_ALL", "LC_CTYPE") if k in os.environ}
    proxy, local = "http://127.0.0.1:4321", "127.0.0.1,localhost"
    assert env == {**{k: os.environ[k] for k in passed},
                   "HERMES_HOME": str(paths["hermes_home"]), "HOME": str(paths["home"]), "TMPDIR": str(paths["tmp"]),
                   "PYTHONPATH": os.pathsep.join([str(config.SHIM), str((tmp_path / "checkout").resolve())]),
                   "BICENTENNIAL_CLOCK_FILE": str(tmp_path / "root" / "clock.json"), "PYTHONHASHSEED": "0",
                   "PYTHONDONTWRITEBYTECODE": "1", "HERMES_DISABLE_LAZY_INSTALLS": "1",
                   "HERMES_ACP_SKIP_CONFIGURED_MCP": "1", "HTTP_PROXY": proxy, "HTTPS_PROXY": proxy,
                   "ALL_PROXY": proxy, "http_proxy": proxy, "https_proxy": proxy, "NO_PROXY": local,
                   "no_proxy": local}
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(config.SHIM) and (config.SHIM / "sitecustomize.py").exists()
    assert "OPENAI_API_KEY" not in env
    assert Path(env["TMPDIR"]).is_dir() and Path(env["TMPDIR"]).is_relative_to(paths["root"])  # not the host's temp


def test_layout_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    with pytest.raises(ValueError, match="Hermes home"):
        layout(tmp_path / "user" / ".hermes" / "run", tmp_path)
    paths = layout(tmp_path / "run", tmp_path)
    assert paths["root"] == (tmp_path / "run").resolve() and all(p.is_dir() for p in paths.values())
    with pytest.raises(ValueError, match="fresh"):
        layout(tmp_path / "run", tmp_path)
    with pytest.raises(ValueError, match="scratch"):
        layout(tmp_path / "elsewhere", tmp_path / "run")


def test_mcp_servers_get_the_discovery_bound():
    # #71: the pin waits 1.5 s for MCP discovery by default and appends a late server's tools after the built-ins
    assert (config.MCP_DEVIATIONS, config.MCP_DISCOVERY_TIMEOUT_S) == (("mcp_discovery_timeout",), 60)
    servers = {"envserver": {"command": "python"}}
    cfg = hermes_config(4321, "main", toolsets=config.HERMES_TOOLSETS + ("envserver",), mcp_servers=servers)
    assert cfg["mcp_discovery_timeout"] == 60 and type(cfg["mcp_discovery_timeout"]) is int
    assert "mcp_discovery_timeout" not in hermes_config(4321, "main")
    with pytest.raises(ValueError, match="protocol settings"):
        hermes_config(4321, "main", plugin="holographic", plugin_config={"mcp_discovery_timeout": 1},
                      mcp_servers=servers)


def test_custom_toolsets_keep_actions_without_memory():
    from bicentennial.harness.hermes.config import HERMES_TOOLSETS

    assert canon(hermes_config(4321, "main")) == canon(hermes_config(4321, "main", toolsets=config.T1_TOOLSETS))
    toolsets = HERMES_TOOLSETS + ("envserver",)
    cfg = hermes_config(4321, "main", toolsets=toolsets, memory=False, mcp_servers={"envserver": {"command": "python"}})
    assert cfg["platform_toolsets"]["acp"] == ["todo", "terminal", "envserver"]
    assert cfg["mcp_servers"] == {"envserver": {"command": "python"}}
    for bad in (["todo"], ("Bad",), ("",), (1,)):
        with pytest.raises(ValueError, match="toolsets"):
            hermes_config(4321, "main", toolsets=bad)

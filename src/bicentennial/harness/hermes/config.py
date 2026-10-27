"""The Hermes config and worker environment (R12 Decisions 4 and 6). Every model route points at the director on
loopback with a placeholder key; the run layout is fresh and isolated, never the user's own Hermes home."""

import os
import re
import tempfile
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.director.core import AUX_TASKS

PLACEHOLDER_KEY = "placeholder-not-a-key"
T1_TOOLSETS = ("memory", "session_search", "todo")  # PREREG-v0-completion line 27
CONTEXT_LENGTH = 65536  # the pin refuses a custom-provider window below 64,000 tokens (agent_init.py 2043-2083)
THRESHOLD_TOKENS = 16384  # C-5: W = 16K, so compaction fires at W through the absolute threshold
SHIM = Path(__file__).resolve().with_name("clockshim")
_PLUGIN = re.compile(r"[a-z0-9][a-z0-9_-]*")
_PASSED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")  # copied when set; nothing else is inherited
_PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")
# Disclosed harness deviations from Hermes's defaults, beyond routing (recorded in the adapter's harness record)
CONFIG_DEVIATIONS = ("auxiliary.compression.context_length", "agent.environment_probe")


def hermes_config(port: int, alias: str, *, plugin: str | None = None) -> dict:
    if type(port) is not int or not 0 < port < 65536 or not isinstance(alias, str) or not alias:
        raise ValueError("a port and an alias are required")
    if plugin is not None and (not isinstance(plugin, str) or not _PLUGIN.fullmatch(plugin)):
        raise ValueError("a memory plug-in is named by ^[a-z0-9][a-z0-9_-]*$")
    base = f"http://127.0.0.1:{port}"
    aux = {t: {"provider": "auto", "model": "bicentennial-summariser" if t == "compression"
               else f"bicentennial-aux-{t}", "base_url": f"{base}/aux/{t}/v1", "api_key": PLACEHOLDER_KEY}
           for t in AUX_TASKS}
    # Deviation: on a loopback base URL the pin's compression check probes an Ollama-style /api/show, which the
    # director refuses as unknown; a remote provider would give the length from model metadata instead
    # (conversation_compression.py 2075-2084; model_metadata.py 2239-2241 returns a configured value first)
    aux["compression"]["context_length"] = CONTEXT_LENGTH
    return {"model": {"default": alias, "provider": "custom", "base_url": f"{base}/main/v1",
                      "api_key": PLACEHOLDER_KEY, "context_length": CONTEXT_LENGTH},
            "auxiliary": aux,
            "memory": {"memory_enabled": True, "user_profile_enabled": True, "provider": plugin or ""},
            "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
            "updates": {"check": False}, "auth": {"adopt_external_logins": False},
            # Deviation: the toolchain probe is warmed off-thread, so the system prompt's toolchain line depends on
            # timing, and it fingerprints the machine (agent_init.py 1417-1427)
            "agent": {"environment_probe": False},
            "platform_toolsets": {"acp": list(T1_TOOLSETS)},
            "compression": {"enabled": True, "threshold_tokens": THRESHOLD_TOKENS, "micro_compact": False}}


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
    if paths["hermes_home"].exists():
        raise ValueError("hermes-home exists: every run starts from fresh directories")
    paths["hermes_home"].mkdir(parents=True)
    for key in ("home", "workspace", "logs", "tmp"):
        paths[key].mkdir(exist_ok=True)
    return paths


def worker_env(paths: dict, port: int, clock_path, checkout) -> dict:
    """Built from an allowlist, never a filtered copy: no inherited provider key or credential reaches Hermes."""
    env = {k: os.environ[k] for k in _PASSED if k in os.environ}
    env.update(HERMES_HOME=str(paths["hermes_home"]), HOME=str(paths["home"]), TMPDIR=str(paths["tmp"]),
               PYTHONPATH=os.pathsep.join([str(SHIM)] + ([str(Path(checkout).resolve())] if checkout else [])),
               BICENTENNIAL_CLOCK_FILE=str(clock_path), PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1",
               HERMES_DISABLE_LAZY_INSTALLS="1", HERMES_ACP_SKIP_CONFIGURED_MCP="1",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
               **dict.fromkeys(_PROXIES, f"http://127.0.0.1:{port}"))
    return env

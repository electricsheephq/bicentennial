"""Finite, offline worker for lifecycle failures; its child only writes a heartbeat."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

mode, root = sys.argv[1], Path(sys.argv[2])


def publish(name, text):
    # Write, then rename into place, so a reader never sees the file empty (#262).
    (root / f"{name}.tmp").write_text(text)
    os.replace(root / f"{name}.tmp", root / name)


publish("pid", str(os.getpid()))
if mode == "tree":
    child = subprocess.Popen([sys.executable, "-c", """
import sys, time
with open(sys.argv[1], 'ab', buffering=0) as out:
    for _ in range(1000):
        out.write(b'.')
        time.sleep(0.01)
""", str(root / "heartbeat")])
    publish("child", str(child.pid))
if mode == "stall-startup":
    time.sleep(2)
    sys.exit(0)
if mode in ("malformed", "invalid-ready"):
    print("not-json" if mode == "malformed" else "[1]", flush=True)
    time.sleep(2)
    sys.exit(0)
print(json.dumps({"ready": True}), flush=True)
if mode == "exit-after-ready":
    sys.exit(0)
for line in sys.stdin:
    cmd = json.loads(line)
    if mode == "stall-" + cmd["op"]:
        # Includes a partial UTF-8 character, with no newline: readability is not a complete reply.
        os.write(sys.stdout.fileno(), b'{"partial":"\xe2')
        time.sleep(2)
        break
    print(json.dumps({"ok": True}), flush=True)
    if cmd["op"] == "end":
        break

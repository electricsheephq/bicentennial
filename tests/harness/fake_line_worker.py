"""Finite control-line double: pipes only, no Hermes or sockets."""

import json
import sys

phase, reply = sys.argv[1:]
if phase == "startup":
    print(reply, flush=True)
else:
    print('{"ready": true}', flush=True)
    for line in sys.stdin:
        op = json.loads(line)["op"]
        if op == phase:
            print(reply, flush=True)
            break
        print(json.dumps({"ok": True, "session_id": "fake-session", "history": 0,
                          "final": "", "alive_threads": [], "active_memory_providers": ["holographic"]}),
              flush=True)

# Let the parent end this child after it has read the reply. An already-exited Darwin group requires a ps scan,
# which this socket-free sandbox cannot perform; that separate lifecycle path is covered by the existing tests.
sys.stdin.read()

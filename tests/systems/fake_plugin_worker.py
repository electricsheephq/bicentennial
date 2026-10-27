"""Recorded provider tools behind the R12 worker protocol; standard library only."""

import http.client
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

HOME = Path(os.environ["HERMES_HOME"])
SANDBOX = Path(os.environ["HOME"])
CFG = json.loads((HOME / "config.yaml").read_bytes())
PROVIDER = CFG["memory"]["provider"]
SCHEMAS = json.loads((Path(__file__).parents[1] / "fixtures/systems/tool-schemas.json").read_bytes())
TOOLS = [{"type": "function", "function": t} for t in [
    *({"name": n, "parameters": {"type": "object", "properties": {}}}
      for n in ("memory", "session_search", "todo")), *SCHEMAS["tools"][PROVIDER]]]
MEM0 = json.loads((HOME / "mem0.json").read_bytes()) if PROVIDER == "mem0" else None


def emit(obj):
    print(json.dumps(obj), flush=True)


def post(base, path, body, *, refused=False):
    url = urlsplit(base)
    assert url.hostname == "127.0.0.1"  # every child-process connection is guarded too
    conn = http.client.HTTPConnection("127.0.0.1", url.port, timeout=60)
    conn.request("POST", path if refused else url.path + path, json.dumps(body), {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    if refused:
        assert resp.status == 403
        return None
    assert resp.status == 200, (resp.status, data)
    return json.loads(data)


def chat(messages):
    model = CFG["model"]
    return post(model["base_url"], "/chat/completions", {
        "model": model["default"], "messages": messages, "tools": TOOLS})["choices"][0]["message"]


def embedding(content):
    cfg = MEM0["oss"]["embedder"]["config"]
    return post(cfg["openai_base_url"], "/embeddings", {"model": cfg["model"], "input": [content],
                "dimensions": 1536, "encoding_format": "float"})["data"][0]["embedding"]


def saved(content, vector=None):
    directory = SANDBOX / ".mem0" if MEM0 else HOME
    directory.mkdir(exist_ok=True)
    with sqlite3.connect(directory / ("history.db" if MEM0 else "memory_store.db")) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS facts(event TEXT, content TEXT)")
        con.execute("INSERT INTO facts VALUES ('ADD', ?)", (content,))
    if MEM0:
        vectors = directory / "qdrant"
        vectors.mkdir(exist_ok=True)
        with (vectors / "vectors.jsonl").open("a") as stream:
            stream.write(json.dumps({"text": content, "vector": vector}) + "\n")


def extract(messages):
    cfg = MEM0["oss"]["llm"]["config"]
    text = post(cfg["openai_base_url"], "/chat/completions", {"model": cfg["model"], "messages": messages,
                "response_format": {"type": "json_object"}})["choices"][0]["message"]["content"]
    return json.loads(text)


def sync(user, assistant):
    facts = extract([{"role": "system", "content": "Extract facts"},
                     {"role": "user", "content": f"Input:\nuser: {user}\nassistant: {assistant}"}])["facts"]
    vectors = [embedding(f) for f in facts]
    with sqlite3.connect(SANDBOX / ".mem0" / "history.db") as con:
        old = [{"id": str(i), "text": r[0]} for i, r in enumerate(con.execute("SELECT content FROM facts"))]
    updated = extract([{"role": "user", "content": json.dumps(old) + "\nNew facts:\n" + json.dumps(facts)}])
    for row in updated["memory"]:
        assert row["event"] == "ADD"
        saved(row["text"], vectors[int(row["id"])])


def main():
    store = HOME / "fake-sessions"
    store.mkdir(exist_ok=True)
    emit({"ready": True})
    history, sid, path = [], None, None
    for line in sys.stdin:
        cmd = json.loads(line)
        if cmd["op"] == "open":
            sid = cmd["session_id"] or str(uuid.uuid4())
            path = store / f"{sid}.json"
            history = json.loads(path.read_bytes()) if path.exists() else []
            emit({"ok": cmd["session_id"] is None or path.exists(), "session_id": sid,
                  "history": len(history), "active_memory_providers": [PROVIDER]})
            env = HOME / ".env"
            if MEM0 and (not env.exists() or env.read_bytes() != b"MEM0_TELEMETRY=false\n"):
                post(CFG["model"]["base_url"], "https://telemetry.invalid/track", {}, refused=True)
            if (HOME / ".fake-stray").exists():
                (SANDBOX / "stray").write_text("undeclared")
            if (HOME / ".fake-tmp-stray").exists():
                (Path(os.environ["TMPDIR"]) / "stray").write_text("undeclared")
        elif cmd["op"] == "turn":
            system = {"role": "system", "content": f"fake harness; cwd {cmd.get('cwd', os.getcwd())}; home {HOME}"}
            turn = [{"role": "user", "content": cmd["text"]}]
            msg = chat([system, *history, *turn])
            while msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    args = json.loads(call["function"]["arguments"])
                    assert call["function"]["name"] == ("mem0_add" if MEM0 else "fact_store")
                    saved(args["content"], embedding(args["content"]) if MEM0 else None)
                turn += [{"role": "assistant", "content": "", "tool_calls": msg["tool_calls"]},
                         *({"role": "tool", "tool_call_id": c["id"], "content": "saved"} for c in msg["tool_calls"])]
                msg = chat([system, *history, *turn])
            history += [*turn, {"role": "assistant", "content": msg["content"]}]
            path.write_text(json.dumps(history))
            if MEM0:
                sync(cmd["text"], msg["content"])
            emit({"ok": True, "final": msg["content"], "history": len(history)})
        elif cmd["op"] == "end":
            override = HOME / ".fake-end"
            emit({"ok": True, **(json.loads(override.read_bytes()) if override.exists() else {"alive_threads": []})})
            break


if __name__ == "__main__":
    main()

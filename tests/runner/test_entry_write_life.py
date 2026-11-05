"""An outside provider's scripted write turns through a complete fake-worker life."""

import json
import sys
from pathlib import Path

import test_life_fake as fake
import test_outside_entry as entries

from bicentennial.systems import mapping, pins, registry

lives = fake.lives
harness = fake.harness
outside = entries.outside
source = entries.source


def test_outside_scripted_write_life(lives, outside, source, tmp_path, harness):
    outside.update(write_tools=[dict(tool=name, actions=[]) for name in ("entry_store", "entry_remove")],
                   read_tools=["entry_search"], fresh_install_hash=registry.ZERO_HASH)
    outside["artifact"]["sha256"] = pins.archive_hash(source, ("HEAD",))
    outside["recipe"].update(file_time_sites=[], worker_environment={},
        write=dict(tool="entry_store", fixed={}, content_key="content"),
        forget=dict(search_tool="entry_search", search_fixed=dict(whole=True), query_key="query",
            listing_key="results", text_key="content", id_key="id", delete_tool="entry_remove",
            delete_fixed={}, delete_key="memory_id"))
    assert registry.outside_reasons(outside) == []
    assert mapping.check_mapping(outside, mapping.resolve_mapping(outside)) is None
    case = lives["t1-g1", "B0"]
    result = fake.drive(case, tmp_path / "run", entry=outside, plugin_source=source,
        worker_argv=[sys.executable, str(Path(__file__).with_name("fake_entry_write_worker.py")),
                     "--timeline", str(case["timeline"])])
    try:
        assert result.stopped is None
        assert result.audit["status"] == "OK"
        assert result.audit["failures"] == ["A4.no_effects_hook"]
        assert len(result.results) == len(case["items"])
        turns = {(session["index"], turn["n"]): turn["user"]
                 for session in case["compiled"].script["sessions"] for turn in session["turns"]}
        writes = [row for row in result.records if row.get("served") == "write_tool_calls"]
        assert writes
        for row in writes:
            assert row["write_turn_readback"] is True
            body = json.loads(fake.blobs(result).get(row["resp"]))
            calls = body["choices"][0]["message"]["tool_calls"]
            assert len(calls) == 1
            function = calls[0]["function"]
            assert function["name"] == "entry_store"
            assert json.loads(function["arguments"]) == dict(content=turns[
                row["cursor"]["session"], row["cursor"]["turn"]])
    finally:
        result.cleanup()

"""Observable recipe effects captured before the resolver refactor.

Every value was captured on the unmodified base. Five of them carry a run lock, which pins the hash of the packs
the fixtures build. Those packs hold SQLite world databases. A SQLite library that turns secure_delete on by
default (Ubuntu's, which CI's Python links) zeroes freed space inside their pages, so their bytes and hash differ
from a library that leaves it off (#327). Those five values are therefore recorded per build in BUILDS. A
build with other pack hashes fails until its values are captured on the base.
"""

import json
import sqlite3
import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import test_compare as comparison
import test_t0 as zero

from bicentennial.canon import sha256_canon
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.harness.hermes import plugin_host as host
from bicentennial.harness.hermes.config import hermes_config, layout
from bicentennial.runner import t0, t1
from bicentennial.runtime.clock import SimClock
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems.registry import REGISTRY, SystemRefused, load

EXPECTED = {'calls:hermes-native': '62a006e01509dd2eb04e956f2dae50a416b06d0f111ef2a5fba9e2b6dd51a5a4',
 'calls:holographic': '79de831208c43625a810ad77e26d723957c658660e230e2ee19cbef51ddc366b',
 'calls:mem0-oss': '70449588609bf70f1d9840f321892ea5ff7a65a49082fea3db13de35651b1ee1',
 'calls:omega': '40cb7e62d582bfb57d4afa1781bb2c1f248e7977200379c674cd7424b1d6f468',
 'config:hermes-native': 'a412531bd88e93cd0bd4f0de77869de2c819dd9c5374528c69cd850367254f29',
 'config:holographic': '7aae579fcf7632513872a00bfd4f8a164cc61eb5b4681c9e913b0190dc47776b',
 'config:mem0-oss': 'b77fa8258a51f47a1666a865d07175ccdcb1d2da3e01b7da7aea45960378918b',
 'config:omega': '440c3ac7e1bfc7752883cbc4a34c348bb0786162be3a8211afcfe499d3799523',
 'install:holographic': 'f158f668cc29bd89119d3348898a2b15b9dd924507a85e3f65b73c16f5d4f43b',
 'install:mem0-oss': 'eee7616d2d56caed7ea5c01fb764731f6b956c4d23d54da66ed50ad2319f5bb5',
 'install:omega': '2e2d2e74b4166a39bb0a8f47aa67d7363e7c6dddab0ef33e184694d51026ff72'}

# The five values that carry a run lock, per build of the fixtures' packs, keyed by their (T0, T1) pack hashes.
BUILDS = {
    # SQLite with secure_delete off by default (macOS and uv's Python)
    ('d5fb7f8953cd009e6d5304644540a91ded7bf8a468b2fba2b954392a77e41482',
     '475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7'): (
        {'effects': {'hermes-native': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                                       'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                       't0': '6ca2a2b050776398f38cda9dbc61f9b749df73489ea943945cdec475505144d2',
                                       't1': '199ec8dc319fdf55abff054ac543a85ddf9eb366fb7d7884eda97f730cca8f74',
                                       'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                                       'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'holographic': {'config': '6ad0309e7ec1495bfd850a4402248930d70eecd36d16ef34a6c1f5e2f5e20389',
                                     'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                     't0': '54e302c97dee646b5ba3976508e42a734c226a9692fd34c3d19143faa1dd7e4d',
                                     't1': '1413c29ed7081d7a373980ac698dafd0a69ccbb6af1fa9a92ac4835b6959c92c',
                                     'tree': '321fbd170cc856ba6639a1e0dc901830d5fdf38aa4364b990b9501d5c3cb0834',
                                     'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'lcm-x': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                               'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                               't0': 'd08c02a08401fb77149dbe6e57dac5d8f814126174ab5a19df5d02db1605f214',
                               't1': 'd08c02a08401fb77149dbe6e57dac5d8f814126174ab5a19df5d02db1605f214',
                               'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                               'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'mem0-oss': {'config': '6f5ba59657108040e58a31bbdd318973fb3f8e677d6ccbbfc27c398195e07250',
                                  'settle': '8cc7a555bd5de26952939f74ba6a477b50226ec5fd62c640c099197d28a70274',
                                  't0': '7a4947355eedd2f46f2b3bdc45b164310cb7ef0f397a9242a644ddaaf8ca6482',
                                  't1': 'a2cca1ea65ece69a1cf90d00d44a97ae9af8414a230114b6578674538045456c',
                                  'tree': 'e5571d16fd1b90dcf4bea9fbfe461b12e5b9d45dc6e23a154e013ec574562603',
                                  'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'no-memory': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                                   'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                   't0': 'b01e27578c4c48d5c3f254068144fd632fbf6d3280fbb3b3c32ec4022ea5ab97',
                                   't1': 'b01e27578c4c48d5c3f254068144fd632fbf6d3280fbb3b3c32ec4022ea5ab97',
                                   'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                                   'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'omega': {'config': 'e9c31704eb56f8edfbce2f2532c788933a5cc3da0a03559fc439fade5bea4920',
                               'settle': '493e0b668e1564572b8b3276e22fba02efca89e3433e77fb9ea16ec018776dbe',
                               't0': '2675c5e0a8a5cb67eb62b59b64bff7993869074618f49b9bcdc06ba7c3910ac0',
                               't1': 'c83229f7ea983312db96ad51824f8ea09c1c0d44651a7d89d1c12a9f6f377517',
                               'tree': '46b7c6ab3fa7cb8273a10a78fef5ca560ea12eb1a3446bb54c91b739f48b95fa',
                               'worker_env': '0083b11b24784aafb435f032414bd5c00cf0417f7d556d5adef388d9c98fa53e'}},
         'reference_t0_cards': '8231fddf86a547c9bd2382ddcf62235fac8f6d869d3ff735ba49375ca094271b',
         'replayed_plugin': 'b51fafd5b734195277de7593084c4f2e0602b87a125c2a2b28408a85e2b674ab',
         't0_cards': 'a3e07d3d99af09d9d2a5bb126e5cb99e04ad4e83c6755998449e19c43bfe2ad5',
         't1_cards_root_free': '785bf07c6ac5ef7d7e82c421406ff173ff0521306adfa80b0c3d0757b1671fc7'}),
    # SQLite with secure_delete on by default (Ubuntu's SQLite 3.45.1, which CI's Python links)
    ('07391f82fe36ea8cb5b531deed23045b47f38ed2151ccc523c75f9426344da32',
     'bb1292c62cf2a00a801d9751a1d273fa0c4a2a1d672c2369a090941f0379e2f3'): (
        {'effects': {'hermes-native': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                                       'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                       't0': '5559770694385ea1e468aa701b011468212a37f1fd42973574edbcc9ffa07522',
                                       't1': '2d216ef84d31f6f37778a5562d43f573f8d67e5cdc532f29638d366e7193efe6',
                                       'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                                       'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'holographic': {'config': '6ad0309e7ec1495bfd850a4402248930d70eecd36d16ef34a6c1f5e2f5e20389',
                                     'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                     't0': '62e161495dfe565dadad85af53c2567619ca508f6c15c69118cb14cb96752bc7',
                                     't1': 'e665e211de72cd0ba3c08302b2af02e88da1f14358e11b331949e069b042b50c',
                                     'tree': '321fbd170cc856ba6639a1e0dc901830d5fdf38aa4364b990b9501d5c3cb0834',
                                     'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'lcm-x': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                               'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                               't0': 'd08c02a08401fb77149dbe6e57dac5d8f814126174ab5a19df5d02db1605f214',
                               't1': 'd08c02a08401fb77149dbe6e57dac5d8f814126174ab5a19df5d02db1605f214',
                               'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                               'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'mem0-oss': {'config': '6f5ba59657108040e58a31bbdd318973fb3f8e677d6ccbbfc27c398195e07250',
                                  'settle': '8cc7a555bd5de26952939f74ba6a477b50226ec5fd62c640c099197d28a70274',
                                  't0': 'b14efc63fe7bd170dba20de0e544866f1791734ed6ed9920cbf631f05053da1b',
                                  't1': '7881570f5039354a2858a11e8e9f284fde253c79c5fa9906176e794df3f2feed',
                                  'tree': 'e5571d16fd1b90dcf4bea9fbfe461b12e5b9d45dc6e23a154e013ec574562603',
                                  'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'no-memory': {'config': '07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a',
                                   'settle': '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
                                   't0': 'b01e27578c4c48d5c3f254068144fd632fbf6d3280fbb3b3c32ec4022ea5ab97',
                                   't1': 'b01e27578c4c48d5c3f254068144fd632fbf6d3280fbb3b3c32ec4022ea5ab97',
                                   'tree': '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b',
                                   'worker_env': '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'},
                     'omega': {'config': 'e9c31704eb56f8edfbce2f2532c788933a5cc3da0a03559fc439fade5bea4920',
                               'settle': '493e0b668e1564572b8b3276e22fba02efca89e3433e77fb9ea16ec018776dbe',
                               't0': 'a40a073b60cae2d10e62b414476e7c5b83275ba85bff30391310690fedecda9c',
                               't1': 'b9a74b03f7d82805dc582e7fe69b90805649cf7de48ee9e2909d2c695c957040',
                               'tree': '46b7c6ab3fa7cb8273a10a78fef5ca560ea12eb1a3446bb54c91b739f48b95fa',
                               'worker_env': '0083b11b24784aafb435f032414bd5c00cf0417f7d556d5adef388d9c98fa53e'}},
         'reference_t0_cards': 'ed02deb976fd278b4e2edfb8558607d73ac4ddd24d31f006dcc3c9826638344a',
         'replayed_plugin': 'be756fcb40122755e827ba93020767a2c60d0c31cb7d2474434d3ae6c8634cff',
         't0_cards': '49280210f580021e8112ec8ac7104b1ef19c9ff6ffa405c671f484f4810c7541',
         't1_cards_root_free': '8a99133cd8139800f6f3e1373a85d5e7dd43c7c2c43f307e1401a3395159d7ee'}),
}

# Reuse the existing offline installations and card paths.
installed = comparison.installed
cases = comparison.cases
policy = comparison.policy
replay = comparison.replay
synth = comparison.synth
environment = comparison.environment
completed = comparison.completed
synthetic_egress = comparison.synthetic_egress
extra_rows = zero.extra_rows
stub_hosts = zero.stub_hosts


@pytest.fixture(scope="module", autouse=True)
def fixed_commit():
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("BICENTENNIAL_OPERATOR", raising=False)
        patch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
        patch.setattr(t0, "_commit", lambda: "f" * 40)
        patch.setattr(t1, "_commit", lambda: "f" * 40)
        yield


@pytest.fixture(scope="module")
def t0_installed(tmp_path_factory, extra_rows):
    yield from zero.installed.__wrapped__(tmp_path_factory, extra_rows)


@pytest.fixture(scope="module")
def built(t0_installed, installed):
    """The lock-bearing values recorded for this build of the fixtures' packs; none for a build not recorded."""
    key = (t0_installed[2], installed.digest)
    if key not in BUILDS:
        db = sqlite3.connect(":memory:")
        secure_delete = db.execute("PRAGMA secure_delete").fetchone()[0]
        db.close()
        print("recipe_build=" + json.dumps(dict(t0=key[0], t1=key[1], sqlite=sqlite3.sqlite_version,
                                                secure_delete=secure_delete)))
    return BUILDS.get(key, {})


def golden(key, value, built=None):
    expected = EXPECTED if built is None else built
    digest = ({name: {field: sha256_canon(item) for field, item in fields.items()}
               for name, fields in value.items()} if key == "effects" else
              sha256(value).hexdigest() if isinstance(value, bytes) else sha256_canon(value))
    if expected.get(key) != digest:
        print("recipe_capture=" + json.dumps({key: digest}, sort_keys=True))
    assert expected.get(key) == digest, (key, digest)


def test_recipe_effects(t0_installed, installed, built, monkeypatch, tmp_path):
    monkeypatch.delenv("BICENTENNIAL_OPERATOR", raising=False)
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    for module in (t0, t1):
        monkeypatch.setattr(module, "read_marker", lambda: NS(exit=0))
        monkeypatch.setattr(module, "admit", lambda *a, **k: NS(admitted=True, max_roots=2))
    cache = tmp_path / "cache"
    cache.mkdir()
    values = {}
    for path in sorted(REGISTRY.glob("*.toml")):
        entry = load(path)
        name = entry["name"]
        data = dict(config=hermes_config(4321, "bicentennial-main", plugin=hp.PROVIDERS.get(name),
            context_engine=hp.ENGINES.get(name),
            plugins_enabled=(hp.plugin_dir(name),) if name in hp.ENABLED else ()),
            worker_env=hp.resolve_worker_env(name, Path("model-cache")),
            tree=list(hp.TREES[name]) if name in hp.TREES else None,
            settle=list(host.SETTLE_THREADS.get(name, ())))
        for tier, module in (("t0", t0), ("t1", t1)):
            try:
                kwargs = dict(system=name, entry=entry, hermes=tmp_path, plugin_source=tmp_path,
                              model_cache=cache if name == "omega" else None)
                if tier == "t0":
                    prepared = module._preflight(**kwargs, packs=t0_installed[0], selected=["all"],
                        pack_hash=t0_installed[2], host_overrides={"worker_argv": []})
                    locks = [module._lock(prepared[0], pack, entry, t0_installed[2], True)
                             for pack in prepared[1]]
                else:
                    ctx = module.prepare(**kwargs, packs=installed.root, pack_hash=installed.digest,
                                         worker_argv=[])
                    locks = [ctx.lock]
                data[tier] = dict(verdict="admitted", locks=locks)
            except (SystemRefused, t0.T0Refused, t1.T1Refused) as error:
                data[tier] = dict(verdict=list(error.reasons) if isinstance(error, SystemRefused)
                                 else error.code)
        values[name] = data
    golden("effects", values, built)


@pytest.mark.parametrize("name", tuple(host.FORGET))
def test_host_calls(name, tmp_path, monkeypatch):
    entry = load(REGISTRY / f"{name}.toml")
    obj = object.__new__(host.HermesMemoryHost)
    obj.entry, obj.name = entry, name
    obj.paths = layout(tmp_path / "run", tmp_path)
    obj.server = NS(port=4321)
    obj.director = NS(route={"alias": "bicentennial-main"})
    obj.clock = SimClock(tmp_path / "clock.json", 1_600_000_000, 60)
    obj.argv, obj.checkout, obj.egress, obj.extra_env = [], None, None, None
    obj._worker, obj.pids, obj.gate, obj.session, obj.latency_ms = None, [], [], 1, 0
    obj.events, obj.turn, obj.write_clipped, obj.sim_epoch_s = {}, 0, 0, 1_600_000_000
    obj.forget_kept, obj.forget_kept_texts, obj._forget_deleted = {}, {}, set()
    obj._store_generation = 0
    calls = []

    class Worker:
        proc = NS(pid=1)

        def __init__(self, *args):
            pass

        def call(self, **kwargs):
            calls.append(kwargs)
            return dict(ok=True, active_memory_providers=list(hp.PROVIDERS.values()), schemas=[])

    monkeypatch.setattr(host, "_Worker", Worker)
    monkeypatch.setattr(host, "read_marker", lambda: NS(exit=0, state="idle"))
    monkeypatch.setattr(host, "admit", lambda *a, **k: NS(admitted=True))
    monkeypatch.setattr(host, "assert_niced", lambda pid: None)
    obj._start()
    config = (obj.paths["hermes_home"] / "config.yaml").read_bytes()
    if name == "hermes-native":
        assert calls[0]["provider"] == ""
    obj.ingest(dict(event_id="e1", t_sim=1, kind="message", actor="user", text="quartz"))
    obj._worker = None
    row = host.FORGET[name]
    searched = False

    def call(kind, **kwargs):
        nonlocal searched
        calls.append(dict(call=kind, **kwargs))
        result = {} if searched else {row[3]: [{row[4]: "quartz", row[5]: "row1"}]}
        searched = True
        return {"result": json.dumps(result)}

    obj._call = call
    obj.forget(dict(event_ids=["e1"]))
    golden("calls:" + name, calls)
    golden("config:" + name, config)


def test_t0_card(t0_installed, built, tmp_path, stub_hosts):
    options, created, denied = stub_hosts
    out = tmp_path / "out"
    zero.run(t0_installed, out, **options())
    if denied:
        raise denied[0]
    assert created
    golden("t0_cards", {p: sha256(v).hexdigest() for p, v in zero.stable_files(out).items()
                        if p.endswith("card.json")}, built)


def root_free(raw):
    """A T1 card without the two values that depend on the length of its sandbox root's path.

    RING0 §4 claims byte-identical cards per machine, where the fixed root never moves. Here the
    root lives under the session's temporary directory, so each citation's context offset and the
    masked ledger digest move with that path's length between sessions.
    """
    card = json.loads(raw)
    card["masked_ledger_digest"] = "-"
    for item in card["items"]:
        citation = (item.get("envelope") or {}).get("citation")
        if citation:
            citation["context_offset"] = 0
    return card


def test_t1_card(completed, built):
    golden("t1_cards_root_free", {arm: root_free((completed.root / "one" / arm / "card.json").read_bytes())
                                  for arm in comparison.compare.GATED}, built)


def test_t0_route_hash():
    assert route_table_hash(RouteTable.load(t0.ROUTE_TABLE)) == (
        "7c34dc452feec849111831603ac6caec7521b3eb46aef7705c15d365b30b917f")


def test_replayed_plugin_card(synth, installed, built, monkeypatch, tmp_path):
    ctx = replace(synth.ctx, entry=comparison.measured("holographic"), plugin_source=tmp_path / "plugin")
    run = replace(synth, ctx=ctx)
    monkeypatch.setattr(t1, "prepare", lambda **kw: ctx)
    monkeypatch.setattr(t1, "check_install", lambda *a: None)
    comparison.set_run(monkeypatch, run)
    out = tmp_path / "out"
    assert comparison.invoke(installed, out, system="holographic", entry=ctx.entry,
                             plugin_source=ctx.plugin_source) == 0
    golden("replayed_plugin", dict(
        cards={arm: (out / arm / "card.json").read_bytes().hex() for arm in comparison.compare.GATED},
        properties={arm: comparison.properties(out, arm) for arm in comparison.compare.GATED}), built)


@pytest.mark.parametrize("name", tuple(hp.TREES))
def test_plugin_install(name, tmp_path, monkeypatch, git_checkouts):
    source = tmp_path / "source"
    source.mkdir()
    tree = hp.TREES[name]
    target = source / tree[1] if len(tree) > 1 else source
    target.mkdir(parents=True, exist_ok=True)
    (target / "provider.py").write_text("# synthetic provider\n")
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", *tree],
                             check=True, capture_output=True).stdout
    entry = load(REGISTRY / f"{name}.toml")
    entry["artifact"]["sha256"] = sha256(archive).hexdigest()
    entry["fresh_install_hash"] = "0" * 64
    paths = layout(tmp_path / "run", tmp_path)
    adapter = NS(paths=paths, director=NS(run_values={"director_port": "4321"},
                                        control=lambda: {"inflight": 0}), end_threads=())
    calls = []
    original = subprocess.Popen

    def popen(argv, **kwargs):
        if argv[:3] == ["git", "-C", str(source)]:
            calls.append(argv[3:])
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    cell = hp.PluginCell(entry, adapter)
    cell.install(source, alias="bicentennial-main")
    result = cell.settle()
    value = dict(calls=calls, config=(paths["hermes_home"] / "config.yaml").read_bytes().hex(),
                 settle=[result.kind, result.settled, result.polls, result.reason])
    if name in host.SETTLE_THREADS:
        adapter.end_threads = host.SETTLE_THREADS[name]
        result = cell.settle()
        value["cut"] = [result.kind, result.settled, result.polls, result.reason]
    golden("install:" + name, value)


def test_route_copies():
    for path in sorted(REGISTRY.glob("*.toml")):
        name = load(path)["name"]
        inline = {"routes": [dict(system=name, segment=s, probe_model="probe-model",
            summariser="summary-model", alias=a, vision=None, served_by="scripted")
            for s, a in (("seg0", "bicentennial-main"), ("seg1", "bicentennial-swap"))]}
        assert route_table_hash(RouteTable.load(inline)) == route_table_hash(RouteTable.load(t1._routes(name)))
        pin_row = dict(system=name, segment="seg0", probe_model="probe-model",
            alias="bicentennial-main", summariser="summary-model", vision=None, served_by="scripted")
        assert pin_row == t1._routes(name)["routes"][0]


def test_reference_t0_cards(t0_installed, built, tmp_path):
    out = tmp_path / "out"
    assert zero.run(t0_installed, out) == 0
    golden("reference_t0_cards", {p: sha256(v).hexdigest() for p, v in zero.stable_files(out).items()
                                  if p.endswith("card.json")}, built)

"""Per-item surface callers share the existing eviction and diagnostics lock."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, RLock

import pytest

from bicentennial import surface_cache
from bicentennial.harness.hermes import adapter, plugin_host
from bicentennial.runner import kept, life
from bicentennial.sandbox import surfaces
from bicentennial.systems import controls, hermes_plugin


@pytest.mark.parametrize("caller,mode", [(adapter, "hash"), (plugin_host, "hash"), (hermes_plugin, "hash"),
                                        (controls, "hash"), (plugin_host, "verify"), (hermes_plugin, "verify"),
                                        (controls, "verify"), (plugin_host, "changed"), (hermes_plugin, "changed"),
                                        (controls, "changed")])
def test_per_item_callers_forced_eviction(tmp_path, monkeypatch, caller, mode):
    paused, resume, contention = Event(), Event(), Event()
    guard = Lock()
    iterations = 0

    class ObservedLock:
        def __init__(self):
            self.lock, self.calls = RLock(), 0

        def __enter__(self):
            with guard:
                self.calls += 1
                if self.calls == 2:
                    contention.set()
                    resume.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    class Listings(dict):
        def __iter__(self):
            nonlocal iterations
            victim = next(super().__iter__())
            with guard:
                iterations += 1
                first = iterations == 1
            if first:
                paused.set()
                assert resume.wait(5)
            return iter([victim])

        def __delitem__(self, key):
            super().__delitem__(key)
            resume.set()

    trees = [tmp_path / str(i) for i in range(2)]
    for i, tree in enumerate(trees):
        tree.mkdir()
        (tree / "value").write_text(str(i))
    expected = [surfaces.install_hash(tree, [], 1234) for tree in trees]
    listings = {str(i): {} for i in range(128)}
    if mode == "changed":
        # The cached baselines sit last, so the forced eviction removes a filler entry, never a baseline.
        listings = {str(i): {} for i in range(126)}
        listings.update({digest: {row["path"]: row for row in surfaces.tree_listing(tree, [])}
                         for digest, tree in zip(expected, trees, strict=True)})
        for i, tree in enumerate(trees):
            (tree / "value").write_text(f"changed {i}")
    monkeypatch.setattr(surface_cache, "LOCK", ObservedLock())
    monkeypatch.setattr(surfaces, "_LISTINGS", Listings(listings))

    def access(n):
        if mode == "changed":
            with pytest.raises(surfaces.NotEmpty) as raised:
                caller.verify_empty(trees[n], [], expected[n])
            assert raised.value.paths == ("value",) and raised.value.paths_known
        elif mode == "verify":
            caller.verify_empty(trees[n], [], expected[n])
        else:
            assert caller.surface_hash(trees[n], []) == expected[n]

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(access, 0)
        assert paused.wait(5)
        second = pool.submit(access, 1)
        second.result(timeout=10)
        first.result(timeout=10)
    assert contention.is_set() and len(surfaces._LISTINGS) == 128


def test_direct_clone_and_install_hash_never_access_listings(tmp_path, monkeypatch):
    class NoCache(dict):
        def _fail(self, *args, **kwargs):
            pytest.fail("unexpected listing cache access")

        __setitem__ = __getitem__ = __delitem__ = __contains__ = __iter__ = __len__ = _fail
        get = pop = popitem = setdefault = update = clear = keys = items = values = copy = _fail

    monkeypatch.setattr(surfaces, "_LISTINGS", NoCache())
    source = tmp_path / "source"
    source.mkdir()
    (source / "value").write_text("before")
    for n, caller in enumerate((life, kept, plugin_host, hermes_plugin)):
        caller.clone_tree(source, tmp_path / str(n))
        assert caller.install_hash(source, [], 1234) == surfaces.install_hash(source, [], 1234)

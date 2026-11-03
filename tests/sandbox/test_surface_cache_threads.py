"""Unpinned callers serialize the listing cache, including eviction and diagnostic reads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, RLock

import pytest

from bicentennial import surface_cache
from bicentennial.harness.hermes import adapter, plugin_host
from bicentennial.sandbox import surfaces
from bicentennial.systems import controls, hermes_plugin

CALLERS = (adapter, plugin_host, controls, hermes_plugin)


def test_all_callers_share_wrappers_and_parallel_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(surfaces, "_LISTINGS", {})
    trees = []
    for i in range(160):
        tree = tmp_path / str(i)
        tree.mkdir()
        (tree / "value").write_text(str(i))
        trees.append(tree)
    expected = [surfaces.surface_hash(p, []) for p in trees]
    for caller in CALLERS:
        assert caller.surface_hash is surface_cache.surface_hash
        if caller is not adapter:
            assert caller.verify_empty is surface_cache.verify_empty
    with ThreadPoolExecutor(8) as pool:
        actual = list(pool.map(lambda pair: CALLERS[pair[0] % len(CALLERS)].surface_hash(pair[1], []),
                               enumerate(trees)))
    assert actual == expected
    assert len(surfaces._LISTINGS) == 128
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda pair: CALLERS[1 + pair[0] % 3].verify_empty(pair[1], [], expected[pair[0]]),
                      enumerate(trees)))


@pytest.mark.parametrize("wrapped", [False, True])
def test_forced_eviction_interleaving(tmp_path, monkeypatch, wrapped):
    paused, resume, contention = Event(), Event(), Event()
    guard = Lock()
    iterations = 0

    class ObservedLock:
        def __init__(self):
            self.lock = RLock()
            self.calls = 0

        def __enter__(self):
            with guard:
                self.calls += 1
                if self.calls == 2:
                    # The second wrapper reached the lock while the first eviction was paused.
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
            # Without serialization, both evictions choose the same oldest entry.
            return iter([victim])

        def __delitem__(self, key):
            super().__delitem__(key)
            resume.set()

    monkeypatch.setattr(surface_cache, "LOCK", ObservedLock())
    monkeypatch.setattr(surfaces, "_LISTINGS", Listings({str(i): {} for i in range(128)}))
    trees = [tmp_path / str(i) for i in range(2)]
    for i, tree in enumerate(trees):
        tree.mkdir()
        (tree / "value").write_text(str(i))
    hashing = adapter.surface_hash if wrapped else surfaces.surface_hash
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(hashing, trees[0], [])
        assert paused.wait(5)
        second = pool.submit(hashing, trees[1], [])
        second.result(timeout=10)
        if wrapped:
            first.result(timeout=10)
            assert contention.is_set()
        else:
            with pytest.raises(KeyError):
                first.result(timeout=10)
    if wrapped:
        assert len(surfaces._LISTINGS) == 128

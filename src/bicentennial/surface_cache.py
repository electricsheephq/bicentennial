"""Serialize callers of the pinned surface listing cache within this process."""

from threading import RLock

from bicentennial.sandbox import surfaces

LOCK = RLock()


def surface_hash(*args, **kwargs):
    with LOCK:
        return surfaces.surface_hash(*args, **kwargs)


def verify_empty(*args, **kwargs):
    with LOCK:
        return surfaces.verify_empty(*args, **kwargs)

"""Generator-owned immutable world histories and canonical exports."""

from .bitemporal import as_known as as_known
from .bitemporal import as_valid as as_valid
from .db import create_world as create_world
from .db import open_world as open_world
from .export import export_jsonl as export_jsonl
from .export import export_world as export_world
from .export import world_hash as world_hash


def unit(life: str, process: str, unit_id: str) -> tuple[str, ...]:
    """The sole unit key shape: three nonempty string components, unchanged."""
    if any(type(part) is not str or not part for part in (life, process, unit_id)):
        raise ValueError('unit components must be nonempty strings')
    return life, process, unit_id

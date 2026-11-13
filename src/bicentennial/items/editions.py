"""Template editions: the template set a pack is built from, with one version per template id.

Edition 1 is the v0.1 catalogue. Edition 2 swaps in version two of four templates (#505, #506). v1 and v2 of one
template never meet in one edition, so every lookup keyed by template id stays unambiguous. Each edition has its own
C-7 freeze file; edition 1's is the pinned ``c7-partial.json``.
"""

from bicentennial.items.templates import g1, g2, g2_v2


def _swap(templates, versions):
    by_id = {t.template_id: t for t in versions}
    if len(by_id) != len(versions) or set(by_id) - {t.template_id for t in templates}:
        raise ValueError("an edition swaps each existing template id at most once")
    return tuple(by_id.get(t.template_id, t) for t in templates)


EDITIONS = {
    1: {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES},
    2: {"G1": _swap(g1.TEMPLATES, g1.TEMPLATES_V2), "G2": _swap(g2.TEMPLATES, g2_v2.TEMPLATES_V2)},
}
BY_REF = {t.ref: t for edition in EDITIONS.values() for templates in edition.values() for t in templates}
C7_FILES = {1: "specs/ring0/c7-partial.json", 2: "specs/ring0/c7-edition2.json"}

"""Text-free copy-match and bundle-overlap rows (issue #241, choice 8)."""

from collections.abc import Mapping

from .literal_copy import CopyResult, tertiles


def rows(result: CopyResult, tracks: Mapping[str, str]) -> tuple[dict[str, str | int], ...]:
    """One row per item/triple match, then one overlap row for every bundle.

    tracks maps bundle ids to tracks, as for tertiles(). Copy rows identify one
    item and branch. Bundle overlap rows identify both via item_id_0/1 and
    branch_0/1, ordered by item id. Fractions always use p/q, including 0/1 and
    1/1. Only the explicit metadata below is published, never any source text.
    """
    bins = tertiles(result, tracks)
    output = []
    for bundle in result.bundles:
        first, second = bundle.items
        common = dict(bundle_id=bundle.bundle_id, track=first.track, life=first.life,
                      template_id=first.template_id, template_version=first.template_version,
                      filter="literal_copy")
        if bundle.dropped:
            for item in bundle.items:
                for match in item.matches:
                    output.append(dict(common, item_id=item.item_id, branch=item.branch,
                                       reason="literal_copy", df=match.df, idf=match.idf,
                                       sha256_prefix=match.sha256_prefix))
        overlap = bundle.overlap
        output.append(dict(common, item_id_0=first.item_id, branch_0=first.branch,
                           item_id_1=second.item_id, branch_1=second.branch,
                           reason="overlap", overlap=f"{overlap.numerator}/{overlap.denominator}",
                           tertile=bins[bundle.bundle_id]))
    return tuple(output)

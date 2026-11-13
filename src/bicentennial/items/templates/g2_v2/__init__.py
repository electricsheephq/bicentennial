"""Version-two G2 templates, kept outside g2 so the pinned controls' import closure does not change."""

from .recall_count import RecallCountV2

__all__ = ["TEMPLATES_V2", "RecallCountV2"]

TEMPLATES_V2 = (
    RecallCountV2(template_id="recall-count", version=2, cell_id="RECALL-AGG", kind="qa", twin_type=None,
                  direction="retrieval breadth", semantics="as_known"),
)

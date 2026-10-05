"""Where along a device's edge a clip or tab may stand.

The snap shell's clips and the cradle's tabs both stand in the middle of an
edge, slid along it to the nearest place clear of every feature there, and kept
off the corners, where a rounded outline leaves them nothing to hook. Both use
this, so the two cannot disagree.
"""

from __future__ import annotations

from collections.abc import Sequence

from zcad_core.hardware.wearables.capture import EdgeFeature

# A clip or tab keeps this far from a feature, and this far from where the
# edge's straight run ends.
FEATURE_MARGIN_MM = 1.0
CORNER_KEEPOUT_MM = 2.0
_SLIDE_STEP_MM = 0.5


def edge_reach_mm(
    edge_length_mm: float, span_mm: float, corner_radius_mm: float
) -> float:
    """How far from the middle of an edge the middle of something ``span_mm``
    long may slide: to the end of the edge's straight run, less the keepout."""

    return edge_length_mm / 2 - corner_radius_mm - CORNER_KEEPOUT_MM - span_mm / 2


def clear_offset(
    features: Sequence[EdgeFeature], reach_mm: float, span_mm: float
) -> float | None:
    """The offset nearest the middle, within ``reach_mm`` of it, where something
    ``span_mm`` long clears every feature by the margin; ``None`` if there is
    none. The +X or +Y side comes first at equal distance."""

    def clear(offset: float) -> bool:
        return all(
            abs(offset - feature.center_offset_mm)
            >= (span_mm + feature.width_mm) / 2 + FEATURE_MARGIN_MM
            for feature in features
        )

    for step in range(int(max(reach_mm, 0.0) / _SLIDE_STEP_MM) + 1):
        for offset in (step * _SLIDE_STEP_MM, -step * _SLIDE_STEP_MM):
            if clear(offset):
                return offset

    return None

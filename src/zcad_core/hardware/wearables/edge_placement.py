"""Where along a device's edge a clip or tab may stand.

The snap shell's clips and the cradle's tabs both stand in the middle of an
edge, slid along it to the nearest place clear of every feature there, and kept
off the corners, where a rounded outline leaves them nothing to hook. Both use
this, so the two cannot disagree. A hook over the top face keeps clear of the
face features there by ``FACE_MARGIN_MM``: the cradle refuses a tab whose hook
would cover one, and the snap shell slides its clip clear (:func:`face_keepouts`).
"""

from __future__ import annotations

from collections.abc import Sequence

from zcad_core.hardware.wearables.capture import EdgeFeature, FaceFeature

# A clip or tab keeps this far from a feature, and this far from where the
# edge's straight run ends.
FEATURE_MARGIN_MM = 1.0
CORNER_KEEPOUT_MM = 2.0
# A face feature must stand this far clear of a hook.
FACE_MARGIN_MM = 0.5
_SLIDE_STEP_MM = 0.5


def edge_reach_mm(
    edge_length_mm: float, span_mm: float, corner_radius_mm: float
) -> float:
    """How far from the middle of an edge the middle of something ``span_mm``
    long may slide: to the end of the edge's straight run, less the keepout."""

    return edge_length_mm / 2 - corner_radius_mm - CORNER_KEEPOUT_MM - span_mm / 2


def clear_offset(
    features: Sequence[EdgeFeature],
    reach_mm: float,
    span_mm: float,
    keepouts: Sequence[tuple[float, float]] = (),
) -> float | None:
    """The offset nearest the middle, within ``reach_mm`` of it, where something
    ``span_mm`` long clears every feature by the margin and its middle lies in
    none of the open ``keepouts`` ranges; ``None`` if there is none. The +X or
    +Y side comes first at equal distance."""

    def clear(offset: float) -> bool:
        return all(
            abs(offset - feature.center_offset_mm)
            >= (span_mm + feature.width_mm) / 2 + FEATURE_MARGIN_MM
            for feature in features
        ) and not any(low < offset < high for low, high in keepouts)

    for step in range(int(max(reach_mm, 0.0) / _SLIDE_STEP_MM) + 1):
        for offset in (step * _SLIDE_STEP_MM, -step * _SLIDE_STEP_MM):
            if clear(offset):
                return offset

    return None


def face_keepouts(
    features: Sequence[FaceFeature],
    edge: str,
    *,
    half_length_mm: float,
    half_width_mm: float,
    overhang_mm: float,
    hook_width_mm: float,
    hook_offset_mm: float = 0.0,
) -> list[tuple[FaceFeature, tuple[float, float]]]:
    """Each face feature a hook on ``edge`` could cover, with the open range of
    clip offsets, along the edge as :func:`clear_offset` takes them, where it
    would.

    The hook covers ``overhang_mm`` in from the edge and ``hook_width_mm``
    along it, its middle ``hook_offset_mm`` along the edge from the clip's; a
    feature within ``FACE_MARGIN_MM`` of that is covered. Offsets run +X on
    the north and south edges and +Y on the east and west, as an edge
    feature's do; the device is centred, ``half_length_mm`` along X and
    ``half_width_mm`` along Y."""

    keepouts = []

    for feature in features:
        half_x, half_y = feature.width_mm / 2, feature.depth_mm / 2

        if edge in ("north", "south"):
            across, half_across, along, half_along = (
                feature.center_y_mm,
                half_y,
                feature.center_x_mm,
                half_x,
            )
            edge_mm = half_width_mm
        else:
            across, half_across, along, half_along = (
                feature.center_x_mm,
                half_x,
                feature.center_y_mm,
                half_y,
            )
            edge_mm = half_length_mm

        # How far in from the edge the feature's side nearest it stands, less
        # the margin: under the overhang, the hook covers it.
        outward = 1.0 if edge in ("north", "east") else -1.0

        if edge_mm - (outward * across + half_across) - FACE_MARGIN_MM >= overhang_mm:
            continue

        reach = hook_width_mm / 2 + half_along + FACE_MARGIN_MM
        middle = along - hook_offset_mm
        keepouts.append((feature, (middle - reach, middle + reach)))

    return keepouts

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from zcad_core.geometry.edge_outline import EdgeOutlineAnalyzer
from zcad_core.geometry.types import BoardEdge, EdgeSegment
from zcad_core.retention.edge_backend import EdgeCaptureRequest
from zcad_core.retention.edge_capture import EdgeCaptureLocation, EdgeCapturePolicy
from zcad_core.retention.production_board import (
    ProductionBoardModel,
    import_production_board_model,
)

_EDGE_COORDINATE = {
    BoardEdge.NEGATIVE_X: lambda bounds: bounds.xmin,
    BoardEdge.POSITIVE_X: lambda bounds: bounds.xmax,
    BoardEdge.NEGATIVE_Y: lambda bounds: bounds.ymin,
    BoardEdge.POSITIVE_Y: lambda bounds: bounds.ymax,
}


@dataclass(frozen=True)
class EdgeClearanceResult:
    """Component- and material-clear spans found on one board edge."""

    edge: BoardEdge
    clear_spans: tuple[EdgeSegment, ...]


@dataclass(frozen=True)
class ProductionEdgeDerivation:
    """Evidence-derived edge-capture request and audit results."""

    request: EdgeCaptureRequest
    clearances: tuple[EdgeClearanceResult, ...]
    selected_edge: BoardEdge
    selected_span: EdgeSegment


class ProductionBoardEdgeAdapter:
    """Derive edge-capture input from production STEP evidence.

    Finds edge spans where the PCB itself has continuous material (via
    :class:`~zcad_core.geometry.edge_outline.EdgeOutlineAnalyzer`, which is
    deliberately blind to components) and intersects them with the exact
    component-clear intervals computed from component bounding boxes
    (analogous to
    :meth:`~zcad_core.retention.production_board.ProductionBoardCornerAdapter.analyze_corner_clearance`,
    projected onto edge spans instead of corner squares).
    """

    def __init__(
        self,
        *,
        engagement_depth_mm: float = 2.5,
        vertical_margin_mm: float = 0.10,
        sample_resolution_mm: float = 0.25,
        required_material_ratio: float = 0.995,
        minimum_anchor_separation_mm: float = 6.0,
    ) -> None:
        if engagement_depth_mm <= 0:
            raise ValueError("engagement_depth_mm must be positive")

        if vertical_margin_mm < 0:
            raise ValueError("vertical_margin_mm cannot be negative")

        if minimum_anchor_separation_mm <= 0:
            raise ValueError("minimum_anchor_separation_mm must be positive")

        self._engagement_depth_mm = engagement_depth_mm
        self._vertical_margin_mm = vertical_margin_mm
        self._sample_resolution_mm = sample_resolution_mm
        self._required_material_ratio = required_material_ratio
        self._minimum_anchor_separation_mm = minimum_anchor_separation_mm

    def import_model(
        self,
        *,
        source_step: Path,
        pcb_solid_index: int,
    ) -> ProductionBoardModel:
        """Import a STEP model and identify its PCB solid."""

        return import_production_board_model(
            source_step=source_step,
            pcb_solid_index=pcb_solid_index,
        )

    def analyze_edge_clearance(
        self,
        model: ProductionBoardModel,
        edge: BoardEdge,
        *,
        minimum_span_mm: float,
    ) -> EdgeClearanceResult:
        """Find spans on one edge clear of both material gaps and components."""

        pcb_bounds = model.pcb.BoundingBox()

        analyzer = EdgeOutlineAnalyzer(
            model.pcb,
            engagement_depth_mm=self._engagement_depth_mm,
            sample_resolution_mm=self._sample_resolution_mm,
            required_material_ratio=self._required_material_ratio,
        )
        material_spans = analyzer.candidate_segments(
            edge,
            minimum_length_mm=self._sample_resolution_mm,
        )

        component_clear_spans = self._component_clear_spans(
            model=model,
            edge=edge,
            pcb_bounds=pcb_bounds,
        )

        clear_spans = tuple(
            intersection
            for material_span in material_spans
            for component_span in component_clear_spans
            for intersection in (
                _intersect_edge_segments(
                    material_span,
                    component_span,
                ),
            )
            if intersection is not None and intersection.length_mm >= minimum_span_mm
        )

        return EdgeClearanceResult(
            edge=edge,
            clear_spans=clear_spans,
        )

    def derive(
        self,
        *,
        model: ProductionBoardModel,
        policy: EdgeCapturePolicy,
    ) -> ProductionEdgeDerivation:
        """Derive a two-point edge-capture request from the widest clear span."""

        minimum_span_mm = policy.arm_width_mm + self._minimum_anchor_separation_mm

        clearances = tuple(
            self.analyze_edge_clearance(
                model,
                edge,
                minimum_span_mm=minimum_span_mm,
            )
            for edge in BoardEdge
        )

        candidates = tuple(
            (result.edge, span) for result in clearances for span in result.clear_spans
        )

        if not candidates:
            raise ValueError(
                "Production board does not have a component-clear edge span "
                "wide enough for two spaced capture points"
            )

        edge, span = max(candidates, key=lambda item: item[1].length_mm)

        bounds = model.pcb.BoundingBox()
        edge_coordinate = _EDGE_COORDINATE[edge](bounds)
        margin = policy.arm_width_mm / 2.0

        locations = (
            EdgeCaptureLocation(
                edge=edge,
                position_mm=span.start_mm + margin,
                edge_coordinate_mm=edge_coordinate,
            ),
            EdgeCaptureLocation(
                edge=edge,
                position_mm=span.end_mm - margin,
                edge_coordinate_mm=edge_coordinate,
            ),
        )

        return ProductionEdgeDerivation(
            request=EdgeCaptureRequest(
                board_thickness_mm=bounds.zlen,
                locations=locations,
                policy=policy,
            ),
            clearances=clearances,
            selected_edge=edge,
            selected_span=span,
        )

    def _component_clear_spans(
        self,
        *,
        model: ProductionBoardModel,
        edge: BoardEdge,
        pcb_bounds: cq.BoundBox,
    ) -> tuple[EdgeSegment, ...]:
        lower, upper = _edge_limits(edge, pcb_bounds)
        pcb_top_z = pcb_bounds.zmax
        depth = self._engagement_depth_mm

        blocked: list[tuple[float, float]] = []

        for solid in model.component_solids:
            bounds = solid.BoundingBox()

            if bounds.zmax <= pcb_top_z + self._vertical_margin_mm:
                continue

            along_start, along_end, overlaps_depth = _component_edge_overlap(
                edge=edge,
                bounds=bounds,
                pcb_bounds=pcb_bounds,
                depth=depth,
            )

            if not overlaps_depth:
                continue

            start = max(along_start, lower)
            end = min(along_end, upper)

            if end > start:
                blocked.append((start, end))

        return _complement_intervals(
            blocked,
            lower=lower,
            upper=upper,
            edge=edge,
        )


def _edge_limits(
    edge: BoardEdge,
    pcb_bounds: cq.BoundBox,
) -> tuple[float, float]:
    if edge in (BoardEdge.NEGATIVE_X, BoardEdge.POSITIVE_X):
        return pcb_bounds.ymin, pcb_bounds.ymax

    return pcb_bounds.xmin, pcb_bounds.xmax


def _component_edge_overlap(
    *,
    edge: BoardEdge,
    bounds: cq.BoundBox,
    pcb_bounds: cq.BoundBox,
    depth: float,
) -> tuple[float, float, bool]:
    """Return the component's along-edge projection and whether it reaches
    into the engagement-depth strip on the given edge."""

    if edge is BoardEdge.NEGATIVE_X:
        overlaps = (
            bounds.xmax > pcb_bounds.xmin and bounds.xmin < pcb_bounds.xmin + depth
        )
        return bounds.ymin, bounds.ymax, overlaps

    if edge is BoardEdge.POSITIVE_X:
        overlaps = (
            bounds.xmax > pcb_bounds.xmax - depth and bounds.xmin < pcb_bounds.xmax
        )
        return bounds.ymin, bounds.ymax, overlaps

    if edge is BoardEdge.NEGATIVE_Y:
        overlaps = (
            bounds.ymax > pcb_bounds.ymin and bounds.ymin < pcb_bounds.ymin + depth
        )
        return bounds.xmin, bounds.xmax, overlaps

    overlaps = bounds.ymax > pcb_bounds.ymax - depth and bounds.ymin < pcb_bounds.ymax

    return bounds.xmin, bounds.xmax, overlaps


def _complement_intervals(
    blocked: list[tuple[float, float]],
    *,
    lower: float,
    upper: float,
    edge: BoardEdge,
) -> tuple[EdgeSegment, ...]:
    """Return the spans within [lower, upper] not covered by any blocked interval."""

    if upper <= lower:
        return ()

    if not blocked:
        return (
            EdgeSegment(
                edge=edge,
                start_mm=lower,
                end_mm=upper,
            ),
        )

    merged: list[list[float]] = []

    for start, end in sorted(blocked):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    clear: list[EdgeSegment] = []
    cursor = lower

    for start, end in merged:
        if start > cursor:
            clear.append(
                EdgeSegment(
                    edge=edge,
                    start_mm=cursor,
                    end_mm=min(start, upper),
                )
            )

        cursor = max(cursor, end)

        if cursor >= upper:
            break

    if cursor < upper:
        clear.append(
            EdgeSegment(
                edge=edge,
                start_mm=cursor,
                end_mm=upper,
            )
        )

    return tuple(span for span in clear if span.length_mm > 0)


def _intersect_edge_segments(
    first: EdgeSegment,
    second: EdgeSegment,
) -> EdgeSegment | None:
    if first.edge is not second.edge:
        raise ValueError("Cannot intersect segments from different edges")

    start = max(first.start_mm, second.start_mm)
    end = min(first.end_mm, second.end_mm)

    if end <= start:
        return None

    return EdgeSegment(
        edge=first.edge,
        start_mm=start,
        end_mm=end,
    )

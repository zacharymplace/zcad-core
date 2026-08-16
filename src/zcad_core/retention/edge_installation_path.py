from __future__ import annotations

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_capture import as_edge_capture_parameters
from zcad_core.retention.installation_path import (
    InstallationPathCollision,
    InstallationPathPlan,
    InstallationPathReport,
    InstallationPathResult,
)
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionResult,
)
from zcad_core.retention.synthetic_edge_backend import SyntheticEdgeCaptureBackend

Vector3 = tuple[float, float, float]


def _intersection_volume(
    first: cq.Shape,
    second: cq.Shape,
) -> float:
    intersection = first.intersect(second)

    if intersection.isNull():
        return 0.0

    return float(intersection.Volume())


def _translated_bounds_overlap(
    bounds: cq.BoundBox,
    obstacle_bounds: cq.BoundBox,
    offset_mm: Vector3,
) -> bool:
    x_offset, y_offset, z_offset = offset_mm

    return not (
        bounds.xmax + x_offset < obstacle_bounds.xmin
        or bounds.xmin + x_offset > obstacle_bounds.xmax
        or bounds.ymax + y_offset < obstacle_bounds.ymin
        or bounds.ymin + y_offset > obstacle_bounds.ymax
        or bounds.zmax + z_offset < obstacle_bounds.zmin
        or bounds.zmin + z_offset > obstacle_bounds.zmax
    )


def _moved_shape(
    shape: cq.Shape,
    offset_mm: Vector3,
) -> cq.Shape:
    return shape.moved(cq.Location(cq.Vector(*offset_mm)))


def _edge_normal(
    edge: BoardEdge,
) -> tuple[int, int]:
    return {
        BoardEdge.NEGATIVE_X: (-1, 0),
        BoardEdge.POSITIVE_X: (1, 0),
        BoardEdge.NEGATIVE_Y: (0, -1),
        BoardEdge.POSITIVE_Y: (0, 1),
    }[edge]


def default_edge_installation_path_plans(
    execution: ProductionEdgeExecutionResult,
) -> tuple[InstallationPathPlan, ...]:
    """Build vertical and open-edge rigid paths.

    Edge capture only ever occupies one of the board's four edges (see
    :class:`~zcad_core.retention.production_edge_board.ProductionEdgeDerivation`),
    unlike corner capture which may occupy up to all four corners. The
    three edges without capture geometry are open approach directions,
    mirroring how :func:`~zcad_core.retention.installation_path.default_installation_path_plans`
    treats corners left uncaptured.
    """

    board_bounds = execution.board_model.pcb.BoundingBox()
    parameters = as_edge_capture_parameters(execution.execution.parameters)
    capture = workplane_shape(SyntheticEdgeCaptureBackend().build_geometry(parameters))

    if capture.isNull():
        raise ValueError("Production execution contains no capture geometry")

    capture_bounds = capture.BoundingBox()

    lift_mm = capture_bounds.zmax - board_bounds.zmin + 5.0
    x_travel_mm = board_bounds.xlen + capture_bounds.xlen + 5.0
    y_travel_mm = board_bounds.ylen + capture_bounds.ylen + 5.0

    open_edges = tuple(
        edge for edge in BoardEdge if edge is not execution.derivation.selected_edge
    )

    plans: list[InstallationPathPlan] = [
        InstallationPathPlan(
            name="vertical",
            waypoints_mm=(
                (0.0, 0.0, lift_mm),
                (0.0, 0.0, 0.0),
            ),
        )
    ]

    for edge in open_edges:
        x_sign, y_sign = _edge_normal(edge)
        offset = (
            x_sign * x_travel_mm,
            y_sign * y_travel_mm,
            0.0,
        )
        elevated_offset = (
            offset[0],
            offset[1],
            lift_mm,
        )

        plans.append(
            InstallationPathPlan(
                name=(f"planar_from_{edge.value}"),
                waypoints_mm=(
                    offset,
                    (0.0, 0.0, 0.0),
                ),
            )
        )
        plans.append(
            InstallationPathPlan(
                name=(f"lifted_from_{edge.value}"),
                waypoints_mm=(
                    elevated_offset,
                    (0.0, 0.0, lift_mm),
                    (0.0, 0.0, 0.0),
                ),
            )
        )

    return tuple(plans)


def analyze_edge_installation_paths(
    execution: ProductionEdgeExecutionResult,
    *,
    candidate_id: str,
    plans: (tuple[InstallationPathPlan, ...] | None) = None,
    tolerance_mm3: float = 1e-6,
) -> InstallationPathReport:
    """Sample rigid translations against edge-capture geometry."""

    if not candidate_id.strip():
        raise ValueError("candidate_id cannot be empty")

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    selected_plans = (
        plans if plans is not None else default_edge_installation_path_plans(execution)
    )

    if not selected_plans:
        raise ValueError("At least one installation path is required")

    parameters = as_edge_capture_parameters(execution.execution.parameters)
    capture = workplane_shape(SyntheticEdgeCaptureBackend().build_geometry(parameters))

    if capture.isNull():
        raise ValueError("Production execution contains no capture geometry")

    board_shapes = (
        execution.board_model.pcb,
        *execution.board_model.component_solids,
    )
    board_geometry = tuple(
        (
            shape,
            shape.BoundingBox(),
        )
        for shape in board_shapes
    )
    capture_bounds = capture.BoundingBox()

    results: list[InstallationPathResult] = []

    for plan in selected_plans:
        collisions: list[InstallationPathCollision] = []
        maximum = 0.0
        sample_count = 0

        for segment_index, (
            start,
            end,
        ) in enumerate(
            zip(
                plan.waypoints_mm,
                plan.waypoints_mm[1:],
            )
        ):
            first_sample = 0 if segment_index == 0 else 1

            for sample_index in range(
                first_sample,
                plan.samples_per_segment + 1,
            ):
                fraction = sample_index / plan.samples_per_segment
                offset: Vector3 = (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                    start[2] + (end[2] - start[2]) * fraction,
                )
                volume = sum(
                    _intersection_volume(
                        _moved_shape(
                            shape,
                            offset,
                        ),
                        capture,
                    )
                    for shape, bounds in board_geometry
                    if _translated_bounds_overlap(
                        bounds,
                        capture_bounds,
                        offset,
                    )
                )
                maximum = max(maximum, volume)
                sample_count += 1

                if volume > tolerance_mm3:
                    collisions.append(
                        InstallationPathCollision(
                            segment_index=(segment_index),
                            segment_fraction=round(
                                fraction,
                                6,
                            ),
                            offset_mm=(
                                round(offset[0], 6),
                                round(offset[1], 6),
                                round(offset[2], 6),
                            ),
                            intersection_mm3=round(
                                volume,
                                6,
                            ),
                        )
                    )

        results.append(
            InstallationPathResult(
                name=plan.name,
                passed=not collisions,
                sample_count=sample_count,
                maximum_intersection_mm3=round(
                    maximum,
                    6,
                ),
                collisions=tuple(collisions),
            )
        )

    return InstallationPathReport(
        schema_version="1.0.0",
        candidate_id=candidate_id,
        tolerance_mm3=tolerance_mm3,
        results=tuple(results),
        limitation=(
            "Sampled rigid translations do not model "
            "capture deflection, PCB flex, rotation, "
            "manufacturing tolerance, or hand-guided "
            "installation."
        ),
    )

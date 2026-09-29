from __future__ import annotations

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_capture import as_edge_capture_parameters
from zcad_core.retention.installation_path import (
    InstallationPathPlan,
    InstallationPathReport,
    sample_installation_paths,
)
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionResult,
)
from zcad_core.retention.synthetic_edge_backend import SyntheticEdgeCaptureBackend
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    build_edge_validation_fixture,
)


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
    fixture_policy: ValidationFixturePolicy | None = None,
) -> InstallationPathReport:
    """Sample rigid translations against the printed edge-clip fixture."""

    return sample_installation_paths(
        candidate_id=candidate_id,
        plans=(
            plans
            if plans is not None
            else default_edge_installation_path_plans(execution)
        ),
        pcb=execution.board_model.pcb,
        components=tuple(execution.board_model.component_solids),
        fixture=workplane_shape(
            build_edge_validation_fixture(
                execution, policy=fixture_policy or ValidationFixturePolicy()
            )
        ),
        tolerance_mm3=tolerance_mm3,
    )

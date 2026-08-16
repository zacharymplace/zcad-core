from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.corner_capture import (
    BoardCorner,
    as_corner_capture_parameters,
)
from zcad_core.retention.production_execution import (
    ProductionCornerExecutionResult,
)
from zcad_core.retention.synthetic_backend import (
    SyntheticCornerCaptureBackend,
)

Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class InstallationPathPlan:
    """One sampled rigid-body translation path."""

    name: str
    waypoints_mm: tuple[Vector3, ...]
    samples_per_segment: int = 20

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Installation path name cannot be empty")

        if len(self.waypoints_mm) < 2:
            raise ValueError("Installation path requires at least two waypoints")

        if self.waypoints_mm[-1] != (
            0.0,
            0.0,
            0.0,
        ):
            raise ValueError("Installation path must end at the installed position")

        if self.samples_per_segment < 2:
            raise ValueError("samples_per_segment must be at least 2")


@dataclass(frozen=True)
class InstallationPathCollision:
    """One sampled collision along a path."""

    segment_index: int
    segment_fraction: float
    offset_mm: Vector3
    intersection_mm3: float


@dataclass(frozen=True)
class InstallationPathResult:
    """Collision result for one tested path."""

    name: str
    passed: bool
    sample_count: int
    maximum_intersection_mm3: float
    collisions: tuple[InstallationPathCollision, ...]


@dataclass(frozen=True)
class InstallationPathReport:
    """Bounded rigid-body installation analysis."""

    schema_version: str
    candidate_id: str
    tolerance_mm3: float
    results: tuple[InstallationPathResult, ...]
    limitation: str

    @property
    def rigid_path_verified(self) -> bool:
        """Whether at least one sampled path passed."""

        return any(result.passed for result in self.results)


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


def _corner_signs(
    corner: BoardCorner,
) -> tuple[int, int]:
    return {
        BoardCorner.NEGATIVE_X_NEGATIVE_Y: (
            -1,
            -1,
        ),
        BoardCorner.NEGATIVE_X_POSITIVE_Y: (
            -1,
            1,
        ),
        BoardCorner.POSITIVE_X_NEGATIVE_Y: (
            1,
            -1,
        ),
        BoardCorner.POSITIVE_X_POSITIVE_Y: (
            1,
            1,
        ),
    }[corner]


def default_installation_path_plans(
    execution: ProductionCornerExecutionResult,
) -> tuple[InstallationPathPlan, ...]:
    """Build vertical and open-corner rigid paths."""

    board_bounds = execution.board_model.pcb.BoundingBox()
    parameters = as_corner_capture_parameters(execution.execution.parameters)
    capture = workplane_shape(
        SyntheticCornerCaptureBackend().build_geometry(parameters)
    )

    if capture.isNull():
        raise ValueError("Production execution contains no capture geometry")

    capture_bounds = capture.BoundingBox()

    lift_mm = capture_bounds.zmax - board_bounds.zmin + 5.0
    x_travel_mm = board_bounds.xlen + capture_bounds.xlen + 5.0
    y_travel_mm = board_bounds.ylen + capture_bounds.ylen + 5.0

    selected = set(execution.derivation.selected_corners)
    open_corners = tuple(corner for corner in BoardCorner if corner not in selected)

    plans: list[InstallationPathPlan] = [
        InstallationPathPlan(
            name="vertical",
            waypoints_mm=(
                (0.0, 0.0, lift_mm),
                (0.0, 0.0, 0.0),
            ),
        )
    ]

    for corner in open_corners:
        x_sign, y_sign = _corner_signs(corner)
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
                name=(f"planar_from_{corner.value}"),
                waypoints_mm=(
                    offset,
                    (0.0, 0.0, 0.0),
                ),
            )
        )
        plans.append(
            InstallationPathPlan(
                name=(f"lifted_from_{corner.value}"),
                waypoints_mm=(
                    elevated_offset,
                    (0.0, 0.0, lift_mm),
                    (0.0, 0.0, 0.0),
                ),
            )
        )

    return tuple(plans)


def analyze_installation_paths(
    execution: ProductionCornerExecutionResult,
    *,
    candidate_id: str,
    plans: (tuple[InstallationPathPlan, ...] | None) = None,
    tolerance_mm3: float = 1e-6,
) -> InstallationPathReport:
    """Sample rigid translations against capture geometry."""

    if not candidate_id.strip():
        raise ValueError("candidate_id cannot be empty")

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    selected_plans = (
        plans if plans is not None else default_installation_path_plans(execution)
    )

    if not selected_plans:
        raise ValueError("At least one installation path is required")

    parameters = as_corner_capture_parameters(execution.execution.parameters)
    capture = workplane_shape(
        SyntheticCornerCaptureBackend().build_geometry(parameters)
    )

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


def write_installation_path_report(
    report: InstallationPathReport,
    *,
    output_path: Path,
) -> None:
    """Write an immutable installation-path report."""

    payload = asdict(report)
    payload["rigid_path_verified"] = report.rigid_path_verified
    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")

        if existing == serialized:
            return

        raise FileExistsError(
            f"Refusing to overwrite immutable installation-path report: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )

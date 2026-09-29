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
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    build_validation_fixture,
)

Vector3 = tuple[float, float, float]

INSTALLATION_PATH_SCHEMA_VERSION = "1.1.0"

# The fixture splits at the PCB's underside into captures (above) and base
# (below); this keeps a board resting on the base out of the capture half.
_SPLIT_EPSILON_MM = 1e-3

LIMITATION = (
    "Sampled rigid translations do not model "
    "capture deflection, PCB flex, rotation, "
    "manufacturing tolerance, or hand-guided "
    "installation."
)


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
    # Schema 1.0.0 reports tested the capture geometry alone.
    collision_geometry: str = "capture"

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


def _split_fixture(
    fixture: cq.Shape,
    pcb_bottom: float,
) -> tuple[cq.Shape | None, cq.Shape | None]:
    """Split the fixture at the PCB's underside into (captures, base)."""

    bounds = fixture.BoundingBox()
    split = pcb_bottom + _SPLIT_EPSILON_MM
    halves: list[cq.Shape | None] = []

    for z_min, z_max in ((split, bounds.zmax + 1.0), (bounds.zmin - 1.0, split)):
        if z_max <= z_min:
            halves.append(None)
            continue

        box = cq.Solid.makeBox(
            bounds.xlen + 2.0,
            bounds.ylen + 2.0,
            z_max - z_min,
            pnt=cq.Vector(bounds.xmin - 1.0, bounds.ymin - 1.0, z_min),
        )
        half = fixture.intersect(box)
        halves.append(None if half.isNull() or half.Volume() <= 0 else half)

    return halves[0], halves[1]


def sample_installation_paths(
    *,
    candidate_id: str,
    plans: tuple[InstallationPathPlan, ...],
    pcb: cq.Shape,
    components: tuple[cq.Shape, ...],
    fixture: cq.Shape,
    tolerance_mm3: float,
) -> InstallationPathReport:
    """Sample rigid translations of the board against the printed fixture.

    The whole fixture is an obstacle: captures and walls, and the base with
    its clearance holes, so parts reaching into those holes stop the board
    sliding. A collision is overlap beyond what each part already has when
    seated, so pads resting on the base do not collide by sliding along it.
    Paths never move below the installed position, so only the PCB and
    parts reaching below it are tested against the base.
    """

    if not candidate_id.strip():
        raise ValueError("candidate_id cannot be empty")

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    if not plans:
        raise ValueError("At least one installation path is required")

    if fixture.isNull():
        raise ValueError("Installation analysis needs fixture geometry")

    shapes = (pcb, *components)
    shape_bounds = tuple(shape.BoundingBox() for shape in shapes)
    pcb_bottom = pcb.BoundingBox().zmin
    captures, base = _split_fixture(fixture, pcb_bottom)

    # (obstacle, obstacle bounds, indices of shapes tested against it)
    obstacles: list[tuple[cq.Shape, cq.BoundBox, tuple[int, ...]]] = []

    if captures is not None:
        everything = tuple(range(len(shapes)))
        obstacles.extend(
            (solid, solid.BoundingBox(), everything) for solid in captures.Solids()
        )

    if base is not None:
        reaching_base = tuple(
            index
            for index, bounds in enumerate(shape_bounds)
            if bounds.zmin < pcb_bottom + _SPLIT_EPSILON_MM
        )
        obstacles.append((base, base.BoundingBox(), reaching_base))

    seated = {
        (obstacle_index, shape_index): _intersection_volume(
            shapes[shape_index], obstacle
        )
        for obstacle_index, (obstacle, obstacle_bounds, movers) in enumerate(obstacles)
        for shape_index in movers
        if _translated_bounds_overlap(
            shape_bounds[shape_index], obstacle_bounds, (0.0, 0.0, 0.0)
        )
    }

    def excess_volume(offset: Vector3) -> float:
        total = 0.0

        for obstacle_index, (obstacle, obstacle_bounds, movers) in enumerate(obstacles):
            for shape_index in movers:
                if not _translated_bounds_overlap(
                    shape_bounds[shape_index], obstacle_bounds, offset
                ):
                    continue

                volume = _intersection_volume(
                    _moved_shape(shapes[shape_index], offset), obstacle
                )
                total += max(
                    0.0, volume - seated.get((obstacle_index, shape_index), 0.0)
                )

        return total

    results: list[InstallationPathResult] = []

    for plan in plans:
        collisions: list[InstallationPathCollision] = []
        maximum = 0.0
        sample_count = 0

        for segment_index, (start, end) in enumerate(
            zip(plan.waypoints_mm, plan.waypoints_mm[1:])
        ):
            first_sample = 0 if segment_index == 0 else 1

            for sample_index in range(first_sample, plan.samples_per_segment + 1):
                fraction = sample_index / plan.samples_per_segment
                offset: Vector3 = (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                    start[2] + (end[2] - start[2]) * fraction,
                )
                volume = excess_volume(offset)
                maximum = max(maximum, volume)
                sample_count += 1

                if volume > tolerance_mm3:
                    collisions.append(
                        InstallationPathCollision(
                            segment_index=segment_index,
                            segment_fraction=round(fraction, 6),
                            offset_mm=(
                                round(offset[0], 6),
                                round(offset[1], 6),
                                round(offset[2], 6),
                            ),
                            intersection_mm3=round(volume, 6),
                        )
                    )

        results.append(
            InstallationPathResult(
                name=plan.name,
                passed=not collisions,
                sample_count=sample_count,
                maximum_intersection_mm3=round(maximum, 6),
                collisions=tuple(collisions),
            )
        )

    return InstallationPathReport(
        schema_version=INSTALLATION_PATH_SCHEMA_VERSION,
        candidate_id=candidate_id,
        tolerance_mm3=tolerance_mm3,
        results=tuple(results),
        limitation=LIMITATION,
        collision_geometry="fixture",
    )


def analyze_installation_paths(
    execution: ProductionCornerExecutionResult,
    *,
    candidate_id: str,
    plans: (tuple[InstallationPathPlan, ...] | None) = None,
    tolerance_mm3: float = 1e-6,
    fixture_policy: ValidationFixturePolicy | None = None,
) -> InstallationPathReport:
    """Sample rigid translations against the printed validation fixture."""

    return sample_installation_paths(
        candidate_id=candidate_id,
        plans=(
            plans if plans is not None else default_installation_path_plans(execution)
        ),
        pcb=execution.board_model.pcb,
        components=tuple(execution.board_model.component_solids),
        fixture=workplane_shape(
            build_validation_fixture(
                execution, policy=fixture_policy or ValidationFixturePolicy()
            )
        ),
        tolerance_mm3=tolerance_mm3,
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

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.corner_capture import (
    CornerCaptureParameters,
)
from zcad_core.retention.edge_capture import (
    EdgeCaptureLocation,
    EdgeCaptureParameters,
)


class PrintOrientation(str, Enum):
    """Declared build orientation for generated retention geometry."""

    BASE_DOWN = "base_down"


class ManufacturingCheck(str, Enum):
    """Required manufacturing-validation dimensions."""

    MINIMUM_WALL = "minimum_wall"
    BOARD_CLEARANCE = "board_clearance"
    VERTICAL_OVERLAP = "vertical_overlap"
    ARM_PROPORTION = "arm_proportion"
    CAPTURE_SPACING = "capture_spacing"
    PRINT_ORIENTATION = "print_orientation"
    OVERHANG = "overhang"


@dataclass(frozen=True)
class ManufacturingPolicy:
    """Manufacturing limits for corner-capture geometry."""

    minimum_wall_mm: float = 1.20
    minimum_board_clearance_mm: float = 0.20
    minimum_vertical_overlap_mm: float = 0.40
    minimum_capture_spacing_mm: float = 10.0
    maximum_unsupported_overhang_mm: float = 3.0
    print_orientation: PrintOrientation = PrintOrientation.BASE_DOWN

    def __post_init__(self) -> None:
        positive_fields = {
            "minimum_wall_mm": self.minimum_wall_mm,
            "minimum_board_clearance_mm": (self.minimum_board_clearance_mm),
            "minimum_vertical_overlap_mm": (self.minimum_vertical_overlap_mm),
            "minimum_capture_spacing_mm": (self.minimum_capture_spacing_mm),
            "maximum_unsupported_overhang_mm": (self.maximum_unsupported_overhang_mm),
        }

        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class ManufacturingCheckResult:
    """Outcome of one manufacturing gate."""

    check: ManufacturingCheck
    passed: bool
    measured_value: float | str
    required_value: float | str
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("Manufacturing result detail cannot be empty")


@dataclass(frozen=True)
class ManufacturingReport:
    """Complete fail-closed manufacturing-validation report."""

    results: tuple[ManufacturingCheckResult, ...]

    def __post_init__(self) -> None:
        checks = tuple(result.check for result in self.results)

        if len(set(checks)) != len(checks):
            raise ValueError("Manufacturing report cannot contain duplicate checks")

    @property
    def passed(self) -> bool:
        required = set(ManufacturingCheck)
        observed = {result.check for result in self.results}

        return observed == required and all(result.passed for result in self.results)

    @property
    def failures(
        self,
    ) -> tuple[ManufacturingCheckResult, ...]:
        return tuple(result for result in self.results if not result.passed)


def validate_corner_capture_manufacturing(
    parameters: CornerCaptureParameters,
    *,
    policy: ManufacturingPolicy,
) -> ManufacturingReport:
    """Validate derived corner-capture parameters for printing."""

    spacing_mm = _minimum_location_spacing(parameters)

    wall_passed = parameters.minimum_wall_mm >= policy.minimum_wall_mm
    clearance_passed = (
        parameters.board_clearance_mm >= policy.minimum_board_clearance_mm
    )
    overlap_passed = (
        parameters.vertical_overlap_mm >= policy.minimum_vertical_overlap_mm
    )
    arm_passed = parameters.arm_width_mm > (
        2.0 * parameters.board_clearance_mm + parameters.minimum_wall_mm
    )
    spacing_passed = spacing_mm >= policy.minimum_capture_spacing_mm

    orientation_passed = policy.print_orientation is PrintOrientation.BASE_DOWN

    unsupported_overhang_mm = parameters.vertical_overlap_mm
    overhang_passed = unsupported_overhang_mm <= policy.maximum_unsupported_overhang_mm

    return ManufacturingReport(
        results=(
            ManufacturingCheckResult(
                check=ManufacturingCheck.MINIMUM_WALL,
                passed=wall_passed,
                measured_value=(parameters.minimum_wall_mm),
                required_value=(policy.minimum_wall_mm),
                detail=(
                    "Minimum wall thickness satisfies the manufacturing policy."
                    if wall_passed
                    else "Minimum wall thickness is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.BOARD_CLEARANCE,
                passed=clearance_passed,
                measured_value=(parameters.board_clearance_mm),
                required_value=(policy.minimum_board_clearance_mm),
                detail=(
                    "Board clearance satisfies the manufacturing policy."
                    if clearance_passed
                    else "Board clearance is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.VERTICAL_OVERLAP,
                passed=overlap_passed,
                measured_value=(parameters.vertical_overlap_mm),
                required_value=(policy.minimum_vertical_overlap_mm),
                detail=(
                    "Vertical retention overlap satisfies the manufacturing policy."
                    if overlap_passed
                    else "Vertical retention overlap is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.ARM_PROPORTION,
                passed=arm_passed,
                measured_value=(parameters.arm_width_mm),
                required_value=(
                    2.0 * parameters.board_clearance_mm + parameters.minimum_wall_mm
                ),
                detail=(
                    "Capture arm width exceeds wall and clearance requirements."
                    if arm_passed
                    else "Capture arm width is insufficient "
                    "for wall and clearance requirements."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.CAPTURE_SPACING,
                passed=spacing_passed,
                measured_value=spacing_mm,
                required_value=(policy.minimum_capture_spacing_mm),
                detail=(
                    "Capture spacing satisfies the mechanical-balance threshold."
                    if spacing_passed
                    else "Capture spacing is below the mechanical-balance threshold."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.PRINT_ORIENTATION,
                passed=orientation_passed,
                measured_value=(policy.print_orientation.value),
                required_value=(PrintOrientation.BASE_DOWN.value),
                detail=(
                    "Base-down print orientation is declared."
                    if orientation_passed
                    else "A supported print orientation has not been declared."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.OVERHANG,
                passed=overhang_passed,
                measured_value=(unsupported_overhang_mm),
                required_value=(policy.maximum_unsupported_overhang_mm),
                detail=(
                    "Unsupported overlap is within the configured overhang limit."
                    if overhang_passed
                    else "Unsupported overlap exceeds the configured overhang limit."
                ),
            ),
        )
    )


def _minimum_location_spacing(
    parameters: CornerCaptureParameters,
) -> float:
    locations = parameters.locations

    distances = tuple(
        ((first.x_mm - second.x_mm) ** 2 + (first.y_mm - second.y_mm) ** 2) ** 0.5
        for index, first in enumerate(locations)
        for second in locations[index + 1 :]
    )

    if not distances:
        raise ValueError("At least two capture locations are required")

    return min(distances)


def validate_edge_capture_manufacturing(
    parameters: EdgeCaptureParameters,
    *,
    policy: ManufacturingPolicy,
) -> ManufacturingReport:
    """Validate derived edge-capture parameters for printing."""

    spacing_mm = _minimum_edge_location_spacing(parameters)

    wall_passed = parameters.minimum_wall_mm >= policy.minimum_wall_mm
    clearance_passed = (
        parameters.board_clearance_mm >= policy.minimum_board_clearance_mm
    )
    overlap_passed = (
        parameters.vertical_overlap_mm >= policy.minimum_vertical_overlap_mm
    )
    arm_passed = parameters.arm_width_mm > (
        2.0 * parameters.board_clearance_mm + parameters.minimum_wall_mm
    )
    spacing_passed = spacing_mm >= policy.minimum_capture_spacing_mm

    orientation_passed = policy.print_orientation is PrintOrientation.BASE_DOWN

    unsupported_overhang_mm = parameters.vertical_overlap_mm
    overhang_passed = unsupported_overhang_mm <= policy.maximum_unsupported_overhang_mm

    return ManufacturingReport(
        results=(
            ManufacturingCheckResult(
                check=ManufacturingCheck.MINIMUM_WALL,
                passed=wall_passed,
                measured_value=(parameters.minimum_wall_mm),
                required_value=(policy.minimum_wall_mm),
                detail=(
                    "Minimum wall thickness satisfies the manufacturing policy."
                    if wall_passed
                    else "Minimum wall thickness is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.BOARD_CLEARANCE,
                passed=clearance_passed,
                measured_value=(parameters.board_clearance_mm),
                required_value=(policy.minimum_board_clearance_mm),
                detail=(
                    "Board clearance satisfies the manufacturing policy."
                    if clearance_passed
                    else "Board clearance is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.VERTICAL_OVERLAP,
                passed=overlap_passed,
                measured_value=(parameters.vertical_overlap_mm),
                required_value=(policy.minimum_vertical_overlap_mm),
                detail=(
                    "Vertical retention overlap satisfies the manufacturing policy."
                    if overlap_passed
                    else "Vertical retention overlap is below the manufacturing policy."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.ARM_PROPORTION,
                passed=arm_passed,
                measured_value=(parameters.arm_width_mm),
                required_value=(
                    2.0 * parameters.board_clearance_mm + parameters.minimum_wall_mm
                ),
                detail=(
                    "Capture arm width exceeds wall and clearance requirements."
                    if arm_passed
                    else "Capture arm width is insufficient "
                    "for wall and clearance requirements."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.CAPTURE_SPACING,
                passed=spacing_passed,
                measured_value=spacing_mm,
                required_value=(policy.minimum_capture_spacing_mm),
                detail=(
                    "Capture spacing satisfies the mechanical-balance threshold."
                    if spacing_passed
                    else "Capture spacing is below the mechanical-balance threshold."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.PRINT_ORIENTATION,
                passed=orientation_passed,
                measured_value=(policy.print_orientation.value),
                required_value=(PrintOrientation.BASE_DOWN.value),
                detail=(
                    "Base-down print orientation is declared."
                    if orientation_passed
                    else "A supported print orientation has not been declared."
                ),
            ),
            ManufacturingCheckResult(
                check=ManufacturingCheck.OVERHANG,
                passed=overhang_passed,
                measured_value=(unsupported_overhang_mm),
                required_value=(policy.maximum_unsupported_overhang_mm),
                detail=(
                    "Unsupported overlap is within the configured overhang limit."
                    if overhang_passed
                    else "Unsupported overlap exceeds the configured overhang limit."
                ),
            ),
        )
    )


def _absolute_xy(
    location: EdgeCaptureLocation,
) -> tuple[float, float]:
    if location.edge in (BoardEdge.NEGATIVE_X, BoardEdge.POSITIVE_X):
        return location.edge_coordinate_mm, location.position_mm

    return location.position_mm, location.edge_coordinate_mm


def _minimum_edge_location_spacing(
    parameters: EdgeCaptureParameters,
) -> float:
    points = tuple(_absolute_xy(location) for location in parameters.locations)

    distances = tuple(
        ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
        for index, first in enumerate(points)
        for second in points[index + 1 :]
    )

    if not distances:
        raise ValueError("At least two capture locations are required")

    return min(distances)

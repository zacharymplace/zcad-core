"""Assembly-aware mounting metadata and position derivation."""

from collections.abc import Mapping
from math import cos, radians, sin
from typing import Any, Protocol, TypedDict

from zcad_core.assemblies.component import AssemblyComponent
from zcad_core.assemblies.placement import Placement


class RectangularMountingBoardSpec(Protocol):
    """Optional rectangular mounting properties supplied by a board."""

    @property
    def mounting_hole_diameter_mm(self) -> float: ...
    @property
    def mounting_hole_spacing_x_mm(self) -> float: ...
    @property
    def mounting_hole_spacing_y_mm(self) -> float: ...
    @property
    def recommended_standoff_height_mm(self) -> float: ...
    @property
    def recommended_clearance_mm(self) -> float: ...


class RectangularMountingMetadata(TypedDict):
    """Structured four-hole rectangular mounting metadata."""

    pattern: str
    hole_diameter_mm: float
    spacing_x_mm: float
    spacing_y_mm: float
    recommended_standoff_height_mm: float
    recommended_clearance_mm: float


def rectangular_board_mounting_metadata(
    board: object,
) -> RectangularMountingMetadata | None:
    """Return mounting metadata when a complete board pattern exists.

    A board that lists irregular holes in ``mounting_hole_positions_mm`` has
    no rectangular pattern, so it gets none.
    """
    if getattr(board, "mounting_hole_positions_mm", None) is not None:
        return None

    hole_fields = {
        "hole_diameter_mm": "mounting_hole_diameter_mm",
        "spacing_x_mm": "mounting_hole_spacing_x_mm",
        "spacing_y_mm": "mounting_hole_spacing_y_mm",
    }

    resolved_holes = {
        target: getattr(board, source, None) for target, source in hole_fields.items()
    }

    defined_holes = {name: value is not None for name, value in resolved_holes.items()}

    # Recommendations alone do not establish a verified hole pattern.
    if not any(defined_holes.values()):
        return None

    if not all(defined_holes.values()):
        missing = ", ".join(
            sorted(name for name, is_defined in defined_holes.items() if not is_defined)
        )
        raise ValueError(
            f"board mounting-hole metadata must be complete; missing: {missing}"
        )

    recommendations = {
        "recommended_standoff_height_mm": getattr(
            board,
            "recommended_standoff_height_mm",
            None,
        ),
        "recommended_clearance_mm": getattr(
            board,
            "recommended_clearance_mm",
            None,
        ),
    }

    missing_recommendations = [
        name for name, value in recommendations.items() if value is None
    ]

    if missing_recommendations:
        rendered = ", ".join(sorted(missing_recommendations))
        raise ValueError(
            f"board mounting recommendations must be complete; missing: {rendered}"
        )

    for name, value in resolved_holes.items():
        assert value is not None

        if value <= 0:
            raise ValueError(
                f"board mounting metadata {name} must be greater than zero"
            )

    standoff_height = recommendations["recommended_standoff_height_mm"]
    clearance = recommendations["recommended_clearance_mm"]

    assert standoff_height is not None
    assert clearance is not None

    if standoff_height <= 0:
        raise ValueError(
            "board mounting metadata "
            "recommended_standoff_height_mm "
            "must be greater than zero"
        )

    if clearance < 0:
        raise ValueError(
            "board mounting metadata recommended_clearance_mm must not be negative"
        )

    hole_diameter_mm = resolved_holes["hole_diameter_mm"]
    spacing_x_mm = resolved_holes["spacing_x_mm"]
    spacing_y_mm = resolved_holes["spacing_y_mm"]

    assert hole_diameter_mm is not None
    assert spacing_x_mm is not None
    assert spacing_y_mm is not None

    return RectangularMountingMetadata(
        pattern="rectangular_4_hole",
        hole_diameter_mm=hole_diameter_mm,
        spacing_x_mm=spacing_x_mm,
        spacing_y_mm=spacing_y_mm,
        recommended_standoff_height_mm=standoff_height,
        recommended_clearance_mm=clearance,
    )


def _rotate_point(
    point: tuple[float, float, float],
    placement: Placement,
) -> tuple[float, float, float]:
    """Apply Placement Euler rotations in the same X/Y/Z order."""
    x, y, z = point

    if placement.rotation_x_deg:
        angle = radians(placement.rotation_x_deg)
        y, z = (
            y * cos(angle) - z * sin(angle),
            y * sin(angle) + z * cos(angle),
        )

    if placement.rotation_y_deg:
        angle = radians(placement.rotation_y_deg)
        x, z = (
            x * cos(angle) + z * sin(angle),
            -x * sin(angle) + z * cos(angle),
        )

    if placement.rotation_z_deg:
        angle = radians(placement.rotation_z_deg)
        x, y = (
            x * cos(angle) - y * sin(angle),
            x * sin(angle) + y * cos(angle),
        )

    return (
        x + placement.x_mm,
        y + placement.y_mm,
        z + placement.z_mm,
    )


def _mounting_metadata(
    component: AssemblyComponent,
) -> Mapping[str, Any] | None:
    mounting = component.metadata.get("mounting")

    if mounting is None:
        return None

    if not isinstance(mounting, Mapping):
        raise TypeError("component mounting metadata must be a mapping")

    return mounting


def assembly_mounting_hole_positions(
    component: AssemblyComponent,
) -> tuple[tuple[float, float, float], ...]:
    """Return mounting-hole centers in assembly coordinates."""
    mounting = _mounting_metadata(component)

    if mounting is None:
        return ()

    pattern = mounting.get("pattern")

    if pattern != "rectangular_4_hole":
        raise ValueError(f"unsupported mounting pattern: {pattern}")

    spacing_x_mm = mounting.get("spacing_x_mm")
    spacing_y_mm = mounting.get("spacing_y_mm")

    if not isinstance(spacing_x_mm, int | float):
        raise TypeError("mounting spacing_x_mm must be numeric")

    if not isinstance(spacing_y_mm, int | float):
        raise TypeError("mounting spacing_y_mm must be numeric")

    if spacing_x_mm <= 0:
        raise ValueError("mounting spacing_x_mm must be greater than zero")

    if spacing_y_mm <= 0:
        raise ValueError("mounting spacing_y_mm must be greater than zero")

    half_x = spacing_x_mm / 2
    half_y = spacing_y_mm / 2

    local_positions = (
        (-half_x, -half_y, 0.0),
        (half_x, -half_y, 0.0),
        (-half_x, half_y, 0.0),
        (half_x, half_y, 0.0),
    )

    return tuple(
        _rotate_point(
            position,
            component.placement,
        )
        for position in local_positions
    )

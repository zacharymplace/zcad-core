"""Reusable engineering fastener specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FastenerSpec:
    """Engineering dimensions for a reusable fastener."""

    identifier: str
    nominal_diameter_mm: float
    clearance_hole_mm: float
    tap_hole_mm: float
    heat_set_insert_diameter_mm: float | None = None
    heat_set_insert_depth_mm: float | None = None


_FASTENERS = {
    "M2": FastenerSpec(
        identifier="M2",
        nominal_diameter_mm=2.0,
        clearance_hole_mm=2.4,
        tap_hole_mm=1.6,
        heat_set_insert_diameter_mm=3.2,
        heat_set_insert_depth_mm=3.0,
    ),
    "M2.5": FastenerSpec(
        identifier="M2.5",
        nominal_diameter_mm=2.5,
        clearance_hole_mm=2.9,
        tap_hole_mm=2.05,
        heat_set_insert_diameter_mm=3.9,
        heat_set_insert_depth_mm=4.0,
    ),
    "M3": FastenerSpec(
        identifier="M3",
        nominal_diameter_mm=3.0,
        clearance_hole_mm=3.4,
        tap_hole_mm=2.5,
        heat_set_insert_diameter_mm=4.6,
        heat_set_insert_depth_mm=5.0,
    ),
    "M4": FastenerSpec(
        identifier="M4",
        nominal_diameter_mm=4.0,
        clearance_hole_mm=4.5,
        tap_hole_mm=3.3,
        heat_set_insert_diameter_mm=6.3,
        heat_set_insert_depth_mm=6.0,
    ),
}


def get_fastener(
    identifier: str,
) -> FastenerSpec:
    """Return one reusable fastener specification."""
    try:
        return _FASTENERS[identifier.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported fastener: {identifier}") from exc


def list_fasteners() -> tuple[str, ...]:
    """Return supported fastener identifiers."""
    return tuple(sorted(_FASTENERS))

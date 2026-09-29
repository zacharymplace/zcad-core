"""Derive enclosure requirements from reusable device assemblies."""

from dataclasses import dataclass
from typing import cast

from zcad_core.assemblies.assembly import DeviceAssembly
from zcad_core.assemblies.models import (
    Assembly,
    AssemblyPart,
    Mate,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware.electronics.connectors import BoardEdge


def build_enclosure_assembly(
    *,
    assembly_id: str,
    lid_clearance: float,
    lid_engagement: float,
) -> Assembly:
    """Create the standard body-and-lid enclosure assembly."""
    return Assembly(
        assembly_id=assembly_id,
        reference_part="body",
        parts=(
            AssemblyPart(
                name="body",
            ),
            AssemblyPart(
                name="lid",
            ),
        ),
        relationships=(
            Mate(
                parent="body",
                child="lid",
                kind="sliding_fit",
                axis="z",
                direction="negative",
                clearance_mm=lid_clearance,
                engagement_mm=lid_engagement,
            ),
        ),
    )


@dataclass(frozen=True)
class EnclosureSpecification:
    """Resolved internal enclosure and connector-opening requirements."""

    inner_width_mm: float
    inner_depth_mm: float
    inner_height_mm: float

    center_x_mm: float
    center_y_mm: float
    bottom_z_mm: float

    connector_identifier: str
    cable_edge: BoardEdge
    cable_width_mm: float
    cable_height_mm: float
    cable_center_offset_mm: float
    cable_bottom_z_mm: float

    def validate(self) -> None:
        """Validate resolved enclosure requirements."""
        positive_values = {
            "inner_width_mm": self.inner_width_mm,
            "inner_depth_mm": self.inner_depth_mm,
            "inner_height_mm": self.inner_height_mm,
            "cable_width_mm": self.cable_width_mm,
            "cable_height_mm": self.cable_height_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if not self.connector_identifier.strip():
            raise ValueError("connector_identifier must not be empty")


def derive_enclosure_specification(
    assembly: DeviceAssembly,
    *,
    connector_identifier: str = "usb_connector",
    internal_clearance_mm: float = 2.0,
    connector_cutout_clearance_mm: float = 0.5,
    side_clearance_mm: float | None = None,
    bottom_clearance_mm: float | None = None,
    top_clearance_mm: float | None = None,
) -> EnclosureSpecification:
    """Derive cavity and connector-opening requirements from an assembly.

    ``internal_clearance_mm`` is the gap between the hardware and the cavity
    on every side; ``side_clearance_mm`` (X and Y), ``bottom_clearance_mm``,
    and ``top_clearance_mm`` override it in their directions.
    """
    if not connector_identifier.strip():
        raise ValueError("connector_identifier must not be empty")

    side = _clearance("side_clearance_mm", side_clearance_mm, internal_clearance_mm)
    bottom = _clearance(
        "bottom_clearance_mm", bottom_clearance_mm, internal_clearance_mm
    )
    top = _clearance("top_clearance_mm", top_clearance_mm, internal_clearance_mm)

    if connector_cutout_clearance_mm < 0:
        raise ValueError("connector_cutout_clearance_mm must not be negative")

    if not assembly.components:
        raise ValueError("assembly must contain at least one component")

    expanded_bounds: list[tuple[float, float, float, float, float, float]] = []

    for component in assembly:
        bounds = workplane_shape(component.transformed_geometry()).BoundingBox()
        envelope = component.clearance_envelope

        expanded_bounds.append(
            (
                bounds.xmin - envelope.negative_x_mm - side,
                bounds.ymin - envelope.negative_y_mm - side,
                bounds.zmin - envelope.negative_z_mm - bottom,
                bounds.xmax + envelope.positive_x_mm + side,
                bounds.ymax + envelope.positive_y_mm + side,
                bounds.zmax + envelope.positive_z_mm + top,
            )
        )

    minimum_x_mm = min(item[0] for item in expanded_bounds)
    minimum_y_mm = min(item[1] for item in expanded_bounds)
    minimum_z_mm = min(item[2] for item in expanded_bounds)
    maximum_x_mm = max(item[3] for item in expanded_bounds)
    maximum_y_mm = max(item[4] for item in expanded_bounds)
    maximum_z_mm = max(item[5] for item in expanded_bounds)

    center_x_mm = (minimum_x_mm + maximum_x_mm) / 2
    center_y_mm = (minimum_y_mm + maximum_y_mm) / 2

    connector = assembly.get(connector_identifier)
    connector_bounds = workplane_shape(connector.transformed_geometry()).BoundingBox()

    raw_edge = connector.metadata.get("board_edge")

    if raw_edge not in {
        "negative_x",
        "positive_x",
        "negative_y",
        "positive_y",
    }:
        raise ValueError(f"{connector_identifier} must define a supported board_edge")

    cable_edge = cast(BoardEdge, raw_edge)

    if cable_edge in {"negative_y", "positive_y"}:
        cable_width_mm = connector_bounds.xlen + 2 * connector_cutout_clearance_mm
        cable_center_offset_mm = (
            connector_bounds.xmin + connector_bounds.xmax
        ) / 2 - center_x_mm
    else:
        cable_width_mm = connector_bounds.ylen + 2 * connector_cutout_clearance_mm
        cable_center_offset_mm = (
            connector_bounds.ymin + connector_bounds.ymax
        ) / 2 - center_y_mm

    specification = EnclosureSpecification(
        inner_width_mm=maximum_x_mm - minimum_x_mm,
        inner_depth_mm=maximum_y_mm - minimum_y_mm,
        inner_height_mm=maximum_z_mm - minimum_z_mm,
        center_x_mm=center_x_mm,
        center_y_mm=center_y_mm,
        bottom_z_mm=minimum_z_mm,
        connector_identifier=connector_identifier,
        cable_edge=cable_edge,
        cable_width_mm=cable_width_mm,
        cable_height_mm=(connector_bounds.zlen + 2 * connector_cutout_clearance_mm),
        cable_center_offset_mm=cable_center_offset_mm,
        cable_bottom_z_mm=(connector_bounds.zmin - connector_cutout_clearance_mm),
    )

    specification.validate()
    return specification


def _clearance(name: str, value: float | None, default: float) -> float:
    """A directional clearance, or the internal clearance when it is unset."""

    if default < 0:
        raise ValueError("internal_clearance_mm must not be negative")

    if value is None:
        return default

    if value < 0:
        raise ValueError(f"{name} must not be negative")

    return value

"""Reusable assembly components for rectangular hardware."""

from collections.abc import Mapping, Sequence
from typing import Any

import cadquery as cq

from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
)
from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.placement import (
    Placement,
)

_CANONICAL_METADATA_KEYS = frozenset(
    {
        "kind",
        "hardware_identifier",
        "width_mm",
        "depth_mm",
        "height_mm",
    }
)


def build_rectangular_hardware_component(
    *,
    identifier: str,
    hardware_identifier: str,
    kind: str,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
    placement: Placement | None = None,
    clearance_envelope: ClearanceEnvelope | None = None,
    metadata: Mapping[str, Any] | None = None,
    outline_points_mm: Sequence[tuple[float, float]] | None = None,
) -> AssemblyComponent:
    """Build a bottom-centered rectangular hardware proxy, or, given
    ``outline_points_mm`` (about its centre), a prism of that outline."""
    if not identifier.strip():
        raise ValueError("hardware component identifier must not be empty")

    if not hardware_identifier.strip():
        raise ValueError("hardware identifier must not be empty")

    if not kind.strip():
        raise ValueError("hardware component kind must not be empty")

    dimensions = {
        "width_mm": width_mm,
        "depth_mm": depth_mm,
        "height_mm": height_mm,
    }

    for name, value in dimensions.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")

    additional_metadata = dict(metadata) if metadata is not None else {}

    conflicting_keys = set(additional_metadata) & _CANONICAL_METADATA_KEYS

    if conflicting_keys:
        rendered = ", ".join(sorted(conflicting_keys))

        raise ValueError(
            f"additional metadata must not override canonical keys: {rendered}"
        )

    component_metadata = {
        "kind": kind,
        "hardware_identifier": hardware_identifier,
        "width_mm": width_mm,
        "depth_mm": depth_mm,
        "height_mm": height_mm,
        **additional_metadata,
    }

    if outline_points_mm is not None:
        # A polygon about the centre, so its bounding box is this width and depth.
        geometry = (
            cq.Workplane("XY")
            .polyline([(x, y) for x, y in outline_points_mm])
            .close()
            .extrude(height_mm)
        )
    else:
        geometry = cq.Workplane("XY").box(
            width_mm,
            depth_mm,
            height_mm,
            centered=(True, True, False),
        )

    return AssemblyComponent(
        identifier=identifier,
        geometry=geometry,
        placement=(placement if placement is not None else Placement()),
        metadata=component_metadata,
        clearance_envelope=(
            clearance_envelope
            if clearance_envelope is not None
            else ClearanceEnvelope()
        ),
    )

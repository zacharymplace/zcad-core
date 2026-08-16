"""Reusable assembly component definitions."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.geometry.cadquery_support import workplane_shape


@dataclass(frozen=True)
class AssemblyComponent:
    """One named piece of geometry placed within an assembly."""

    identifier: str
    geometry: cq.Workplane
    placement: Placement = field(default_factory=Placement)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    clearance_envelope: ClearanceEnvelope = field(default_factory=ClearanceEnvelope)

    def validate(self) -> None:
        """Validate component identity and geometry."""
        if not self.identifier.strip():
            raise ValueError("identifier must not be empty")

        value = workplane_shape(self.geometry)

        if not value.isValid():
            raise ValueError("geometry must contain a valid shape")

    def transformed_geometry(
        self,
    ) -> cq.Workplane:
        """Return geometry positioned in assembly coordinates."""
        self.validate()

        return self.placement.apply(self.geometry)

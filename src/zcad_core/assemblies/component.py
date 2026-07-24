"""Reusable assembly component definitions."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.assemblies.placement import (
    Placement,
)


@dataclass(frozen=True)
class AssemblyComponent:
    """One named piece of geometry placed within an assembly."""

    identifier: str
    geometry: cq.Workplane
    placement: Placement = field(default_factory=Placement)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate component identity and geometry."""
        if not self.identifier.strip():
            raise ValueError("identifier must not be empty")

        value = self.geometry.val()

        if value is None:
            raise ValueError("geometry must contain a shape")

        if not value.isValid():
            raise ValueError("geometry must contain a valid shape")

    def transformed_geometry(
        self,
    ) -> cq.Workplane:
        """Return geometry positioned in assembly coordinates."""
        self.validate()

        return self.placement.apply(self.geometry)

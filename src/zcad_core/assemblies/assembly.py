"""Reusable device assembly container."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies.clearance import (
    ClearancePolicy,
)
from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.interference import (
    ComponentPair,
    InterferenceReport,
    analyze_component_interference,
)


@dataclass(frozen=True)
class AssemblyBounds:
    """Axis-aligned bounds for an assembly."""

    minimum_x_mm: float
    minimum_y_mm: float
    minimum_z_mm: float

    maximum_x_mm: float
    maximum_y_mm: float
    maximum_z_mm: float

    @property
    def width_mm(self) -> float:
        """Return X-axis size."""
        return self.maximum_x_mm - self.minimum_x_mm

    @property
    def depth_mm(self) -> float:
        """Return Y-axis size."""
        return self.maximum_y_mm - self.minimum_y_mm

    @property
    def height_mm(self) -> float:
        """Return Z-axis size."""
        return self.maximum_z_mm - self.minimum_z_mm

    @property
    def center_x_mm(self) -> float:
        """Return X-axis center."""
        return (self.minimum_x_mm + self.maximum_x_mm) / 2

    @property
    def center_y_mm(self) -> float:
        """Return Y-axis center."""
        return (self.minimum_y_mm + self.maximum_y_mm) / 2

    @property
    def center_z_mm(self) -> float:
        """Return Z-axis center."""
        return (self.minimum_z_mm + self.maximum_z_mm) / 2


class DeviceAssembly:
    """Ordered collection of uniquely named placed components."""

    def __init__(
        self,
        components: Iterable[AssemblyComponent] = (),
    ) -> None:
        self._components: list[AssemblyComponent] = []

        for component in components:
            self.add(component)

    def __len__(self) -> int:
        """Return component count."""
        return len(self._components)

    def __iter__(
        self,
    ) -> Iterator[AssemblyComponent]:
        """Iterate over components in insertion order."""
        return iter(self._components)

    @property
    def components(
        self,
    ) -> tuple[AssemblyComponent, ...]:
        """Return an immutable component snapshot."""
        return tuple(self._components)

    @property
    def identifiers(
        self,
    ) -> tuple[str, ...]:
        """Return component identifiers in insertion order."""
        return tuple(component.identifier for component in self._components)

    def add(
        self,
        component: AssemblyComponent,
    ) -> None:
        """Add one validated, uniquely named component."""
        component.validate()

        if component.identifier in self.identifiers:
            raise ValueError(
                f"component identifier already exists: {component.identifier}"
            )

        self._components.append(component)

    def get(
        self,
        identifier: str,
    ) -> AssemblyComponent:
        """Return one component by identifier."""
        for component in self._components:
            if component.identifier == identifier:
                return component

        raise KeyError(identifier)

    def transformed_components(
        self,
    ) -> dict[str, cq.Workplane]:
        """Return all geometry in assembly coordinates."""
        return {
            component.identifier: (component.transformed_geometry())
            for component in self._components
        }

    def bounds(
        self,
    ) -> AssemblyBounds:
        """Return aggregate transformed component bounds."""
        if not self._components:
            raise ValueError("assembly must contain at least one component")

        bounding_boxes = [
            component.transformed_geometry().val().BoundingBox()
            for component in self._components
        ]

        return AssemblyBounds(
            minimum_x_mm=min(bounds.xmin for bounds in bounding_boxes),
            minimum_y_mm=min(bounds.ymin for bounds in bounding_boxes),
            minimum_z_mm=min(bounds.zmin for bounds in bounding_boxes),
            maximum_x_mm=max(bounds.xmax for bounds in bounding_boxes),
            maximum_y_mm=max(bounds.ymax for bounds in bounding_boxes),
            maximum_z_mm=max(bounds.zmax for bounds in bounding_boxes),
        )

    def analyze_interference(
        self,
        *,
        allowed_contact_pairs: tuple[ComponentPair, ...] = (),
        minimum_clearance_mm: float = 0.0,
        collision_volume_tolerance_mm3: float = 1e-6,
        clearance_policy: ClearancePolicy | None = None,
    ) -> InterferenceReport:
        """Return pairwise interference findings."""
        return analyze_component_interference(
            self._components,
            allowed_contact_pairs=(allowed_contact_pairs),
            minimum_clearance_mm=(minimum_clearance_mm),
            collision_volume_tolerance_mm3=(collision_volume_tolerance_mm3),
            clearance_policy=clearance_policy,
        )

    def compound(
        self,
    ) -> cq.Workplane:
        """Return transformed components as one CAD compound."""
        if not self._components:
            raise ValueError("assembly must contain at least one component")

        shapes = [
            component.transformed_geometry().val() for component in self._components
        ]

        compound = cq.Compound.makeCompound(shapes)

        return cq.Workplane("XY").newObject(
            [
                compound,
            ]
        )

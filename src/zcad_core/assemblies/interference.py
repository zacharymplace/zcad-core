"""Assembly interference and clearance detection."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import sqrt

import cadquery as cq

from zcad_core.assemblies.component import (
    AssemblyComponent,
)

ComponentPair = frozenset[str]


@dataclass(frozen=True)
class InterferenceFinding:
    """One detected collision or clearance violation."""

    first_identifier: str
    second_identifier: str
    kind: str

    intersection_volume_mm3: float = 0.0
    required_clearance_mm: float = 0.0
    measured_clearance_mm: float | None = None
    clearance_source: str | None = None

    @property
    def pair(self) -> ComponentPair:
        """Return the unordered component identifier pair."""
        return frozenset(
            (
                self.first_identifier,
                self.second_identifier,
            )
        )


@dataclass(frozen=True)
class InterferenceReport:
    """Structured interference-analysis result."""

    findings: tuple[InterferenceFinding, ...]

    @property
    def has_findings(self) -> bool:
        """Return whether any interference was detected."""
        return bool(self.findings)

    @property
    def collisions(
        self,
    ) -> tuple[InterferenceFinding, ...]:
        """Return exact solid collisions."""
        return tuple(
            finding for finding in self.findings if finding.kind == "collision"
        )

    @property
    def clearance_violations(
        self,
    ) -> tuple[InterferenceFinding, ...]:
        """Return minimum-clearance violations."""
        return tuple(
            finding for finding in self.findings if finding.kind == "clearance"
        )


def component_pair(
    first_identifier: str,
    second_identifier: str,
) -> ComponentPair:
    """Create a normalized unordered component pair."""
    if not first_identifier.strip():
        raise ValueError("first_identifier must not be empty")

    if not second_identifier.strip():
        raise ValueError("second_identifier must not be empty")

    if first_identifier == second_identifier:
        raise ValueError("component pair identifiers must differ")

    return frozenset(
        (
            first_identifier,
            second_identifier,
        )
    )


def _bounding_boxes_overlap(
    first: cq.BoundBox,
    second: cq.BoundBox,
    *,
    tolerance_mm: float = 0.0,
) -> bool:
    """Return whether two axis-aligned bounds overlap."""
    return not (
        first.xmax <= second.xmin + tolerance_mm
        or second.xmax <= first.xmin + tolerance_mm
        or first.ymax <= second.ymin + tolerance_mm
        or second.ymax <= first.ymin + tolerance_mm
        or first.zmax <= second.zmin + tolerance_mm
        or second.zmax <= first.zmin + tolerance_mm
    )


def _axis_gap_mm(
    first_minimum_mm: float,
    first_maximum_mm: float,
    second_minimum_mm: float,
    second_maximum_mm: float,
) -> float:
    """Return nonnegative separation along one axis."""
    if first_maximum_mm < second_minimum_mm:
        return second_minimum_mm - first_maximum_mm

    if second_maximum_mm < first_minimum_mm:
        return first_minimum_mm - second_maximum_mm

    return 0.0


def _bounding_box_clearance_mm(
    first: cq.BoundBox,
    second: cq.BoundBox,
) -> float:
    """Return Euclidean distance between axis-aligned bounds."""
    gap_x_mm = _axis_gap_mm(
        first.xmin,
        first.xmax,
        second.xmin,
        second.xmax,
    )
    gap_y_mm = _axis_gap_mm(
        first.ymin,
        first.ymax,
        second.ymin,
        second.ymax,
    )
    gap_z_mm = _axis_gap_mm(
        first.zmin,
        first.zmax,
        second.zmin,
        second.zmax,
    )

    return (gap_x_mm**2 + gap_y_mm**2 + gap_z_mm**2) ** 0.5


def _expanded_bounds_overlap(
    first: cq.BoundBox,
    first_component: AssemblyComponent,
    second: cq.BoundBox,
    second_component: AssemblyComponent,
) -> bool:
    """Return whether directional keep-out bounds overlap."""
    first_envelope = first_component.clearance_envelope
    second_envelope = second_component.clearance_envelope

    return not (
        (
            first.xmax + first_envelope.positive_x_mm
            <= second.xmin - second_envelope.negative_x_mm
        )
        or (
            second.xmax + second_envelope.positive_x_mm
            <= first.xmin - first_envelope.negative_x_mm
        )
        or (
            first.ymax + first_envelope.positive_y_mm
            <= second.ymin - second_envelope.negative_y_mm
        )
        or (
            second.ymax + second_envelope.positive_y_mm
            <= first.ymin - first_envelope.negative_y_mm
        )
        or (
            first.zmax + first_envelope.positive_z_mm
            <= second.zmin - second_envelope.negative_z_mm
        )
        or (
            second.zmax + second_envelope.positive_z_mm
            <= first.zmin - first_envelope.negative_z_mm
        )
    )


def _directional_requirement_mm(
    *,
    axis: str,
    first_minimum_mm: float,
    first_maximum_mm: float,
    first_component: AssemblyComponent,
    second_minimum_mm: float,
    second_maximum_mm: float,
    second_component: AssemblyComponent,
) -> float:
    """Return combined envelope requirement along one axis."""
    first_envelope = first_component.clearance_envelope
    second_envelope = second_component.clearance_envelope

    if first_maximum_mm <= second_minimum_mm:
        return first_envelope.positive_for_axis(
            axis
        ) + second_envelope.negative_for_axis(axis)

    if second_maximum_mm <= first_minimum_mm:
        return second_envelope.positive_for_axis(
            axis
        ) + first_envelope.negative_for_axis(axis)

    return 0.0


def _envelope_required_clearance_mm(
    first: cq.BoundBox,
    first_component: AssemblyComponent,
    second: cq.BoundBox,
    second_component: AssemblyComponent,
) -> float:
    """Return combined directional envelope distance."""
    required_x_mm = _directional_requirement_mm(
        axis="x",
        first_minimum_mm=first.xmin,
        first_maximum_mm=first.xmax,
        first_component=first_component,
        second_minimum_mm=second.xmin,
        second_maximum_mm=second.xmax,
        second_component=second_component,
    )
    required_y_mm = _directional_requirement_mm(
        axis="y",
        first_minimum_mm=first.ymin,
        first_maximum_mm=first.ymax,
        first_component=first_component,
        second_minimum_mm=second.ymin,
        second_maximum_mm=second.ymax,
        second_component=second_component,
    )
    required_z_mm = _directional_requirement_mm(
        axis="z",
        first_minimum_mm=first.zmin,
        first_maximum_mm=first.zmax,
        first_component=first_component,
        second_minimum_mm=second.zmin,
        second_maximum_mm=second.zmax,
        second_component=second_component,
    )

    return sqrt(required_x_mm**2 + required_y_mm**2 + required_z_mm**2)


def _intersection_volume_mm3(
    first: cq.Shape,
    second: cq.Shape,
) -> float:
    """Return exact common solid volume."""
    intersection = first.intersect(second)

    if intersection is None:
        return 0.0

    return max(
        0.0,
        float(intersection.Volume()),
    )


def analyze_component_interference(
    components: Iterable[AssemblyComponent],
    *,
    allowed_contact_pairs: Iterable[ComponentPair] = (),
    minimum_clearance_mm: float = 0.0,
    collision_volume_tolerance_mm3: float = 1e-6,
) -> InterferenceReport:
    """Analyze pairwise collision and clearance conditions."""
    if minimum_clearance_mm < 0:
        raise ValueError("minimum_clearance_mm must not be negative")

    if collision_volume_tolerance_mm3 < 0:
        raise ValueError("collision_volume_tolerance_mm3 must not be negative")

    resolved_components = tuple(components)

    identifiers = tuple(component.identifier for component in resolved_components)

    if len(set(identifiers)) != len(identifiers):
        raise ValueError("component identifiers must be unique")

    allowed_pairs = frozenset(frozenset(pair) for pair in allowed_contact_pairs)

    findings: list[InterferenceFinding] = []

    transformed = {
        component.identifier: (component.transformed_geometry().val())
        for component in resolved_components
    }

    for first, second in combinations(
        resolved_components,
        2,
    ):
        pair = component_pair(
            first.identifier,
            second.identifier,
        )

        first_shape = transformed[first.identifier]
        second_shape = transformed[second.identifier]

        first_bounds = first_shape.BoundingBox()
        second_bounds = second_shape.BoundingBox()

        intersection_volume_mm3 = 0.0

        if _bounding_boxes_overlap(
            first_bounds,
            second_bounds,
        ):
            intersection_volume_mm3 = _intersection_volume_mm3(
                first_shape,
                second_shape,
            )

        if intersection_volume_mm3 > collision_volume_tolerance_mm3:
            if pair not in allowed_pairs:
                findings.append(
                    InterferenceFinding(
                        first_identifier=(first.identifier),
                        second_identifier=(second.identifier),
                        kind="collision",
                        intersection_volume_mm3=(intersection_volume_mm3),
                    )
                )

            continue

        measured_clearance_mm = _bounding_box_clearance_mm(
            first_bounds,
            second_bounds,
        )

        has_envelope = (
            first.clearance_envelope.has_clearance
            or second.clearance_envelope.has_clearance
        )

        if (
            has_envelope
            and pair not in allowed_pairs
            and _expanded_bounds_overlap(
                first_bounds,
                first,
                second_bounds,
                second,
            )
        ):
            findings.append(
                InterferenceFinding(
                    first_identifier=first.identifier,
                    second_identifier=second.identifier,
                    kind="clearance",
                    required_clearance_mm=(
                        _envelope_required_clearance_mm(
                            first_bounds,
                            first,
                            second_bounds,
                            second,
                        )
                    ),
                    measured_clearance_mm=(measured_clearance_mm),
                    clearance_source="envelope",
                )
            )

            continue

        if minimum_clearance_mm <= 0:
            continue

        if measured_clearance_mm < minimum_clearance_mm and pair not in allowed_pairs:
            findings.append(
                InterferenceFinding(
                    first_identifier=first.identifier,
                    second_identifier=second.identifier,
                    kind="clearance",
                    required_clearance_mm=(minimum_clearance_mm),
                    measured_clearance_mm=(measured_clearance_mm),
                    clearance_source="minimum",
                )
            )

    return InterferenceReport(findings=tuple(findings))

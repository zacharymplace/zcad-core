from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import hypot

_MINIMUM_LOCATION_SEPARATION_MM = 1e-6


@dataclass(frozen=True)
class SnapShellPolicy:
    """Manufacturing and engagement policy for a snap-fit shell.

    Unlike corner capture and edge clip, this strategy does not restrain
    a PCB inside an enclosure; it retains a printed shell against a
    sealed external device (see
    :class:`~zcad_core.retention.snap_shell.SnapShellParameters`). Each
    clip cantilevers up from the shell floor and hooks its lip against
    the device body with ``overhang_mm`` of engagement.
    """

    clip_width_mm: float = 3.0
    wall_mm: float = 1.0
    clip_height_mm: float = 1.5
    overhang_mm: float = 0.6
    clearance_mm: float = 0.15
    compliant_span_mm: float = 2.0

    def __post_init__(self) -> None:
        positive_fields = {
            "clip_width_mm": self.clip_width_mm,
            "wall_mm": self.wall_mm,
            "clip_height_mm": self.clip_height_mm,
            "overhang_mm": self.overhang_mm,
            "compliant_span_mm": self.compliant_span_mm,
        }

        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        if self.clearance_mm < 0:
            raise ValueError("clearance_mm cannot be negative")

        if self.overhang_mm >= self.compliant_span_mm:
            raise ValueError("overhang_mm must be less than compliant_span_mm")


@dataclass(frozen=True)
class SnapShellLocation:
    """One snap-clip location on a shell floor, in absolute XY coordinates.

    ``rotation_degrees`` orients the clip's lip to face the device
    perimeter at this point, matching
    :attr:`~zcad_core.features.snap_retention.SnapRetentionClipParameters.rotation_degrees`.
    """

    label: str
    x_mm: float
    y_mm: float
    rotation_degrees: float = 0.0

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("label cannot be empty")


@dataclass(frozen=True)
class SnapShellParameters:
    """Derived geometry artifact for one snap-shell layout.

    At least three locations are required: two clips can hold a device
    against lift-off but cannot resist it rocking about the line between
    them, the same rotational gap edge clip's two-point capture has
    along its single edge. A third, non-collinear clip is the minimum
    needed for the shell to resist rotation in every direction.
    """

    device_thickness_mm: float
    locations: tuple[SnapShellLocation, ...]
    clip_width_mm: float
    wall_mm: float
    clip_height_mm: float
    overhang_mm: float
    clearance_mm: float
    compliant_span_mm: float

    def __post_init__(self) -> None:
        if self.device_thickness_mm <= 0:
            raise ValueError("device_thickness_mm must be positive")

        if len(self.locations) < 3:
            raise ValueError("Snap shell requires at least three locations")

        labels = tuple(location.label for location in self.locations)

        if len(set(labels)) != len(labels):
            raise ValueError("Snap shell location labels must be unique")

        for first, second in combinations(self.locations, 2):
            distance = hypot(
                first.x_mm - second.x_mm,
                first.y_mm - second.y_mm,
            )

            if distance < _MINIMUM_LOCATION_SEPARATION_MM:
                raise ValueError("Snap shell locations must not overlap")


def as_snap_shell_parameters(
    value: object,
) -> SnapShellParameters:
    """Narrow a generic retention-execution value to snap-shell parameters."""

    if not isinstance(value, SnapShellParameters):
        raise TypeError("Expected SnapShellParameters from the retention execution")

    return value


def derive_snap_shell_parameters(
    *,
    device_thickness_mm: float,
    locations: tuple[SnapShellLocation, ...],
    policy: SnapShellPolicy,
) -> SnapShellParameters:
    """Derive a validated snap-shell geometry artifact."""

    return SnapShellParameters(
        device_thickness_mm=device_thickness_mm,
        locations=locations,
        clip_width_mm=policy.clip_width_mm,
        wall_mm=policy.wall_mm,
        clip_height_mm=policy.clip_height_mm,
        overhang_mm=policy.overhang_mm,
        clearance_mm=policy.clearance_mm,
        compliant_span_mm=policy.compliant_span_mm,
    )

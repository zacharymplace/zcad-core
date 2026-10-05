from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from zcad_core.hardware.wearables.capture import EdgeFeature
from zcad_core.retention.snap_shell import (
    SnapShellLocation,
    SnapShellParameters,
    SnapShellPolicy,
)


@dataclass(frozen=True)
class SnapShellRequest:
    """Validated input required to derive snap-shell geometry: the device's
    size and corner radius, the points on its edges where clips hold it, and
    the features on its edges the shell must leave open."""

    device_thickness_mm: float
    device_length_mm: float
    device_width_mm: float
    locations: tuple[SnapShellLocation, ...]
    policy: SnapShellPolicy
    edge_features: tuple[EdgeFeature, ...] = ()
    device_corner_radius_mm: float = 0.0

    def __post_init__(self) -> None:
        for name, value in {
            "device_thickness_mm": self.device_thickness_mm,
            "device_length_mm": self.device_length_mm,
            "device_width_mm": self.device_width_mm,
        }.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        if len(self.locations) < 3:
            raise ValueError("Snap shell requires at least three locations")


class SnapShellFitCheck(str, Enum):
    """Required verification dimensions for a snap-fit shell.

    There is no check named after corner capture's ``planar_restraint``:
    a snap shell restrains a sealed external device from the outside,
    not a PCB seated inside an enclosure, so the guarantee it can offer
    is closer to edge clip's - discrete anchor points around a
    perimeter - than to corner capture's bilateral diagonal restraint.
    """

    SHELL_MATERIAL_CONTINUITY = "shell_material_continuity"
    SNAP_ENGAGEMENT = "snap_engagement"
    ANCHOR_SEPARATION = "anchor_separation"
    DEVICE_CLEARANCE = "device_clearance"
    MANUFACTURING_CLEARANCE = "manufacturing_clearance"
    CLIP_STRAIN = "clip_strain"


@dataclass(frozen=True)
class SnapShellFitResult:
    """Outcome of one required fit check."""

    check: SnapShellFitCheck
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("Fit-result detail cannot be empty")


@dataclass(frozen=True)
class SnapShellFitReport:
    """Complete verification report for a derived snap-shell layout."""

    results: tuple[SnapShellFitResult, ...]

    def __post_init__(self) -> None:
        checks = tuple(result.check for result in self.results)

        if len(set(checks)) != len(checks):
            raise ValueError("Fit report cannot contain duplicate checks")

    @property
    def passed(self) -> bool:
        required = set(SnapShellFitCheck)
        observed = {result.check for result in self.results}

        return observed == required and all(result.passed for result in self.results)

    @property
    def failures(
        self,
    ) -> tuple[SnapShellFitResult, ...]:
        return tuple(result for result in self.results if not result.passed)


@runtime_checkable
class SnapShellBackend(Protocol):
    """Backend lifecycle for one snap-shell implementation."""

    def derive(
        self,
        request: SnapShellRequest,
    ) -> SnapShellParameters:
        """Derive validated strategy parameters."""

        ...

    def apply(
        self,
        model: object,
        parameters: SnapShellParameters,
    ) -> object:
        """Apply snap-shell geometry to a model."""

        ...

    def analyze_fit(
        self,
        parameters: SnapShellParameters,
    ) -> SnapShellFitReport:
        """Verify the derived geometry against all required gates."""

        ...


def as_snap_shell_fit_report(
    report: object,
) -> SnapShellFitReport:
    """Narrow a generic retention fit report to its snap-shell form."""

    if not isinstance(report, SnapShellFitReport):
        raise TypeError("Expected SnapShellFitReport from the retention execution")

    return report

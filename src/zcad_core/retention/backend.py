from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from zcad_core.retention.corner_capture import (
    CornerCaptureLocation,
    CornerCaptureParameters,
    CornerCapturePolicy,
)


@dataclass(frozen=True)
class CornerCaptureRequest:
    """Validated input required to derive corner-capture geometry."""

    board_thickness_mm: float
    locations: tuple[CornerCaptureLocation, ...]
    policy: CornerCapturePolicy

    def __post_init__(self) -> None:
        if self.board_thickness_mm <= 0:
            raise ValueError("board_thickness_mm must be positive")

        if len(self.locations) < 2:
            raise ValueError("Corner capture requires at least two locations")


class CornerCaptureFitCheck(str, Enum):
    """Required verification dimensions for corner capture."""

    PLANAR_RESTRAINT = "planar_restraint"
    VERTICAL_RETENTION = "vertical_retention"
    COMPONENT_CLEARANCE = "component_clearance"
    INSTALLATION_PATH = "installation_path"
    MANUFACTURING_CLEARANCE = "manufacturing_clearance"


@dataclass(frozen=True)
class CornerCaptureFitResult:
    """Outcome of one required fit check."""

    check: CornerCaptureFitCheck
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("Fit-result detail cannot be empty")


@dataclass(frozen=True)
class CornerCaptureFitReport:
    """Complete verification report for derived corner capture."""

    results: tuple[CornerCaptureFitResult, ...]

    def __post_init__(self) -> None:
        checks = tuple(result.check for result in self.results)

        if len(set(checks)) != len(checks):
            raise ValueError("Fit report cannot contain duplicate checks")

    @property
    def passed(self) -> bool:
        required = set(CornerCaptureFitCheck)
        observed = {result.check for result in self.results}

        return observed == required and all(result.passed for result in self.results)

    @property
    def failures(
        self,
    ) -> tuple[CornerCaptureFitResult, ...]:
        return tuple(result for result in self.results if not result.passed)


def as_corner_capture_fit_report(
    report: object,
) -> CornerCaptureFitReport:
    """Narrow a generic retention fit report to its corner-capture form."""

    if not isinstance(report, CornerCaptureFitReport):
        raise TypeError("Expected CornerCaptureFitReport from the retention execution")

    return report


@runtime_checkable
class CornerCaptureBackend(Protocol):
    """Backend lifecycle for one corner-capture implementation."""

    def derive(
        self,
        request: CornerCaptureRequest,
    ) -> CornerCaptureParameters:
        """Derive validated strategy parameters."""

        ...

    def apply(
        self,
        model: object,
        parameters: CornerCaptureParameters,
    ) -> object:
        """Apply corner-capture geometry to a model."""

        ...

    def analyze_fit(
        self,
        parameters: CornerCaptureParameters,
    ) -> CornerCaptureFitReport:
        """Verify the derived geometry against all required gates."""

        ...

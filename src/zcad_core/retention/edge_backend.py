from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from zcad_core.retention.edge_capture import (
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    EdgeCapturePolicy,
)


@dataclass(frozen=True)
class EdgeCaptureRequest:
    """Validated input required to derive edge-capture geometry."""

    board_thickness_mm: float
    locations: tuple[EdgeCaptureLocation, ...]
    policy: EdgeCapturePolicy

    def __post_init__(self) -> None:
        if self.board_thickness_mm <= 0:
            raise ValueError("board_thickness_mm must be positive")

        if len(self.locations) < 2:
            raise ValueError("Edge capture requires at least two locations")


class EdgeCaptureFitCheck(str, Enum):
    """Required verification dimensions for edge capture.

    There is deliberately no check named after corner capture's
    ``planar_restraint``: as documented on
    :class:`~zcad_core.retention.edge_capture.EdgeCaptureParameters`, this
    strategy does not provide the same bilateral restraint a diagonal
    corner pair does. ``ANCHOR_SEPARATION`` verifies only what this
    geometry actually guarantees - two capture points spread far enough
    apart to resist rotation about the vertical axis.
    """

    EDGE_MATERIAL_CONTINUITY = "edge_material_continuity"
    VERTICAL_RETENTION = "vertical_retention"
    ANCHOR_SEPARATION = "anchor_separation"
    COMPONENT_CLEARANCE = "component_clearance"
    MANUFACTURING_CLEARANCE = "manufacturing_clearance"


@dataclass(frozen=True)
class EdgeCaptureFitResult:
    """Outcome of one required fit check."""

    check: EdgeCaptureFitCheck
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.detail.strip():
            raise ValueError("Fit-result detail cannot be empty")


@dataclass(frozen=True)
class EdgeCaptureFitReport:
    """Complete verification report for derived edge capture."""

    results: tuple[EdgeCaptureFitResult, ...]

    def __post_init__(self) -> None:
        checks = tuple(result.check for result in self.results)

        if len(set(checks)) != len(checks):
            raise ValueError("Fit report cannot contain duplicate checks")

    @property
    def passed(self) -> bool:
        required = set(EdgeCaptureFitCheck)
        observed = {result.check for result in self.results}

        return observed == required and all(result.passed for result in self.results)

    @property
    def failures(
        self,
    ) -> tuple[EdgeCaptureFitResult, ...]:
        return tuple(result for result in self.results if not result.passed)


@runtime_checkable
class EdgeCaptureBackend(Protocol):
    """Backend lifecycle for one edge-capture implementation."""

    def derive(
        self,
        request: EdgeCaptureRequest,
    ) -> EdgeCaptureParameters:
        """Derive validated strategy parameters."""

        ...

    def apply(
        self,
        model: object,
        parameters: EdgeCaptureParameters,
    ) -> object:
        """Apply edge-capture geometry to a model."""

        ...

    def analyze_fit(
        self,
        parameters: EdgeCaptureParameters,
    ) -> EdgeCaptureFitReport:
        """Verify the derived geometry against all required gates."""

        ...


def as_edge_capture_fit_report(
    report: object,
) -> EdgeCaptureFitReport:
    """Narrow a generic retention fit report to its edge-capture form."""

    if not isinstance(report, EdgeCaptureFitReport):
        raise TypeError("Expected EdgeCaptureFitReport from the retention execution")

    return report

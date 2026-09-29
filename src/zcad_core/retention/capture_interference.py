"""Capture-geometry interference with the production board.

Corner capture and edge clip both gate generation on this one measurement,
so a fix to how interference is measured reaches both strategies.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.geometry.intersection import intersection_volume
from zcad_core.retention.production_board import ProductionBoardModel


@dataclass(frozen=True)
class GeometryInterferenceResult:
    """Intersection measurements for one production execution."""

    pcb_capture_intersection_mm3: float
    component_capture_intersection_mm3: float
    tolerance_mm3: float = 1e-6

    @property
    def passed(self) -> bool:
        """Whether captures avoid PCB and component material."""

        return (
            self.pcb_capture_intersection_mm3 <= self.tolerance_mm3
            and self.component_capture_intersection_mm3 <= self.tolerance_mm3
        )


def measure_capture_interference(
    capture: cq.Shape,
    board_model: ProductionBoardModel,
    *,
    tolerance_mm3: float = 1e-6,
) -> GeometryInterferenceResult:
    """Fail-closed overlap of capture geometry with the PCB and its components."""

    if capture.isNull():
        raise ValueError("Production execution contains no capture geometry")

    return GeometryInterferenceResult(
        pcb_capture_intersection_mm3=intersection_volume(capture, board_model.pcb),
        component_capture_intersection_mm3=sum(
            intersection_volume(capture, component)
            for component in board_model.component_solids
        ),
        tolerance_mm3=tolerance_mm3,
    )

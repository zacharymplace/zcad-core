from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.backend import (
    CornerCaptureRequest,
)
from zcad_core.retention.corner_capture import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCapturePolicy,
)


@dataclass(frozen=True)
class ProductionBoardModel:
    """Imported production-board geometry and PCB identity."""

    source_step: Path
    pcb_solid_index: int
    shape: cq.Shape
    pcb: cq.Solid
    component_solids: tuple[cq.Solid, ...]

    def __post_init__(self) -> None:
        if self.pcb_solid_index < 1:
            raise ValueError("pcb_solid_index must be one-based and positive")


@dataclass(frozen=True)
class CornerClearanceResult:
    """Component-clearance result for one board corner."""

    corner: BoardCorner
    clear: bool
    interfering_solid_indices: tuple[int, ...]


@dataclass(frozen=True)
class ProductionCornerDerivation:
    """Evidence-derived corner-capture request and audit results."""

    request: CornerCaptureRequest
    clearances: tuple[CornerClearanceResult, ...]
    selected_corners: tuple[BoardCorner, ...]


class ProductionBoardCornerAdapter:
    """Derive corner-capture input from production STEP evidence."""

    def __init__(
        self,
        *,
        corner_keepout_mm: float = 4.0,
        vertical_margin_mm: float = 0.10,
    ) -> None:
        if corner_keepout_mm <= 0:
            raise ValueError("corner_keepout_mm must be positive")

        if vertical_margin_mm < 0:
            raise ValueError("vertical_margin_mm cannot be negative")

        self._corner_keepout_mm = corner_keepout_mm
        self._vertical_margin_mm = vertical_margin_mm

    def import_model(
        self,
        *,
        source_step: Path,
        pcb_solid_index: int,
    ) -> ProductionBoardModel:
        """Import a STEP model and identify its PCB solid."""

        if pcb_solid_index < 1:
            raise ValueError("pcb_solid_index must be one-based and positive")

        shape = workplane_shape(cq.importers.importStep(str(source_step)))

        if shape.isNull():
            raise ValueError("STEP model contains no shape")

        solids = tuple(shape.Solids())

        if pcb_solid_index > len(solids):
            raise ValueError("pcb_solid_index exceeds imported solid count")

        pcb = solids[pcb_solid_index - 1]

        components = tuple(
            solid
            for index, solid in enumerate(
                solids,
                start=1,
            )
            if index != pcb_solid_index
        )

        return ProductionBoardModel(
            source_step=source_step,
            pcb_solid_index=pcb_solid_index,
            shape=shape,
            pcb=pcb,
            component_solids=components,
        )

    def analyze_corner_clearance(
        self,
        model: ProductionBoardModel,
    ) -> tuple[CornerClearanceResult, ...]:
        """Check modeled components against each PCB corner."""

        pcb_bounds = model.pcb.BoundingBox()
        pcb_top_z = pcb_bounds.zmax

        results: list[CornerClearanceResult] = []

        for corner in BoardCorner:
            x_min, x_max, y_min, y_max = self._corner_region(
                corner=corner,
                x_min=pcb_bounds.xmin,
                x_max=pcb_bounds.xmax,
                y_min=pcb_bounds.ymin,
                y_max=pcb_bounds.ymax,
            )

            interfering: list[int] = []

            for component_index, solid in enumerate(
                model.component_solids,
                start=1,
            ):
                bounds = solid.BoundingBox()

                overlaps_x = bounds.xmax > x_min and bounds.xmin < x_max
                overlaps_y = bounds.ymax > y_min and bounds.ymin < y_max
                reaches_board_top = bounds.zmax > pcb_top_z + self._vertical_margin_mm

                if overlaps_x and overlaps_y and reaches_board_top:
                    interfering.append(component_index)

            results.append(
                CornerClearanceResult(
                    corner=corner,
                    clear=not interfering,
                    interfering_solid_indices=tuple(interfering),
                )
            )

        return tuple(results)

    def derive(
        self,
        *,
        model: ProductionBoardModel,
        policy: CornerCapturePolicy,
    ) -> ProductionCornerDerivation:
        """Derive a balanced clear-corner request."""

        clearances = self.analyze_corner_clearance(model)

        clear_corners = {result.corner for result in clearances if result.clear}

        selected = self._select_diagonal_pair(clear_corners)

        if selected is None:
            raise ValueError(
                "Production board does not have two component-clear diagonal corners"
            )

        bounds = model.pcb.BoundingBox()

        locations = tuple(
            self._location_for_corner(
                corner=corner,
                x_min=bounds.xmin,
                x_max=bounds.xmax,
                y_min=bounds.ymin,
                y_max=bounds.ymax,
            )
            for corner in selected
        )

        return ProductionCornerDerivation(
            request=CornerCaptureRequest(
                board_thickness_mm=(bounds.zlen),
                locations=locations,
                policy=policy,
            ),
            clearances=clearances,
            selected_corners=selected,
        )

    def _corner_region(
        self,
        *,
        corner: BoardCorner,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> tuple[float, float, float, float]:
        keepout = self._corner_keepout_mm

        if corner in {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
        }:
            region_x_min = x_min
            region_x_max = x_min + keepout
        else:
            region_x_min = x_max - keepout
            region_x_max = x_max

        if corner in {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
        }:
            region_y_min = y_min
            region_y_max = y_min + keepout
        else:
            region_y_min = y_max - keepout
            region_y_max = y_max

        return (
            region_x_min,
            region_x_max,
            region_y_min,
            region_y_max,
        )

    @staticmethod
    def _select_diagonal_pair(
        clear_corners: set[BoardCorner],
    ) -> tuple[BoardCorner, BoardCorner] | None:
        candidates = (
            (
                BoardCorner.NEGATIVE_X_NEGATIVE_Y,
                BoardCorner.POSITIVE_X_POSITIVE_Y,
            ),
            (
                BoardCorner.NEGATIVE_X_POSITIVE_Y,
                BoardCorner.POSITIVE_X_NEGATIVE_Y,
            ),
        )

        for first, second in candidates:
            if {
                first,
                second,
            }.issubset(clear_corners):
                return first, second

        return None

    @staticmethod
    def _location_for_corner(
        *,
        corner: BoardCorner,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> CornerCaptureLocation:
        x_mm = (
            x_min
            if corner
            in {
                BoardCorner.NEGATIVE_X_NEGATIVE_Y,
                BoardCorner.NEGATIVE_X_POSITIVE_Y,
            }
            else x_max
        )
        y_mm = (
            y_min
            if corner
            in {
                BoardCorner.NEGATIVE_X_NEGATIVE_Y,
                BoardCorner.POSITIVE_X_NEGATIVE_Y,
            }
            else y_max
        )

        return CornerCaptureLocation(
            corner=corner,
            x_mm=x_mm,
            y_mm=y_mm,
        )

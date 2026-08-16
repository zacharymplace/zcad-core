from __future__ import annotations

import cadquery as cq

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_backend import (
    EdgeCaptureFitCheck,
    EdgeCaptureFitReport,
    EdgeCaptureFitResult,
    EdgeCaptureRequest,
)
from zcad_core.retention.edge_capture import (
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    derive_edge_capture_parameters,
)

_Y_EDGES = (BoardEdge.NEGATIVE_Y, BoardEdge.POSITIVE_Y)
_OUTWARD_SIGN = {
    BoardEdge.NEGATIVE_X: -1.0,
    BoardEdge.POSITIVE_X: 1.0,
    BoardEdge.NEGATIVE_Y: -1.0,
    BoardEdge.POSITIVE_Y: 1.0,
}


class SyntheticEdgeCaptureBackend:
    """CadQuery backend for synthetic edge-capture fixtures.

    Builds one wall-and-ledge feature per :class:`EdgeCaptureLocation` -
    see :class:`~zcad_core.retention.edge_capture.EdgeCaptureParameters`
    for the mechanical scope this geometry actually provides. This backend
    validates the retention lifecycle against simple, axis-aligned
    synthetic board coordinates. It does not establish component clearance
    for a production board.
    """

    def derive(
        self,
        request: EdgeCaptureRequest,
    ) -> EdgeCaptureParameters:
        """Derive validated edge-capture parameters."""

        return derive_edge_capture_parameters(
            board_thickness_mm=(request.board_thickness_mm),
            locations=request.locations,
            policy=request.policy,
        )

    def apply(
        self,
        model: object,
        parameters: EdgeCaptureParameters,
    ) -> object:
        """Union synthetic edge-capture geometry into a model."""

        if not isinstance(model, cq.Workplane):
            raise TypeError(
                "SyntheticEdgeCaptureBackend requires a cadquery.Workplane model"
            )

        return model.union(self.build_geometry(parameters))

    def build_geometry(
        self,
        parameters: EdgeCaptureParameters,
    ) -> cq.Workplane:
        """Build capture-only geometry without a board model."""

        captures = tuple(
            self._build_capture(
                parameters=parameters,
                location=location,
            )
            for location in parameters.locations
        )

        if not captures:
            raise ValueError("Edge capture requires geometry locations")

        result = captures[0]

        for capture in captures[1:]:
            result = result.union(capture)

        return result

    def analyze_fit(
        self,
        parameters: EdgeCaptureParameters,
    ) -> EdgeCaptureFitReport:
        """Evaluate deterministic synthetic fit gates.

        ``edge_material_continuity`` and ``component_clearance`` cannot be
        verified from parameters alone - they depend on a real board.
        Synthetic evaluation reports them as unverified placeholders;
        production execution (see
        :mod:`zcad_core.retention.production_edge_execution`) replaces
        both with evidence from the actual STEP model.
        """

        vertical_passed = (
            parameters.vertical_overlap_mm > 0 and parameters.engagement_depth_mm > 0
        )

        manufacturing_passed = (
            parameters.board_clearance_mm >= 0.10
            and parameters.minimum_wall_mm >= 0.80
            and parameters.arm_width_mm > 2.0 * parameters.board_clearance_mm
        )

        anchor_passed = self._anchor_separation_passed(parameters)

        return EdgeCaptureFitReport(
            results=(
                EdgeCaptureFitResult(
                    check=(EdgeCaptureFitCheck.EDGE_MATERIAL_CONTINUITY),
                    passed=True,
                    detail=(
                        "Synthetic fixture assumes continuous PCB material "
                        "at each capture location; production evidence is "
                        "required to confirm."
                    ),
                ),
                EdgeCaptureFitResult(
                    check=(EdgeCaptureFitCheck.VERTICAL_RETENTION),
                    passed=vertical_passed,
                    detail=(
                        "Positive synthetic ledge overlap is present."
                        if vertical_passed
                        else "Positive vertical overlap and "
                        "engagement depth are required."
                    ),
                ),
                EdgeCaptureFitResult(
                    check=(EdgeCaptureFitCheck.ANCHOR_SEPARATION),
                    passed=anchor_passed,
                    detail=(
                        "Capture locations are spread apart enough to "
                        "resist rotation about the vertical axis."
                        if anchor_passed
                        else "Capture locations must be spread apart by "
                        "at least one arm width."
                    ),
                ),
                EdgeCaptureFitResult(
                    check=(EdgeCaptureFitCheck.COMPONENT_CLEARANCE),
                    passed=True,
                    detail=(
                        "Synthetic fixture contains no modeled board "
                        "components; production clearance remains "
                        "unverified."
                    ),
                ),
                EdgeCaptureFitResult(
                    check=(EdgeCaptureFitCheck.MANUFACTURING_CLEARANCE),
                    passed=manufacturing_passed,
                    detail=(
                        "Synthetic clearance and minimum-wall thresholds pass."
                        if manufacturing_passed
                        else "Synthetic clearance or minimum-wall thresholds fail."
                    ),
                ),
            )
        )

    @staticmethod
    def _anchor_separation_passed(
        parameters: EdgeCaptureParameters,
    ) -> bool:
        by_edge: dict[BoardEdge, list[float]] = {}

        for location in parameters.locations:
            by_edge.setdefault(location.edge, []).append(location.position_mm)

        for positions in by_edge.values():
            if len(positions) < 2:
                continue

            ordered = sorted(positions)

            if ordered[-1] - ordered[0] < parameters.arm_width_mm:
                return False

        return True

    def _build_capture(
        self,
        *,
        parameters: EdgeCaptureParameters,
        location: EdgeCaptureLocation,
    ) -> cq.Workplane:
        arm_width = parameters.arm_width_mm
        engagement = parameters.engagement_depth_mm
        clearance = parameters.board_clearance_mm
        wall = parameters.minimum_wall_mm

        wall_height = (
            parameters.board_thickness_mm
            + clearance
            + parameters.vertical_overlap_mm
            + wall
        )

        outward = _OUTWARD_SIGN[location.edge]
        wall_perpendicular_center = location.edge_coordinate_mm + outward * (
            clearance + wall / 2.0
        )
        ledge_perpendicular_center = location.edge_coordinate_mm - outward * (
            engagement / 2.0
        )

        if location.edge in _Y_EDGES:
            wall_x_length, wall_y_length = arm_width, wall
            wall_x_center, wall_y_center = (
                location.position_mm,
                wall_perpendicular_center,
            )
            ledge_x_length, ledge_y_length = arm_width, engagement
            ledge_x_center, ledge_y_center = (
                location.position_mm,
                ledge_perpendicular_center,
            )
        else:
            wall_x_length, wall_y_length = wall, arm_width
            wall_x_center, wall_y_center = (
                wall_perpendicular_center,
                location.position_mm,
            )
            ledge_x_length, ledge_y_length = engagement, arm_width
            ledge_x_center, ledge_y_center = (
                ledge_perpendicular_center,
                location.position_mm,
            )

        wall_shape = (
            cq.Workplane("XY")
            .box(
                wall_x_length,
                wall_y_length,
                wall_height,
            )
            .translate(
                (
                    wall_x_center,
                    wall_y_center,
                    wall_height / 2.0,
                )
            )
        )

        ledge = (
            cq.Workplane("XY")
            .box(
                ledge_x_length,
                ledge_y_length,
                wall,
            )
            .translate(
                (
                    ledge_x_center,
                    ledge_y_center,
                    wall_height - wall / 2.0,
                )
            )
        )

        return wall_shape.union(ledge)

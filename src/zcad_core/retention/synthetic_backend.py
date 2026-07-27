from __future__ import annotations

import cadquery as cq

from zcad_core.retention.backend import (
    CornerCaptureFitCheck,
    CornerCaptureFitReport,
    CornerCaptureFitResult,
    CornerCaptureRequest,
)
from zcad_core.retention.corner_capture import (
    BoardCorner,
    CornerCaptureParameters,
    derive_corner_capture_parameters,
)


class SyntheticCornerCaptureBackend:
    """CadQuery backend for synthetic corner-capture fixtures.

    This backend validates the retention lifecycle against simple,
    axis-aligned synthetic board coordinates. It does not establish
    component clearance for a production board.
    """

    def derive(
        self,
        request: CornerCaptureRequest,
    ) -> CornerCaptureParameters:
        """Derive validated corner-capture parameters."""

        return derive_corner_capture_parameters(
            board_thickness_mm=(request.board_thickness_mm),
            locations=request.locations,
            policy=request.policy,
        )

    def apply(
        self,
        model: object,
        parameters: CornerCaptureParameters,
    ) -> object:
        """Union synthetic corner-capture geometry into a model."""

        if not isinstance(model, cq.Workplane):
            raise TypeError(
                "SyntheticCornerCaptureBackend requires a cadquery.Workplane model"
            )

        return model.union(self.build_geometry(parameters))

    def build_geometry(
        self,
        parameters: CornerCaptureParameters,
    ) -> cq.Workplane:
        """Build capture-only geometry without a board model."""

        captures = tuple(
            self._build_capture(
                parameters=parameters,
                corner=location.corner,
                x_mm=location.x_mm,
                y_mm=location.y_mm,
            )
            for location in parameters.locations
        )

        if not captures:
            raise ValueError("Corner capture requires geometry locations")

        result = captures[0]

        for capture in captures[1:]:
            result = result.union(capture)

        return result

    def analyze_fit(
        self,
        parameters: CornerCaptureParameters,
    ) -> CornerCaptureFitReport:
        """Evaluate deterministic synthetic fit gates."""

        corners = {location.corner for location in parameters.locations}

        planar_passed = self._has_both_x_sides(corners) and self._has_both_y_sides(
            corners
        )

        vertical_passed = (
            parameters.vertical_overlap_mm > 0 and parameters.engagement_depth_mm > 0
        )

        manufacturing_passed = (
            parameters.board_clearance_mm >= 0.10
            and parameters.minimum_wall_mm >= 0.80
            and parameters.arm_width_mm > 2.0 * parameters.board_clearance_mm
        )

        installation_passed = len(corners) < 4

        return CornerCaptureFitReport(
            results=(
                CornerCaptureFitResult(
                    check=(CornerCaptureFitCheck.PLANAR_RESTRAINT),
                    passed=planar_passed,
                    detail=(
                        "Capture locations oppose translation "
                        "along both board-plane axes."
                        if planar_passed
                        else "Capture locations do not oppose "
                        "translation along both axes."
                    ),
                ),
                CornerCaptureFitResult(
                    check=(CornerCaptureFitCheck.VERTICAL_RETENTION),
                    passed=vertical_passed,
                    detail=(
                        "Positive synthetic upper overlap is present."
                        if vertical_passed
                        else "Positive vertical overlap and "
                        "engagement depth are required."
                    ),
                ),
                CornerCaptureFitResult(
                    check=(CornerCaptureFitCheck.COMPONENT_CLEARANCE),
                    passed=True,
                    detail=(
                        "Synthetic fixture contains no modeled "
                        "board components; production clearance "
                        "remains unverified."
                    ),
                ),
                CornerCaptureFitResult(
                    check=(CornerCaptureFitCheck.INSTALLATION_PATH),
                    passed=installation_passed,
                    detail=(
                        "At least one board corner remains open "
                        "for synthetic insertion."
                        if installation_passed
                        else "All four corners are captured; no "
                        "synthetic insertion path remains."
                    ),
                ),
                CornerCaptureFitResult(
                    check=(CornerCaptureFitCheck.MANUFACTURING_CLEARANCE),
                    passed=manufacturing_passed,
                    detail=(
                        "Synthetic clearance and minimum-wall thresholds pass."
                        if manufacturing_passed
                        else "Synthetic clearance or minimum-wall thresholds fail."
                    ),
                ),
            )
        )

    def _build_capture(
        self,
        *,
        parameters: CornerCaptureParameters,
        corner: BoardCorner,
        x_mm: float,
        y_mm: float,
    ) -> cq.Workplane:
        x_sign, y_sign = self._corner_signs(corner)

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

        x_wall_center_x = x_mm + x_sign * (clearance + wall / 2.0)
        x_wall_center_y = y_mm - y_sign * (arm_width + engagement) / 2.0

        y_wall_center_x = x_mm - x_sign * (arm_width + engagement) / 2.0
        y_wall_center_y = y_mm + y_sign * (clearance + wall / 2.0)

        x_wall = (
            cq.Workplane("XY")
            .box(
                wall,
                arm_width + engagement,
                wall_height,
            )
            .translate(
                (
                    x_wall_center_x,
                    x_wall_center_y,
                    wall_height / 2.0,
                )
            )
        )

        y_wall = (
            cq.Workplane("XY")
            .box(
                arm_width + engagement,
                wall,
                wall_height,
            )
            .translate(
                (
                    y_wall_center_x,
                    y_wall_center_y,
                    wall_height / 2.0,
                )
            )
        )

        ledge_center_x = x_mm - x_sign * arm_width / 2.0
        ledge_center_y = y_mm - y_sign * arm_width / 2.0
        ledge_center_z = (
            parameters.board_thickness_mm
            + clearance
            + parameters.vertical_overlap_mm
            + wall / 2.0
        )

        ledge = (
            cq.Workplane("XY")
            .box(
                arm_width + clearance,
                arm_width + clearance,
                wall,
            )
            .translate(
                (
                    ledge_center_x,
                    ledge_center_y,
                    ledge_center_z,
                )
            )
        )

        return x_wall.union(y_wall).union(ledge)

    @staticmethod
    def _corner_signs(
        corner: BoardCorner,
    ) -> tuple[int, int]:
        mapping = {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y: (
                -1,
                -1,
            ),
            BoardCorner.NEGATIVE_X_POSITIVE_Y: (
                -1,
                1,
            ),
            BoardCorner.POSITIVE_X_NEGATIVE_Y: (
                1,
                -1,
            ),
            BoardCorner.POSITIVE_X_POSITIVE_Y: (
                1,
                1,
            ),
        }

        return mapping[corner]

    @staticmethod
    def _has_both_x_sides(
        corners: set[BoardCorner],
    ) -> bool:
        negative = {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
        }
        positive = {
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
            BoardCorner.POSITIVE_X_POSITIVE_Y,
        }

        return bool(corners & negative) and bool(corners & positive)

    @staticmethod
    def _has_both_y_sides(
        corners: set[BoardCorner],
    ) -> bool:
        negative = {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
        }
        positive = {
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
            BoardCorner.POSITIVE_X_POSITIVE_Y,
        }

        return bool(corners & negative) and bool(corners & positive)

from __future__ import annotations

from itertools import combinations
from math import hypot

import cadquery as cq

from zcad_core.features.snap_retention import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)
from zcad_core.retention.snap_shell import (
    SnapShellLocation,
    SnapShellParameters,
    derive_snap_shell_parameters,
)
from zcad_core.retention.snap_shell_backend import (
    SnapShellFitCheck,
    SnapShellFitReport,
    SnapShellFitResult,
    SnapShellRequest,
)


class SyntheticSnapShellBackend:
    """CadQuery backend for synthetic snap-shell fixtures.

    Builds one reusable printed snap-retention clip (see
    :func:`~zcad_core.features.snap_retention.add_snap_retention_clip`)
    per :class:`~zcad_core.retention.snap_shell.SnapShellLocation`. This
    backend validates the retention lifecycle against simple, synthetic
    device coordinates. It does not establish clearance against a real
    device's internals.
    """

    def derive(
        self,
        request: SnapShellRequest,
    ) -> SnapShellParameters:
        """Derive validated snap-shell parameters."""

        return derive_snap_shell_parameters(
            device_thickness_mm=request.device_thickness_mm,
            locations=request.locations,
            policy=request.policy,
        )

    def apply(
        self,
        model: object,
        parameters: SnapShellParameters,
    ) -> object:
        """Union synthetic snap-shell geometry into a model."""

        if not isinstance(model, cq.Workplane):
            raise TypeError(
                "SyntheticSnapShellBackend requires a cadquery.Workplane model"
            )

        return model.union(self.build_geometry(parameters))

    def build_geometry(
        self,
        parameters: SnapShellParameters,
    ) -> cq.Workplane:
        """Build clip-only geometry without a device model."""

        clips = tuple(
            self._build_clip(
                parameters=parameters,
                location=location,
            )
            for location in parameters.locations
        )

        if not clips:
            raise ValueError("Snap shell requires geometry locations")

        result = clips[0]

        for clip in clips[1:]:
            result = result.union(clip)

        return result

    def analyze_fit(
        self,
        parameters: SnapShellParameters,
    ) -> SnapShellFitReport:
        """Evaluate deterministic synthetic fit gates.

        ``shell_material_continuity`` and ``device_clearance`` cannot be
        verified from parameters alone - they depend on a real device
        model. Synthetic evaluation reports them as unverified
        placeholders.
        """

        engagement_passed = (
            parameters.overhang_mm > 0 and parameters.clip_height_mm > 0
        )

        manufacturing_passed = (
            parameters.clearance_mm >= 0.10
            and parameters.wall_mm >= 0.60
            and parameters.clip_width_mm > 2.0 * parameters.clearance_mm
        )

        anchor_passed = self._anchor_separation_passed(parameters)

        return SnapShellFitReport(
            results=(
                SnapShellFitResult(
                    check=(SnapShellFitCheck.SHELL_MATERIAL_CONTINUITY),
                    passed=True,
                    detail=(
                        "Synthetic fixture assumes continuous shell "
                        "material at each clip location; production "
                        "evidence is required to confirm."
                    ),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.SNAP_ENGAGEMENT),
                    passed=engagement_passed,
                    detail=(
                        "Positive synthetic lip overhang is present."
                        if engagement_passed
                        else "Positive overhang and clip height are required."
                    ),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.ANCHOR_SEPARATION),
                    passed=anchor_passed,
                    detail=(
                        "Clip locations are spread apart enough to "
                        "resist rotation in every direction."
                        if anchor_passed
                        else "Clip locations must be spread apart by at "
                        "least one clip width, and not collinear."
                    ),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.DEVICE_CLEARANCE),
                    passed=True,
                    detail=(
                        "Synthetic fixture contains no modeled device "
                        "internals; production clearance remains "
                        "unverified."
                    ),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.MANUFACTURING_CLEARANCE),
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
        parameters: SnapShellParameters,
    ) -> bool:
        locations = parameters.locations

        distances = tuple(
            hypot(first.x_mm - second.x_mm, first.y_mm - second.y_mm)
            for first, second in combinations(locations, 2)
        )

        if not distances:
            return False

        spread_ok = (
            min(distances) >= parameters.clip_width_mm
            and max(distances) >= 2.0 * parameters.clip_width_mm
        )

        # Collinear clips - however far apart - all sit on one line and
        # cannot resist the shell rocking about that line, the failure
        # mode this check exists to catch. The largest triangle any
        # three locations form measures genuine two-dimensional spread;
        # near-zero area means near-collinear.
        max_triangle_area = max(
            (
                0.5
                * abs(
                    (b.x_mm - a.x_mm) * (c.y_mm - a.y_mm)
                    - (c.x_mm - a.x_mm) * (b.y_mm - a.y_mm)
                )
                for a, b, c in combinations(locations, 3)
            ),
            default=0.0,
        )

        return spread_ok and max_triangle_area >= parameters.clip_width_mm**2

    def _build_clip(
        self,
        *,
        parameters: SnapShellParameters,
        location: SnapShellLocation,
    ) -> cq.Workplane:
        clip_parameters = SnapRetentionClipParameters(
            x=location.x_mm,
            y=location.y_mm,
            base_height_mm=parameters.wall_mm,
            compliant_span_mm=parameters.device_thickness_mm,
            board_thickness_mm=parameters.device_thickness_mm,
            width_mm=parameters.clip_width_mm,
            wall_mm=parameters.wall_mm,
            height_mm=parameters.clip_height_mm,
            overhang_mm=parameters.overhang_mm,
            clearance_mm=parameters.clearance_mm,
            base_z_mm=0.0,
            rotation_degrees=location.rotation_degrees,
        )

        return add_snap_retention_clip(
            cq.Workplane("XY"),
            parameters=clip_parameters,
        )

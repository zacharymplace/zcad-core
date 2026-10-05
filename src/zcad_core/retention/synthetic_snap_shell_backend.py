from __future__ import annotations

import math
from itertools import combinations
from math import hypot

import cadquery as cq

from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT, Flexure, flexure_for
from zcad_core.features.snap_retention import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume, solid_intersection
from zcad_core.hardware.wearables.edge_placement import FEATURE_MARGIN_MM
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

# Overlap smaller than this is boolean noise, not material.
_TOLERANCE_MM3 = 1e-6
# The clearance checks look this much short of the clearance, so a face built
# exactly on it does not read as an intrusion.
_CLEARANCE_SLACK_MM = 0.01
# A location this close to an edge's line is on that edge.
_ON_EDGE_MM = 1e-6


class SyntheticSnapShellBackend:
    """CadQuery backend for a snap shell around a box-shaped device.

    The device is the box its parameters give: ``device_length_mm`` along
    X, ``device_width_mm`` along Y, centred, its underside at ``z == 0``.
    The shell is a frame and a clip at each
    :class:`~zcad_core.retention.snap_shell.SnapShellLocation`:

    - the frame is a plate ``wall_mm`` thick under the device, open in the
      middle, reaching ``ledge_mm`` in under the device's rim so the device
      rests on it, and a rim rising ``rim_height_mm`` up the device's sides
      ``clearance_mm`` out from them, so the device cannot slide off, with a
      notch at each edge feature;
    - each clip (see
      :func:`~zcad_core.features.snap_retention.add_snap_retention_clip`)
      stands on the frame ``clearance_mm`` out from the device's edge and
      hooks ``overhang_mm`` over its top edge, ``clearance_mm`` above its
      top face.

    A clip snaps on by bending outward until its lip clears the device's
    edge, ``overhang_mm``. Its stem is held where the rim joins it, so it
    bends over the length from the rim's top to the lip's underside, where
    the device presses it; its strain is the end-loaded cantilever's,
    checked against the engine's provisional limit as the cradle's tab is.

    The fit checks measure that geometry against the device's box. The box
    is the device's envelope, not its internals; a printed trial on the real
    device is what proves the fit.
    """

    def derive(
        self,
        request: SnapShellRequest,
    ) -> SnapShellParameters:
        """Derive validated snap-shell parameters."""

        return derive_snap_shell_parameters(
            device_thickness_mm=request.device_thickness_mm,
            device_length_mm=request.device_length_mm,
            device_width_mm=request.device_width_mm,
            locations=request.locations,
            policy=request.policy,
            edge_features=request.edge_features,
        )

    def apply(
        self,
        model: object,
        parameters: SnapShellParameters,
    ) -> cq.Workplane:
        """Union snap-shell geometry into a model."""

        if not isinstance(model, cq.Workplane):
            raise TypeError(
                "SyntheticSnapShellBackend requires a cadquery.Workplane model"
            )

        return model.union(self.build_geometry(parameters))

    def build_geometry(
        self,
        parameters: SnapShellParameters,
    ) -> cq.Workplane:
        """Build the shell, frame and clips, without the device."""

        if not parameters.locations:
            raise ValueError("Snap shell requires geometry locations")

        shell = self._build_frame(parameters)

        for location in parameters.locations:
            shell = shell.union(
                self._build_clip(parameters=parameters, location=location)
            )

        return shell

    def device_envelope(self, parameters: SnapShellParameters) -> cq.Workplane:
        """The device as the shell must clear it."""

        return _box(
            (-parameters.device_length_mm / 2, parameters.device_length_mm / 2),
            (-parameters.device_width_mm / 2, parameters.device_width_mm / 2),
            (0.0, parameters.device_thickness_mm),
        )

    def clips_into_device_mm3(self, parameters: SnapShellParameters) -> float:
        """How much shell material is inside the device's envelope."""

        return intersection_volume(
            workplane_shape(self.build_geometry(parameters)),
            workplane_shape(self.device_envelope(parameters)),
        )

    def analyze_fit(
        self,
        parameters: SnapShellParameters,
    ) -> SnapShellFitReport:
        """Measure the built shell against the device's envelope."""

        shell = self.build_geometry(parameters)
        shell_shape = workplane_shape(shell)
        solids = len(shell.solids().vals())
        continuity_passed = solids == 1

        into_device = intersection_volume(
            shell_shape, workplane_shape(self.device_envelope(parameters))
        )
        into_clearance = intersection_volume(
            shell_shape, workplane_shape(self._clearance_zone(parameters))
        )
        clearance_passed = into_clearance <= _TOLERANCE_MM3

        engagement_failures = self._engagement_failures(parameters, shell_shape)
        engagement_passed = (
            parameters.overhang_mm > 0
            and parameters.clip_height_mm > 0
            and not engagement_failures
        )

        manufacturing_passed = (
            parameters.clearance_mm >= 0.10
            and parameters.wall_mm >= 0.60
            and parameters.clip_width_mm > 2.0 * parameters.clearance_mm
        )

        anchor_passed = self._anchor_separation_passed(parameters)
        flexure = clip_flexure(parameters)
        strain_passed = flexure.strain <= FLEXURE_STRAIN_LIMIT

        return SnapShellFitReport(
            results=(
                SnapShellFitResult(
                    check=(SnapShellFitCheck.SHELL_MATERIAL_CONTINUITY),
                    passed=continuity_passed,
                    detail=(
                        "The frame and every clip are one solid."
                        if continuity_passed
                        else f"The shell is {solids} separate solids: a clip "
                        "is not joined to the frame."
                    ),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.SNAP_ENGAGEMENT),
                    passed=engagement_passed,
                    detail=(
                        f"Every lip reaches {parameters.overhang_mm:g} mm in over "
                        "the device's top edge."
                        if engagement_passed
                        else "; ".join(
                            engagement_failures
                            or ["Positive overhang and clip height are required."]
                        )
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
                    passed=clearance_passed,
                    detail=(
                        "No shell material is inside the device's envelope or "
                        f"within {parameters.clearance_mm:g} mm of its sides and "
                        "top face."
                        if clearance_passed
                        else f"{into_clearance:.3f} mm3 of shell material is "
                        f"within {parameters.clearance_mm:g} mm of the device, "
                        f"{into_device:.3f} mm3 of it inside its envelope."
                    ),
                ),
                SnapShellFitResult(
                    check=SnapShellFitCheck.CLIP_STRAIN,
                    passed=strain_passed,
                    detail=_strain_detail(flexure, strain_passed),
                ),
                SnapShellFitResult(
                    check=(SnapShellFitCheck.MANUFACTURING_CLEARANCE),
                    passed=manufacturing_passed,
                    detail=(
                        "Clearance and minimum-wall thresholds pass."
                        if manufacturing_passed
                        else "Clearance or minimum-wall thresholds fail."
                    ),
                ),
            )
        )

    @staticmethod
    def _clearance_zone(parameters: SnapShellParameters) -> cq.Workplane:
        """The device grown by its clearance on its sides and top face, but
        not below it, where it rests on the frame's ledge."""

        grow = max(parameters.clearance_mm - _CLEARANCE_SLACK_MM, 0.0)
        half_x = parameters.device_length_mm / 2 + grow
        half_y = parameters.device_width_mm / 2 + grow

        return _box(
            (-half_x, half_x),
            (-half_y, half_y),
            (0.0, parameters.device_thickness_mm + grow),
        )

    def _engagement_failures(
        self, parameters: SnapShellParameters, shell: cq.Shape
    ) -> list[str]:
        """Each clip whose location is not on the device's edge, or whose lip
        does not reach ``overhang_mm`` in over the top face there."""

        failures = []
        thickness = parameters.device_thickness_mm
        top = thickness + parameters.clearance_mm + parameters.clip_height_mm
        half = parameters.clip_width_mm / 2

        for location in parameters.locations:
            inward = _inward(parameters, location)

            if inward is None:
                failures.append(
                    f"The {location.label} clip is not on the device's edge."
                )

                continue

            # The strip over the top face that the lip should fill: from the
            # edge, overhang_mm in, the clip's width along the edge.
            nx, ny = inward
            reach = parameters.overhang_mm
            xs = sorted((location.x_mm, location.x_mm + nx * reach))
            ys = sorted((location.y_mm, location.y_mm + ny * reach))

            if nx == 0:
                xs = [location.x_mm - half, location.x_mm + half]
            else:
                ys = [location.y_mm - half, location.y_mm + half]

            over = solid_intersection(
                shell,
                workplane_shape(_box((xs[0], xs[1]), (ys[0], ys[1]), (thickness, top))),
            )
            box = over.BoundingBox() if over is not None else None
            reached = (
                0.0
                if box is None
                else max(
                    nx * (corner_x - location.x_mm) + ny * (corner_y - location.y_mm)
                    for corner_x in (box.xmin, box.xmax)
                    for corner_y in (box.ymin, box.ymax)
                )
            )

            if reached < reach - _CLEARANCE_SLACK_MM:
                failures.append(
                    f"The {location.label} clip's lip reaches {reached:.2f} mm "
                    f"over the device's top edge, not {reach:g} mm."
                )

        return failures

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

    @staticmethod
    def _build_frame(parameters: SnapShellParameters) -> cq.Workplane:
        """The plate under the device's rim and the rim up its sides, with a
        notch through the rim at each edge feature."""

        half_x = parameters.device_length_mm / 2
        half_y = parameters.device_width_mm / 2
        reach = parameters.clearance_mm + parameters.wall_mm
        rim_inner = parameters.clearance_mm
        floor = -parameters.wall_mm

        frame = _box(
            (-half_x - reach, half_x + reach),
            (-half_y - reach, half_y + reach),
            (floor, parameters.rim_height_mm),
        )
        frame = frame.cut(
            _box(
                (-half_x - rim_inner, half_x + rim_inner),
                (-half_y - rim_inner, half_y + rim_inner),
                (0.0, parameters.rim_height_mm + 1.0),
            )
        )
        frame = frame.cut(
            _box(
                (-half_x + parameters.ledge_mm, half_x - parameters.ledge_mm),
                (-half_y + parameters.ledge_mm, half_y - parameters.ledge_mm),
                (floor - 1.0, 1.0),
            )
        )

        for feature in parameters.edge_features:
            centre = feature.center_offset_mm
            width = feature.width_mm / 2 + FEATURE_MARGIN_MM
            along = (centre - width, centre + width)
            z = (0.0, parameters.rim_height_mm + 1.0)
            half = half_y if feature.edge in ("north", "south") else half_x
            out = (half + rim_inner - 0.01, half + reach + 0.01)

            if feature.edge in ("south", "west"):
                out = (-out[1], -out[0])

            if feature.edge in ("north", "south"):
                frame = frame.cut(_box(along, out, z))
            else:
                frame = frame.cut(_box(out, along, z))

        return frame

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
            base_z_mm=-parameters.wall_mm,
            rotation_degrees=location.rotation_degrees,
        )

        return add_snap_retention_clip(
            cq.Workplane("XY"),
            parameters=clip_parameters,
        )


def clip_flexure(parameters: SnapShellParameters) -> Flexure:
    """A clip's stem as a cantilever: ``wall_mm`` thick, fixed at the rim's
    top, swinging ``overhang_mm`` at the lip's underside to let the device
    past. A stem the rim reaches to the lip has no length to bend and
    fails."""

    length = (
        parameters.device_thickness_mm
        + parameters.clearance_mm
        - parameters.rim_height_mm
    )

    if length <= 0:
        return Flexure(
            thickness_mm=parameters.wall_mm,
            length_mm=max(length, 0.0),
            deflection_mm=parameters.overhang_mm,
            strain=float("inf"),
            strain_limit=FLEXURE_STRAIN_LIMIT,
        )

    return flexure_for(parameters.overhang_mm, length, parameters.wall_mm)


def _strain_detail(flexure: Flexure, passed: bool) -> str:
    strain = (
        f"A {flexure.thickness_mm:g} mm stem bending over "
        f"{flexure.length_mm:.2f} mm to swing {flexure.deflection_mm:g} mm "
        f"strains {100 * flexure.strain:.1f} per cent"
    )
    limit = f"the {100 * FLEXURE_STRAIN_LIMIT:g} per cent limit"

    if passed:
        return f"{strain}, within {limit}."

    if flexure.length_mm <= 0:
        return (
            "The rim reaches the lip, so the stem has no length to bend: lower the rim."
        )

    # The longest stem and the thickest wall that stay within the limit.
    needed = math.sqrt(
        3 * flexure.thickness_mm * flexure.deflection_mm / (2 * FLEXURE_STRAIN_LIMIT)
    )
    thinnest = (
        2 * FLEXURE_STRAIN_LIMIT * flexure.length_mm**2 / (3 * flexure.deflection_mm)
    )

    return (
        f"{strain}, over {limit}: it needs {needed:.1f} mm to bend over, a "
        f"stem {thinnest:.2f} mm thick, or less overhang."
    )


def _inward(
    parameters: SnapShellParameters, location: SnapShellLocation
) -> tuple[float, float] | None:
    """The way into the device from a location on its edge, ``None`` if the
    location is on no edge."""

    half_x = parameters.device_length_mm / 2
    half_y = parameters.device_width_mm / 2
    x, y = location.x_mm, location.y_mm

    if abs(abs(y) - half_y) <= _ON_EDGE_MM and abs(x) <= half_x:
        return (0.0, -1.0 if y > 0 else 1.0)

    if abs(abs(x) - half_x) <= _ON_EDGE_MM and abs(y) <= half_y:
        return (-1.0 if x > 0 else 1.0, 0.0)

    return None


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )

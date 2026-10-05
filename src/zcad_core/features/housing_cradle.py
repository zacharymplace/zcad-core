"""A cradle for a sealed wearable device: a tray it snaps into.

The device lies in a pocket on a floor, face away from the body up; the skin side is
closed by the floor, so a device whose skin side must stay open, such as the
Dexcom G7, can sit in one but not be worn in one. A wall rises round the pocket to the device's top face, and the
face is left open. A snap **tab** on each of the chosen edges holds the device in.

A tab is the top strip of the wall, cut free from the wall below it by a slit along
its underside and from the wall beside it by a slit at its free end, so it is a beam
fixed at one end that bends outward, in the plane of the wall. A hook on its free
end stands in over the device's top edge by ``OVERHANG_MM``, measured from the
device's edge so that the clearance round the device never eats into it, with a flat underside
that holds the device down and a sloped top that lets the device push the tab aside
as it is pressed in. Because the tab bends along the wall and not up it, a thin
device (the Dexcom G7 is 4.7 mm) has the length a tab needs, and the tab's strain is
the end-loaded cantilever's, checked against the engine's provisional limit, as the
snap clips' are.

A tab stands in the middle of its edge, slid along it to the nearest place clear of
every feature on that edge, and clear of the corners. Each edge feature a capture
lists gets a notch through the wall, so a button, a port or a contact stays open;
each face feature the tab's hook would cover refuses the build.

Frame: the device's, from the capture (see :mod:`housing_file`), underside at
``z == 0``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT, Flexure, flexure_for
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.wearables import FaceFeature, WearableCapture
from zcad_core.hardware.wearables.edge_placement import (
    FACE_MARGIN_MM,
    FEATURE_MARGIN_MM,
    clear_offset,
    edge_reach_mm,
)

# The tab: its length along the wall, the slit round it, and the strip's height.
TAB_LENGTH_MM = 12.0
TAB_SLIT_MM = 0.8
TAB_HEIGHT_MM = 2.5
# The hook: how far it stands in over the device's top edge, how tall, how wide, and
# the gap its flat underside leaves above the device's top face.
OVERHANG_MM = 0.6
HOOK_HEIGHT_MM = 1.0
HOOK_WIDTH_MM = 4.0
TOP_GAP_MM = 0.1
_ROTATION = {"north": 0.0, "west": 90.0, "south": 180.0, "east": 270.0}
# A feature's offset on these edges runs against the tab's own along-the-wall axis.
_FLIPPED = ("south", "east")
_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class Tab:
    """A snap tab on one edge: where it stands along the edge, from the middle, in
    the capture's own offset direction (+X on north and south, +Y on east and
    west)."""

    edge: str
    offset_mm: float


@dataclass(frozen=True)
class CradlePlan:
    """The tabs, the flexure they share, and what the plan found wrong."""

    tabs: tuple[Tab, ...]
    flexure: Flexure
    outer_size_mm: tuple[float, float, float]
    errors: tuple[str, ...]


def outline_points(capture: WearableCapture) -> Sequence[tuple[float, float]]:
    """The device's outline, a rectangle or a rounded rectangle."""

    if capture.outline_radius_mm is None:
        half_x, half_y = capture.length_mm / 2, capture.width_mm / 2

        return (
            (-half_x, -half_y),
            (half_x, -half_y),
            (half_x, half_y),
            (-half_x, half_y),
        )

    return board_outline.rounded_rectangle_points(
        capture.length_mm, capture.width_mm, capture.outline_radius_mm
    )


def _edge_length(capture: WearableCapture, edge: str) -> float:
    return capture.edge_length_mm(edge)


def half_across(capture: WearableCapture, edge: str) -> float:
    """How far the edge stands from the device's middle, across it: half the width
    to the north and south edges, half the length to the east and west."""

    return capture.width_mm / 2 if edge in ("north", "south") else capture.length_mm / 2


def _hook_box(capture: WearableCapture, tab: Tab) -> tuple[float, float, float, float]:
    """The hook's footprint over the device's face, as ``(x0, x1, y0, y1)`` in the
    capture's frame: a strip along the tab's free end, ``OVERHANG_MM`` deep."""

    sign = -1.0 if tab.edge in _FLIPPED else 1.0
    along0 = sign * tab.offset_mm + TAB_LENGTH_MM / 2 - HOOK_WIDTH_MM
    along1 = sign * tab.offset_mm + TAB_LENGTH_MM / 2
    # Back from local (north) to the capture's frame.
    local = (along0, along1)
    angle = math.radians(_ROTATION[tab.edge])
    half_y = half_across(capture, tab.edge)

    corners = [(x, y) for x in local for y in (half_y - OVERHANG_MM, half_y)]
    rotated = [
        (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
        )
        for x, y in corners
    ]
    xs, ys = [p[0] for p in rotated], [p[1] for p in rotated]

    return min(xs), max(xs), min(ys), max(ys)


def _covers(box: tuple[float, float, float, float], feature: FaceFeature) -> bool:
    x0, x1, y0, y1 = box

    return (
        x0 < feature.center_x_mm + feature.width_mm / 2 + FACE_MARGIN_MM
        and feature.center_x_mm - feature.width_mm / 2 - FACE_MARGIN_MM < x1
        and y0 < feature.center_y_mm + feature.depth_mm / 2 + FACE_MARGIN_MM
        and feature.center_y_mm - feature.depth_mm / 2 - FACE_MARGIN_MM < y1
    )


def plan_cradle(
    capture: WearableCapture,
    *,
    edges: Sequence[str],
    wall_mm: float,
    floor_mm: float,
    clearance_mm: float,
) -> CradlePlan:
    """Place a tab on each edge and check its strain, collecting every problem."""

    errors: list[str] = []
    tabs: list[Tab] = []
    span = TAB_LENGTH_MM + TAB_SLIT_MM
    radius = capture.outline_radius_mm or 0.0

    for edge in edges:
        blocked = [f for f in capture.edge_features if f.edge == edge]
        reach = edge_reach_mm(_edge_length(capture, edge), span, radius)
        offset = clear_offset(blocked, reach, span)

        if offset is None:
            names = ", ".join(f.identifier for f in blocked) or "the corners"
            errors.append(
                f"No place on the {edge} edge clears {names} for a "
                f"{TAB_LENGTH_MM:g} mm tab: take {edge} out of retention_edges"
            )

            continue

        tab = Tab(edge, offset)
        box = _hook_box(capture, tab)

        for feature in capture.face_features:
            if _covers(box, feature):
                errors.append(
                    f"The {edge} tab's hook would cover the face feature "
                    f"{feature.identifier}: take {edge} out of retention_edges"
                )

        tabs.append(tab)

    flexure = flexure_for(OVERHANG_MM, TAB_LENGTH_MM, wall_mm)

    if flexure.strain > FLEXURE_STRAIN_LIMIT:
        needed = math.ceil(
            math.sqrt(3 * wall_mm * OVERHANG_MM / (2 * FLEXURE_STRAIN_LIMIT))
        )
        errors.append(
            f"A {wall_mm:g} mm wall's {TAB_LENGTH_MM:g} mm tab strains "
            f"{100 * flexure.strain:.1f} per cent, over the "
            f"{100 * FLEXURE_STRAIN_LIMIT:g} per cent limit: it needs a tab "
            f"{needed} mm long, or a thinner wall"
        )

    reach_out = clearance_mm + wall_mm
    top = capture.thickness_mm + TOP_GAP_MM + HOOK_HEIGHT_MM

    return CradlePlan(
        tabs=tuple(tabs),
        flexure=flexure,
        outer_size_mm=(
            capture.length_mm + 2 * reach_out,
            capture.width_mm + 2 * reach_out,
            floor_mm + top,
        ),
        errors=tuple(errors),
    )


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def _tab_cuts(
    capture: WearableCapture,
    tab: Tab,
    *,
    clearance_mm: float,
    wall_mm: float,
) -> tuple[cq.Workplane, cq.Workplane, cq.Workplane]:
    """The tab as built on the north edge and then turned to its own: material to
    add (the wall's extension and the hook), the slits to cut."""

    sign = -1.0 if tab.edge in _FLIPPED else 1.0
    thickness = capture.thickness_mm
    edge = half_across(capture, tab.edge)
    inner = edge + clearance_mm
    outer = inner + wall_mm
    x0 = sign * tab.offset_mm - TAB_LENGTH_MM / 2
    x1 = x0 + TAB_LENGTH_MM
    top = thickness + TOP_GAP_MM + HOOK_HEIGHT_MM
    strip = top - TAB_HEIGHT_MM
    # The wall stands up to the strip's top along the tab; elsewhere it stops at
    # the device's top face.
    extension = _box((x0, x1), (inner, outer), (thickness, top))
    hook = (
        cq.Workplane("YZ")
        .polyline(
            [
                (inner, thickness + TOP_GAP_MM),
                (edge - OVERHANG_MM, thickness + TOP_GAP_MM),
                (inner, top),
            ]
        )
        .close()
        .extrude(HOOK_WIDTH_MM)
        .translate((x1 - HOOK_WIDTH_MM, 0, 0))
    )
    under = _box(
        (x0, x1 + TAB_SLIT_MM),
        (inner - 0.01, outer + 0.01),
        (strip - TAB_SLIT_MM, strip),
    )
    end = _box(
        (x1, x1 + TAB_SLIT_MM),
        (inner - 0.01, outer + 0.01),
        (strip - TAB_SLIT_MM, top + 0.1),
    )

    return extension.union(hook), under, end


def hook_reach(capture: WearableCapture, tab: Tab) -> cq.Workplane:
    """The space a tab's hook should fill over the device: its width at the
    tab's free end, ``OVERHANG_MM`` in from the device's edge, between the device's
    top face and the hook's top."""

    sign = -1.0 if tab.edge in _FLIPPED else 1.0
    x1 = sign * tab.offset_mm + TAB_LENGTH_MM / 2
    edge = half_across(capture, tab.edge)
    top = capture.thickness_mm + TOP_GAP_MM + HOOK_HEIGHT_MM
    reach = _box(
        (x1 - HOOK_WIDTH_MM, x1),
        (edge - OVERHANG_MM, edge),
        (capture.thickness_mm, top),
    )

    return _turn(reach, tab.edge)


def _turn(model: cq.Workplane, edge: str) -> cq.Workplane:
    angle = _ROTATION[edge]

    return model.rotate((0, 0, 0), (0, 0, 1), angle) if angle else model


def build_cradle(
    capture: WearableCapture,
    plan: CradlePlan,
    *,
    wall_mm: float,
    floor_mm: float,
    clearance_mm: float,
) -> cq.Workplane:
    """The tray: a floor, a wall to the device's top face, a notch at each edge
    feature, and the tabs."""

    points = outline_points(capture)
    thickness = capture.thickness_mm
    reach = clearance_mm + wall_mm
    tray = outline_prism(points, -floor_mm, thickness, reach)
    tray = tray.cut(outline_prism(points, 0.0, thickness + 1.0, clearance_mm))

    for feature in capture.edge_features:
        sign = -1.0 if feature.edge in _FLIPPED else 1.0
        width = feature.width_mm + 2 * FEATURE_MARGIN_MM
        inner = half_across(capture, feature.edge) + clearance_mm
        centre = sign * feature.center_offset_mm
        notch = _box(
            (centre - width / 2, centre + width / 2),
            (inner - 0.01, inner + wall_mm + 0.01),
            (0.0, thickness + HOOK_HEIGHT_MM + 1.0),
        )
        tray = tray.cut(_turn(notch, feature.edge))

    for tab in plan.tabs:
        grown, under, end = _tab_cuts(
            capture, tab, clearance_mm=clearance_mm, wall_mm=wall_mm
        )
        tray = tray.union(_turn(grown, tab.edge))
        tray = tray.cut(_turn(under.union(end), tab.edge))

    return tray


def device_envelope(capture: WearableCapture) -> cq.Workplane:
    """The device as the housing must clear it: its outline from ``z == 0`` to its
    thickness."""

    return outline_prism(outline_points(capture), 0.0, capture.thickness_mm)

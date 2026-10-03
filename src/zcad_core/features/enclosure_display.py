"""A display's window, retainer and posts on an enclosure's lid."""

from __future__ import annotations

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly
from zcad_core.features.display_cutouts import (
    DisplayWindowParameters,
    cut_display_window,
)
from zcad_core.features.display_retainer import (
    DisplayPostParameters,
    DisplayRetainerParameters,
    add_display_posts,
    add_display_retainer,
)
from zcad_core.features.enclosure_geometry import _all_solids
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.features.pcb_mounts import BoardHolePattern, board_hole_pattern
from zcad_core.hardware import DisplaySpec, get_fastener

_DISPLAY_POST_WALL_MM = 1.2


_RETAINER_CLEARANCE_MM = 0.3


def _add_display_features(
    lid: cq.Workplane,
    *,
    assembly: DeviceAssembly,
    display: DisplaySpec,
    display_identifier: str,
    design: EnclosureDesign,
    cavity_top: float,
) -> tuple[cq.Workplane, str | None, tuple[int, float] | None]:
    """Cut the display window and hang what holds the display under it; for
    screw posts, also the number of screws and the longest that fits."""

    component = assembly.get(display_identifier)
    lid = cut_display_window(
        lid,
        parameters=DisplayWindowParameters.from_display(
            display=display,
            panel_base_z_mm=cavity_top,
            panel_thickness_mm=design.lid_mm,
            x=component.placement.x_mm,
            y=component.placement.y_mm,
            window_clearance_mm=display.recommended_window_clearance_mm
            + design.hole_compensation_mm / 2,
        ),
    )

    if not design.display_retainer:
        return lid, None, None

    bounds = _all_solids(component.transformed_geometry()).BoundingBox()
    holes = board_hole_pattern(display)

    if holes is not None:
        pcb_face = bounds.zmax - (display.panel_thickness_mm or 0.0)
        reach = cavity_top - pcb_face + (display.pcb_thickness_mm or 0.0)

        return (
            _add_display_posts(lid, display, holes, bounds, design, cavity_top),
            "posts",
            (len(holes.positions), reach),
        )

    return (
        add_display_retainer(
            lid,
            parameters=DisplayRetainerParameters(
                center_x_mm=(bounds.xmin + bounds.xmax) / 2,
                center_y_mm=(bounds.ymin + bounds.ymax) / 2,
                module_width_mm=bounds.xlen,
                module_depth_mm=bounds.ylen,
                module_thickness_mm=bounds.zlen,
                module_top_z_mm=bounds.zmax,
                lid_underside_z_mm=cavity_top,
                clearance_mm=_RETAINER_CLEARANCE_MM + design.hole_compensation_mm / 2,
            ),
        ),
        "clips",
        None,
    )


def _add_display_posts(
    lid: cq.Workplane,
    display: DisplaySpec,
    holes: BoardHolePattern,
    bounds: cq.BoundBox,
    design: EnclosureDesign,
    cavity_top: float,
) -> cq.Workplane:
    """Posts from the lid down to the display's PCB, over its holes."""

    fastener = get_fastener(design.display_fastener)

    if fastener.clearance_hole_mm > holes.hole_diameter_mm:
        raise ValueError(
            f"{fastener.identifier} screws do not fit the display's "
            f"{holes.hole_diameter_mm} mm holes; choose a smaller display_fastener"
        )

    center_x = (bounds.xmin + bounds.xmax) / 2
    center_y = (bounds.ymin + bounds.ymax) / 2

    return add_display_posts(
        lid,
        parameters=DisplayPostParameters(
            positions=tuple((center_x + x, center_y + y) for x, y in holes.positions),
            pcb_face_z_mm=bounds.zmax - (display.panel_thickness_mm or 0.0),
            lid_underside_z_mm=cavity_top,
            pilot_hole_mm=fastener.tap_hole_mm + design.hole_compensation_mm,
            outer_diameter_mm=fastener.tap_hole_mm + 2 * _DISPLAY_POST_WALL_MM,
        ),
    )

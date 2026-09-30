"""A Raspberry Pi 5 as solid boxes, and the box helpers the enclosure uses.

The envelope is what the enclosure must clear: the board, its ports, the
header, the Active Cooler, and the microSD card."""

from __future__ import annotations

import cadquery as cq

from zcad_core.hardware import RaspberryPi5Spec


def make_box(
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    z_range: tuple[float, float],
) -> cq.Solid:
    return cq.Solid.makeBox(
        x_range[1] - x_range[0],
        y_range[1] - y_range[0],
        z_range[1] - z_range[0],
        pnt=cq.Vector(x_range[0], y_range[0], z_range[0]),
    )


def pi_envelope(
    pi: RaspberryPi5Spec,
    center_x: float,
    center_y: float,
    board_bottom: float,
    board_top: float,
) -> cq.Shape:
    """A Pi 5 as unioned boxes: board, ports, header, cooler, microSD."""

    half_x = pi.board_width_mm / 2
    half_y = pi.board_length_mm / 2
    boxes = [
        make_box(
            (center_x - half_x, center_x + half_x),
            (center_y - half_y, center_y + half_y),
            (board_bottom, board_top),
        )
    ]

    for port in pi.ports:
        top = board_top + port.height_mm

        if port.edge == "positive_y":
            x_range = (
                center_x + port.center_mm - port.width_mm / 2,
                center_x + port.center_mm + port.width_mm / 2,
            )
            y_range = (
                center_y + half_y - port.depth_mm,
                center_y + half_y + port.overhang_mm,
            )
        elif port.edge == "positive_x":
            x_range = (
                center_x + half_x - port.depth_mm,
                center_x + half_x + port.overhang_mm,
            )
            y_range = (
                center_y + port.center_mm - port.width_mm / 2,
                center_y + port.center_mm + port.width_mm / 2,
            )
        else:
            raise ValueError(f"unsupported port edge '{port.edge}'")

        boxes.append(make_box(x_range, y_range, (board_top, top)))

    # The header runs along the board's left (negative_x) edge.
    header_x = center_x - pi.mounting_hole_spacing_x_mm / 2
    boxes.append(
        make_box(
            (header_x - pi.header_width_mm / 2, header_x + pi.header_width_mm / 2),
            (
                center_y + pi.header_center_y_mm - pi.header_length_mm / 2,
                center_y + pi.header_center_y_mm + pi.header_length_mm / 2,
            ),
            (board_top, board_top + pi.header_height_mm),
        )
    )
    boxes.append(
        make_box(
            (
                center_x + pi.cooler_center_x_mm - pi.cooler_width_mm / 2,
                center_x + pi.cooler_center_x_mm + pi.cooler_width_mm / 2,
            ),
            (
                center_y + pi.cooler_center_y_mm - pi.cooler_length_mm / 2,
                center_y + pi.cooler_center_y_mm + pi.cooler_length_mm / 2,
            ),
            (
                board_top + pi.cooler_bottom_above_board_mm,
                board_top + pi.cooler_height_mm,
            ),
        )
    )
    boxes.append(
        make_box(
            (
                center_x - pi.sd_card_width_mm / 2,
                center_x + pi.sd_card_width_mm / 2,
            ),
            (center_y - half_y - pi.sd_card_overhang_mm, center_y - half_y + 15.0),
            (board_bottom - pi.sd_card_depth_below_board_mm, board_bottom),
        )
    )

    return single_shape(cq.Workplane("XY").add(boxes).combine())


def single_shape(model: cq.Workplane) -> cq.Shape:
    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)

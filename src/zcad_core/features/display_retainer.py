"""A lid-hung retainer that holds a display module under its window.

An L-shaped post at each corner of the module locates it and, where the
module sits below the lid, carries a pad the module's face rests against; a
snap clip at the middle of each side edge hooks under the module. The middle
of the other two edges stays open for a pin header or flex cable. The
retainer hangs down from the lid's underside, so it prints upright with the
lid printed face down.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq


@dataclass(frozen=True)
class DisplayRetainerParameters:
    """Geometry of one display retainer, in assembly coordinates."""

    center_x_mm: float
    center_y_mm: float
    module_width_mm: float
    module_depth_mm: float
    module_thickness_mm: float
    module_top_z_mm: float
    lid_underside_z_mm: float

    clearance_mm: float = 0.3
    wall_mm: float = 1.2
    corner_leg_mm: float = 3.0
    pad_mm: float = 2.5
    clip_width_mm: float = 6.0
    clip_reach_mm: float = 1.0
    clip_lip_height_mm: float = 1.0
    # Gap above the clip lip, so the module snaps in without preload.
    clip_gap_mm: float = 0.1

    def validate(self) -> None:
        positive = (
            "module_width_mm",
            "module_depth_mm",
            "module_thickness_mm",
            "wall_mm",
            "corner_leg_mm",
            "pad_mm",
            "clip_width_mm",
            "clip_reach_mm",
            "clip_lip_height_mm",
        )

        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        for name in ("clearance_mm", "clip_gap_mm"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

        if self.module_top_z_mm > self.lid_underside_z_mm:
            raise ValueError("the display module must sit under the lid")

        if self.clip_reach_mm <= self.clearance_mm:
            raise ValueError("clip_reach_mm must exceed clearance_mm")

        if 2 * self.corner_leg_mm + self.clip_width_mm >= self.module_depth_mm:
            raise ValueError("the module is too short for its corner posts and clips")

        if 2 * self.pad_mm >= min(self.module_width_mm, self.module_depth_mm):
            raise ValueError("pad_mm is too large for the module")

    @property
    def module_bottom_z_mm(self) -> float:
        return self.module_top_z_mm - self.module_thickness_mm


def add_display_retainer(
    model: cq.Workplane,
    *,
    parameters: DisplayRetainerParameters,
) -> cq.Workplane:
    """Add corner posts, face pads, and side clips for one display module."""
    parameters.validate()

    retainer = _local_retainer(parameters).translate(
        (parameters.center_x_mm, parameters.center_y_mm, 0)
    )

    return model.union(retainer)


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    """A box spanning each pair of coordinates, in either order."""
    (x0, x1), (y0, y1), (z0, z1) = sorted(x), sorted(y), sorted(z)

    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def _local_retainer(p: DisplayRetainerParameters) -> cq.Workplane:
    """The retainer about the module centre."""
    half_w, half_d = p.module_width_mm / 2, p.module_depth_mm / 2
    inner_w, inner_d = half_w + p.clearance_mm, half_d + p.clearance_mm
    outer_w, outer_d = inner_w + p.wall_mm, inner_d + p.wall_mm
    # Posts reach down past the module's face to locate it; they overlap
    # the lid slightly so they fuse to it.
    top = p.lid_underside_z_mm + 0.01
    post_bottom = p.module_bottom_z_mm + p.module_thickness_mm / 2
    retainer = cq.Workplane("XY")

    for sx in (-1, 1):
        for sy in (-1, 1):
            leg_x = _box(
                (sx * outer_w, sx * (inner_w - p.corner_leg_mm)),
                (sy * inner_d, sy * outer_d),
                (post_bottom, top),
            )
            leg_y = _box(
                (sx * inner_w, sx * outer_w),
                (sy * outer_d, sy * (inner_d - p.corner_leg_mm)),
                (post_bottom, top),
            )
            retainer = retainer.union(leg_x).union(leg_y)

            if p.module_top_z_mm < p.lid_underside_z_mm:
                retainer = retainer.union(
                    _box(
                        (sx * half_w, sx * (half_w - p.pad_mm)),
                        (sy * half_d, sy * (half_d - p.pad_mm)),
                        (p.module_top_z_mm, top),
                    )
                )

    for side in (-1, 1):
        retainer = retainer.union(_clip(p, side=side, inner_w=inner_w, top=top))

    return retainer


def _clip(
    p: DisplayRetainerParameters, *, side: int, inner_w: float, top: float
) -> cq.Workplane:
    """One hanging clip on the ``side * inner_w`` edge, hooking under it."""
    outer = inner_w + p.wall_mm
    reach = p.module_width_mm / 2 - (p.clip_reach_mm - p.clearance_mm)
    lip_top = p.module_bottom_z_mm - p.clip_gap_mm
    lip_bottom = lip_top - p.clip_lip_height_mm
    width = (-p.clip_width_mm / 2, p.clip_width_mm / 2)

    stem = _box((side * inner_w, side * outer), width, (lip_bottom, top))
    lip = _box((side * reach, side * outer), width, (lip_bottom, lip_top))

    return stem.union(lip)

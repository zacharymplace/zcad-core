"""The shadow of a part seen from above, which a fixture's nest follows."""

from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.silhouette import silhouette
from zcad_core.hardware.electronics import board_outline


def block(
    width: float,
    depth: float,
    height: float,
    at: tuple[float, float, float] = (0, 0, 0),
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(width, depth, height, centered=(True, True, False))
        .translate(at)
    )


def shape_of(model: cq.Workplane) -> cq.Shape:
    value = model.val()
    assert isinstance(value, cq.Shape)

    return value


def test_a_box_casts_its_footprint_about_its_centre() -> None:
    shadow = silhouette(shape_of(block(40, 25, 10, at=(100, -30, 7))))
    x0, x1, y0, y1 = board_outline.bounding_box(shadow.points)

    assert shadow.area_mm2 == pytest.approx(40 * 25, rel=0.01)
    assert (x0 + x1, y0 + y1) == pytest.approx((0, 0), abs=0.2)
    assert (x1 - x0, y1 - y0) == pytest.approx((40, 25), abs=0.3)
    assert board_outline.signed_area(shadow.points) > 0
    assert shadow.top_share == pytest.approx(1.0, abs=0.01)


def test_the_shadow_is_never_smaller_than_the_part() -> None:
    shadow = silhouette(shape_of(block(40, 25, 10)))

    assert shadow.area_mm2 >= 40 * 25


def test_an_undercut_casts_the_shadow_of_its_widest_part() -> None:
    """A wide head on a narrow stem: the shadow is the head's, so a pocket cut to
    it lets the part lift out."""

    mushroom = block(10, 10, 20).union(block(40, 30, 5, at=(0, 0, 20)))
    shadow = silhouette(shape_of(mushroom))

    assert shadow.area_mm2 == pytest.approx(40 * 30, rel=0.01)


def test_a_hole_is_filled_and_a_round_corner_is_followed() -> None:
    plate = block(60, 40, 4).edges("|Z").fillet(6).faces(">Z").workplane().hole(10)
    shadow = silhouette(shape_of(plate))
    expected = 60 * 40 - (4 - 3.14159265) * 36

    assert shadow.area_mm2 == pytest.approx(expected, rel=0.01)
    assert len(shadow.points) > 20


def test_a_part_that_hangs_over_the_plate_widens_the_shadow() -> None:
    plate = block(40, 40, 2)
    inside = block(5, 5, 8, at=(0, 0, 2))
    overhang = block(10, 6, 8, at=(22, 0, 2))
    compound = cq.Compound.makeCompound(
        [shape_of(plate), shape_of(inside), shape_of(overhang)]
    )
    shadow = silhouette(compound)
    x0, x1, _, _ = board_outline.bounding_box(shadow.points)

    # The part overhangs by 7 mm on one side.
    assert x1 - x0 == pytest.approx(47, abs=0.4)
    assert shadow.area_mm2 == pytest.approx(40 * 40 + 7 * 6, rel=0.02)


def test_two_parts_apart_are_refused() -> None:
    apart = cq.Compound.makeCompound(
        [shape_of(block(10, 10, 5)), shape_of(block(10, 10, 5, at=(30, 0, 0)))]
    )

    with pytest.raises(ValueError, match="2 separate pieces"):
        silhouette(apart)


def test_every_point_of_the_part_lies_in_its_shadow() -> None:
    part = shape_of(block(30, 20, 6).union(block(8, 30, 6, at=(0, 10, 0))))
    shadow = silhouette(part)
    box = part.BoundingBox()
    centre = ((box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2)
    vertices, _ = part.tessellate(0.1, 0.3)

    for vertex in vertices:
        point = (vertex.x - centre[0], vertex.y - centre[1])

        assert board_outline.depth_inside(shadow.points, point) > -0.1


def test_only_flat_material_at_the_top_counts_as_bearing() -> None:
    ball = shape_of(cq.Workplane("XY").sphere(10))
    stepped = shape_of(block(40, 40, 5).union(block(10, 10, 5, at=(0, 0, 5))))

    assert silhouette(ball).top_share < 0.01
    # Only the 10 x 10 raised block is at the part's top.
    assert silhouette(stepped).top_share == pytest.approx(100 / 1600, abs=0.01)

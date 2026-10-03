"""The point-in-material test the vent placer uses answers as the whole-model
classifier does; it only skips the classifier for a point far outside a solid."""

from __future__ import annotations

import itertools

import cadquery as cq

from zcad_core.features.vent_patterns import solid_tester


def model() -> cq.Workplane:
    """A drilled block, a separate cylinder beside it, and a thin plate."""

    block = cq.Workplane("XY").box(20, 10, 6).faces(">Z").workplane().hole(4)
    post = cq.Workplane("XY").cylinder(8, 3).translate((20, 0, 1))
    plate = cq.Workplane("XY").box(10, 10, 0.4).translate((-20, 0, 0))

    return block.add(post).add(plate)


def test_it_agrees_with_the_whole_compound_everywhere_it_is_asked() -> None:
    shapes = model()
    compound = cq.Compound.makeCompound(
        [
            solid
            for item in shapes.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )
    inside = solid_tester(shapes)
    # Planes through every face, a hair either side of each, and far outside.
    xs = [-40, -25.001, -25, -24.999, -20, -15, -10.001, -10, 0, 9.999, 10, 10.001]
    xs += [17, 17.001, 20, 22.999, 23, 23.001, 30]
    ys = [-6, -5.001, -5, -4.999, -2, 0, 2, 4.999, 5, 5.001, 6]
    zs = [-5, -4.001, -4, -3.001, -3, -2.999, -0.2, 0, 0.2, 2.999, 3, 3.001, 5]
    seen = {True: 0, False: 0}

    for x, y, z in itertools.product(xs, ys, zs):
        point = cq.Vector(x, y, z)
        expected = bool(compound.isInside(point))
        seen[expected] += 1

        assert inside(point) == expected, (x, y, z)

    # The sample reaches material, hole, gap and open space, not just one answer.
    assert seen[True] > 50 and seen[False] > 50


def test_a_point_on_a_face_still_counts_as_in_the_material() -> None:
    inside = solid_tester(cq.Workplane("XY").box(10, 10, 10))

    assert inside(cq.Vector(5, 0, 0))
    assert inside(cq.Vector(5, 5, 5))
    assert not inside(cq.Vector(5.01, 0, 0))

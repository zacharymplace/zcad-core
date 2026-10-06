"""How a print copy sits on the bed, and whether it needs supports.

A part is laid on the bed by a fixed rule (a base on its floor, a lid on its
outer face), which is right for a plain box and wrong for a part with
something standing out of the face it is laid on: a hinged lid's knuckles, a
base's mount pads. Those lie on the protrusion, with the panel in the air.
No turn helps either one, since each has protrusions on more than one face,
so such a part is sliced with supports from the build plate instead.

The measure is the share of a part's footprint that is flat on the bed. The
parts that print without supports have at least 0.89 of it there (a hinged
base, its knuckles hanging over the side, is the least); a part lying on
pads or knuckles has none to 0.02. Half is the line between them.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

# A part with less of its footprint than this flat on the bed is sliced with
# supports from the build plate.
MINIMUM_BED_SHARE = 0.5
# A face this close to the part's lowest point, facing down, is on the bed: far
# under a layer, and wide of the 0.001 mm a meshed part's bounding box moves by.
_ON_BED_MM = 0.05
_FACING_DOWN = -0.999
# The six ways a part can lie with a face of its bounding box on the bed,
# as it is built first.
_TURNS: tuple[tuple[tuple[float, float, float], float], ...] = (
    ((1.0, 0.0, 0.0), 0.0),
    ((1.0, 0.0, 0.0), 180.0),
    ((1.0, 0.0, 0.0), 90.0),
    ((1.0, 0.0, 0.0), -90.0),
    ((0.0, 1.0, 0.0), 90.0),
    ((0.0, 1.0, 0.0), -90.0),
)


@dataclass(frozen=True)
class BedContact:
    """How much of a part lies flat on the bed, against its footprint."""

    on_bed_mm2: float
    footprint_mm2: float

    @property
    def share(self) -> float:
        return self.on_bed_mm2 / self.footprint_mm2 if self.footprint_mm2 else 0.0

    @property
    def needs_support(self) -> bool:
        return self.share < MINIMUM_BED_SHARE


def bed_contact(shape: cq.Shape) -> BedContact:
    """The flat area facing down at the part's lowest point, and the area of
    its bounding box seen from above."""

    box = shape.BoundingBox()
    on_bed = sum(
        face.Area()
        for face in shape.Faces()
        if face.geomType() == "PLANE"
        and face.normalAt().z < _FACING_DOWN
        and abs(face.Center().z - box.zmin) < _ON_BED_MM
    )

    return BedContact(on_bed_mm2=on_bed, footprint_mm2=box.xlen * box.ylen)


def laid_flat(shape: cq.Shape) -> cq.Shape:
    """The part turned onto whichever face of its bounding box puts the most
    of it flat on the bed, keeping it as built where that is as good: for a
    plate, such as a mount plate or a stack top, whose best face the builder
    does not fix."""

    best = shape
    most = bed_contact(shape).on_bed_mm2

    for axis, angle in _TURNS[1:]:
        turned = shape.rotate((0, 0, 0), axis, angle)
        on_bed = bed_contact(turned).on_bed_mm2

        if on_bed > most + _ON_BED_MM:
            best, most = turned, on_bed

    return best

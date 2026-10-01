"""A guide's drill, its bushing, and its bores, and how they sit in the plate.

A bore is where a drill goes: a point on the part's top plane, a diameter, an
optional tilt, and a kind. A **printed** bore is a hole the printer makes,
sized for the drill with the printer's sliding clearance, and it wears. A
**bushing** bore is a pocket for a steel drill bushing, sized from the
bushing's outer diameter and the printer's press-fit clearance, with a hole
through it for the drill.

The bushing figures are the user's own: the engine's catalog holds no bushing
until a maker's datasheet has been read, so the file says where they came
from and the build says they are the user's.

Frame: the guide's own (see :mod:`zcad_core.features.guide_file`). A bore's
axis crosses the part's top plane, ``z == 0``, at ``(x, y)`` and runs down into
the part; the plate stands above that plane. A tilt leans the drill's lower end
toward +Y (about X) or +X (about Y) for a positive angle, so the upper end of
the bore sits the other way across the plate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware.electronics import board_outline

BORE_KINDS = ("printed", "bushing")
TILT_AXES = ("x", "y")
MAXIMUM_TILT_DEG = 45.0
# A tilt past this prints worst: the bore is cut across the layers.
STEEP_TILT_DEG = 20.0
MAXIMUM_BORES = 64
# A printed bore is this many drill diameters long, and at least this long. Both
# are design defaults, not measured values; a trial replaces them.
GUIDE_LENGTH_FACTOR = 1.5
MINIMUM_GUIDE_LENGTH_MM = 3.0
# The plate's thickness is rounded up to this step when the bores set it.
PLATE_STEP_MM = 0.5
# The chuck is a cylinder this long above the plate, and is slid up the axis
# until it clears, to find how far the drill reaches.
CHUCK_LENGTH_MM = 40.0
CHUCK_LIMIT_MM = 60.0
CHUCK_RESOLUTION_MM = 0.1
# A drill that would go this close to the part's underside is taken to exit it.
EXIT_MARGIN_MM = 1.0
_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class Drill:
    """The tool: its bit, its chuck, and how deep it is to cut. The engine looks
    none of this up; a drill is not a catalogued part."""

    diameter_mm: float
    chuck_diameter_mm: float
    depth_mm: float
    # How far the bit stands out of the chuck, when the user knows it.
    stickout_mm: float | None = None


@dataclass(frozen=True)
class Bushing:
    """A steel drill bushing, from the user's own figures."""

    inner_diameter_mm: float
    outer_diameter_mm: float
    length_mm: float
    flange_diameter_mm: float | None
    flange_thickness_mm: float | None
    source: str

    @property
    def body_length_mm(self) -> float:
        """The part that goes in the plate, without its flange."""

        return self.length_mm - (self.flange_thickness_mm or 0.0)


@dataclass(frozen=True)
class Bore:
    """One bore, as the file lists it, with the drill's defaults filled in."""

    identifier: str
    x_mm: float
    y_mm: float
    kind: str
    diameter_mm: float
    depth_mm: float
    tilt_about: str | None
    tilt_deg: float
    allow_exit: bool


@dataclass(frozen=True)
class Sections:
    """The drill, the bushing, and the bores of a guide file."""

    drill: Drill | None
    bushing: Bushing | None
    bores: tuple[Bore, ...]


@dataclass(frozen=True)
class PlannedBore:
    """A bore placed in the plate, with what that makes of it."""

    bore: Bore
    axis: tuple[float, float, float]
    entry: tuple[float, float]
    top: tuple[float, float]
    hole_diameter_mm: float
    pocket_diameter_mm: float | None
    guide_length_mm: float
    # Filled in once the guide is built and the chuck has been slid up the axis.
    chuck_standoff_mm: float | None = None
    bit_needed_mm: float | None = None

    @property
    def outer_radius_mm(self) -> float:
        return (self.pocket_diameter_mm or self.hole_diameter_mm) / 2

    def with_reach(self, standoff_mm: float, bit_needed_mm: float) -> PlannedBore:
        return PlannedBore(
            bore=self.bore,
            axis=self.axis,
            entry=self.entry,
            top=self.top,
            hole_diameter_mm=self.hole_diameter_mm,
            pocket_diameter_mm=self.pocket_diameter_mm,
            guide_length_mm=self.guide_length_mm,
            chuck_standoff_mm=standoff_mm,
            bit_needed_mm=bit_needed_mm,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.bore.identifier,
            "kind": self.bore.kind,
            "entry_mm": [round(v, 3) for v in self.entry],
            "top_mm": [round(v, 3) for v in self.top],
            "axis": [round(v, 4) for v in self.axis],
            "tilt_deg": self.bore.tilt_deg,
            "tilt_about": self.bore.tilt_about,
            "drill_diameter_mm": self.bore.diameter_mm,
            "hole_diameter_mm": round(self.hole_diameter_mm, 3),
            "pocket_diameter_mm": (
                None
                if self.pocket_diameter_mm is None
                else round(self.pocket_diameter_mm, 3)
            ),
            "guide_length_mm": round(self.guide_length_mm, 2),
            "depth_mm": self.bore.depth_mm,
            "chuck_standoff_mm": self.chuck_standoff_mm,
            "bit_needed_beyond_chuck_mm": self.bit_needed_mm,
        }


@dataclass(frozen=True)
class BorePlan:
    """The bores placed in a plate, or why they cannot be."""

    bores: tuple[PlannedBore, ...]
    plate_thickness_mm: float
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


# --- the file's sections --------------------------------------------------------


def _check_drill(data: Mapping[str, Any], findings: Findings) -> None:
    drill = section(data, "drill", findings, required=bool(data.get("bores")))

    if drill is None:
        return

    diameter = number(drill, "diameter_mm", "drill", findings, low=0.5, high=20.0)
    chuck = number(drill, "chuck_diameter_mm", "drill", findings, low=1.0, high=80.0)
    number(drill, "depth_mm", "drill", findings, low=0.1, high=200.0)
    number(drill, "stickout_mm", "drill", findings, low=1.0, high=400.0, required=False)

    if diameter is not None and chuck is not None and chuck < diameter:
        findings.errors.append(
            "drill.chuck_diameter_mm is under the drill's diameter; the chuck is "
            "wider than the bit it holds"
        )


def _check_bushing(
    data: Mapping[str, Any], findings: Findings, *, needed: bool
) -> None:
    bushing = section(data, "bushing", findings, required=needed)

    if bushing is None:
        return

    inner = number(
        bushing, "inner_diameter_mm", "bushing", findings, low=0.5, high=20.0
    )
    outer = number(
        bushing, "outer_diameter_mm", "bushing", findings, low=1.0, high=45.0
    )
    number(bushing, "length_mm", "bushing", findings, low=2.0, high=60.0)
    flange = bushing.get("flange_diameter_mm")
    thickness = bushing.get("flange_thickness_mm")

    if (flange is None) != (thickness is None):
        findings.errors.append(
            "bushing needs both flange_diameter_mm and flange_thickness_mm, or neither"
        )
    elif flange is not None:
        wide = number(
            bushing, "flange_diameter_mm", "bushing", findings, low=1.0, high=60.0
        )
        number(bushing, "flange_thickness_mm", "bushing", findings, low=0.3, high=20.0)

        if wide is not None and outer is not None and wide <= outer:
            findings.errors.append(
                "bushing.flange_diameter_mm must be wider than its outer diameter"
            )

    if inner is not None and outer is not None and outer <= inner:
        findings.errors.append(
            "bushing.outer_diameter_mm must exceed its inner diameter"
        )

    source = bushing.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "bushing.source must say where the figures came from: they are your "
            "own until a maker's datasheet has been read"
        )


def _check_tilt(entry: Mapping[str, Any], where: str, findings: Findings) -> None:
    about, tilt = entry.get("tilt_about"), entry.get("tilt_deg")

    if (about is None) != (tilt is None):
        findings.errors.append(
            f"{where} needs both tilt_about and tilt_deg, or neither"
        )

        return

    if about is None:
        return

    if about not in TILT_AXES:
        findings.errors.append(f"{where}.tilt_about must be one of {TILT_AXES}")

    number(
        entry,
        "tilt_deg",
        where,
        findings,
        low=-MAXIMUM_TILT_DEG,
        high=MAXIMUM_TILT_DEG,
    )


def _check_one_bore(
    entry: Any, index: int, data: Mapping[str, Any], findings: Findings
) -> str | None:
    where = f"bores[{index}]"

    if not isinstance(entry, Mapping):
        findings.errors.append(f"{where} must be an object")

        return None

    name = entry.get("identifier")

    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
        findings.errors.append(
            f"{where}.identifier must be a name of letters, digits, _ . -"
        )

    number(entry, "x_mm", where, findings, low=-500.0, high=500.0)
    number(entry, "y_mm", where, findings, low=-500.0, high=500.0)
    kind = entry.get("kind", "printed")

    if kind not in BORE_KINDS:
        findings.errors.append(
            f"{where}.kind must be one of {BORE_KINDS}, not {kind!r}"
        )

    number(entry, "diameter_mm", where, findings, low=0.5, high=20.0, required=False)
    number(entry, "depth_mm", where, findings, low=0.1, high=200.0, required=False)
    _check_tilt(entry, where, findings)

    if not isinstance(entry.get("allow_exit", False), bool):
        findings.errors.append(f"{where}.allow_exit must be true or false")

    bushing = data.get("bushing")

    if (
        kind == "bushing"
        and isinstance(bushing, Mapping)
        and bushing.get("flange_diameter_mm") is not None
        and isinstance(entry.get("tilt_deg"), int | float)
        and entry["tilt_deg"] != 0
    ):
        findings.errors.append(
            f"{where} tilts a flanged bushing, which needs a flat seat: use a "
            "printed bore or a bushing without a flange for a tilted hole"
        )

    return name if isinstance(name, str) else None


def check_bore_sections(data: Mapping[str, Any], findings: Findings) -> None:
    """Check the drill, the bushing, and the bores without reading the part."""

    bores = data.get("bores")

    if bores is not None and (
        not isinstance(bores, Sequence) or isinstance(bores, str)
    ):
        findings.errors.append("bores must be a list")

        return

    listed = list(bores or ())
    _check_drill(data, findings)
    _check_bushing(
        data,
        findings,
        needed=any(
            isinstance(b, Mapping) and b.get("kind") == "bushing" for b in listed
        ),
    )

    if len(listed) > MAXIMUM_BORES:
        findings.errors.append(f"A guide has at most {MAXIMUM_BORES} bores")

        return

    names = [
        name
        for index, entry in enumerate(listed)
        if (name := _check_one_bore(entry, index, data, findings)) is not None
    ]

    if len(set(names)) != len(names):
        findings.errors.append("Bore identifiers must be unique")

    _check_against_drill(data, listed, findings)


def _check_against_drill(
    data: Mapping[str, Any], listed: list[Any], findings: Findings
) -> None:
    drill, bushing = data.get("drill"), data.get("bushing")

    if not isinstance(drill, Mapping) or not isinstance(bushing, Mapping):
        return

    inner = bushing.get("inner_diameter_mm")

    for entry in listed:
        if not isinstance(entry, Mapping) or entry.get("kind") != "bushing":
            continue

        size = entry.get("diameter_mm", drill.get("diameter_mm"))

        if (
            isinstance(size, int | float)
            and isinstance(inner, int | float)
            and size > inner
        ):
            findings.errors.append(
                f"{entry.get('identifier')} drills {size:g} mm through a bushing "
                f"{inner:g} mm inside: the bit will not pass"
            )


def parse_sections(data: Mapping[str, Any]) -> Sections:
    """The drill, bushing, and bores of a checked file."""

    drill = None
    drill_data = data.get("drill")

    if drill_data is not None:
        drill = Drill(
            diameter_mm=float(drill_data["diameter_mm"]),
            chuck_diameter_mm=float(drill_data["chuck_diameter_mm"]),
            depth_mm=float(drill_data["depth_mm"]),
            stickout_mm=(
                float(drill_data["stickout_mm"])
                if drill_data.get("stickout_mm") is not None
                else None
            ),
        )

    bushing = None
    bushing_data = data.get("bushing")

    if bushing_data is not None:
        flange = bushing_data.get("flange_diameter_mm")
        bushing = Bushing(
            inner_diameter_mm=float(bushing_data["inner_diameter_mm"]),
            outer_diameter_mm=float(bushing_data["outer_diameter_mm"]),
            length_mm=float(bushing_data["length_mm"]),
            flange_diameter_mm=float(flange) if flange is not None else None,
            flange_thickness_mm=(
                float(bushing_data["flange_thickness_mm"])
                if flange is not None
                else None
            ),
            source=str(bushing_data["source"]),
        )

    bores = []

    for entry in data.get("bores") or ():
        assert drill is not None
        about = entry.get("tilt_about")
        bores.append(
            Bore(
                identifier=str(entry["identifier"]),
                x_mm=float(entry["x_mm"]),
                y_mm=float(entry["y_mm"]),
                kind=str(entry.get("kind", "printed")),
                diameter_mm=float(entry.get("diameter_mm", drill.diameter_mm)),
                depth_mm=float(entry.get("depth_mm", drill.depth_mm)),
                tilt_about=str(about) if about is not None else None,
                tilt_deg=float(entry.get("tilt_deg", 0.0)),
                allow_exit=bool(entry.get("allow_exit", False)),
            )
        )

    return Sections(drill=drill, bushing=bushing, bores=tuple(bores))


def printer_numbers(
    profile: Mapping[str, Any],
) -> tuple[dict[str, float], float, float]:
    """The profile's three fits, its minimum wall, and its minimum floor."""

    given = profile.get("tolerances_mm", {})
    fits: dict[str, float] = {}

    for name in (
        "sliding_clearance_per_side",
        "press_fit_clearance_per_side",
        "hole_oversize",
    ):
        if given.get(name) is None:
            raise ValueError(f"The printer profile has no tolerances_mm.{name}")

        fits[name] = float(given[name])

    minimums = profile.get("minimums_mm", {})

    return fits, float(minimums.get("wall", 1.2)), float(minimums.get("floor", 1.2))


# --- placing the bores ------------------------------------------------------------


def axis_of(bore: Bore) -> tuple[float, float, float]:
    """The drill's direction, a unit vector pointing down into the part."""

    angle = math.radians(bore.tilt_deg)

    if bore.tilt_about == "x":
        return 0.0, math.sin(angle), -math.cos(angle)

    if bore.tilt_about == "y":
        return math.sin(angle), 0.0, -math.cos(angle)

    return 0.0, 0.0, -1.0


def _hole_sizes(
    bore: Bore, bushing: Bushing | None, tolerances: Mapping[str, float]
) -> tuple[float, float | None]:
    """The CAD diameters of a bore's hole and of its bushing pocket. A printer
    prints holes small, so each is the intended hole plus the profile's
    ``hole_oversize``."""

    oversize = tolerances["hole_oversize"]

    if bore.kind == "bushing" and bushing is not None:
        pocket = (
            bushing.outer_diameter_mm
            + 2 * tolerances["press_fit_clearance_per_side"]
            + oversize
        )

        return bushing.inner_diameter_mm + oversize, pocket

    return (
        bore.diameter_mm + 2 * tolerances["sliding_clearance_per_side"] + oversize,
        None,
    )


def _guide_length(bore: Bore, bushing: Bushing | None) -> float:
    """How much plate, along the axis, the bore needs."""

    if bore.kind == "bushing" and bushing is not None:
        return bushing.body_length_mm

    return max(GUIDE_LENGTH_FACTOR * bore.diameter_mm, MINIMUM_GUIDE_LENGTH_MM)


def required_thickness(sections: Sections, tolerances: Mapping[str, float]) -> float:
    """The plate the bores need, rounded up to half a millimetre; zero for none."""

    needed = 0.0

    for bore in sections.bores:
        cosine = -axis_of(bore)[2]
        needed = max(needed, _guide_length(bore, sections.bushing) * cosine)

    return math.ceil(needed / PLATE_STEP_MM) * PLATE_STEP_MM


def axis_point(planned: PlannedBore, z: float) -> tuple[float, float]:
    """Where a bore's axis is at height ``z`` above the part's top plane."""

    scale = z / planned.axis[2]

    return (
        planned.entry[0] + scale * planned.axis[0],
        planned.entry[1] + scale * planned.axis[1],
    )


def _closest_approach(
    a: PlannedBore, b: PlannedBore, bottom: float, top: float
) -> float:
    """The least distance between two bores' axes over the plate, from its
    underside at ``bottom`` to its top at ``top``. It is the least of a convex
    function of ``z``, so it is at an end or at a vertex."""

    a0, a1 = axis_point(a, bottom), axis_point(a, top)
    b0, b1 = axis_point(b, bottom), axis_point(b, top)
    d0 = (a0[0] - b0[0], a0[1] - b0[1])
    d1 = (a1[0] - b1[0], a1[1] - b1[1])
    slope = (d1[0] - d0[0], d1[1] - d0[1])
    span = slope[0] ** 2 + slope[1] ** 2
    t = 0.0

    if span > 0:
        t = max(0.0, min(1.0, -(d0[0] * slope[0] + d0[1] * slope[1]) / span))

    return math.hypot(d0[0] + t * slope[0], d0[1] + t * slope[1])


def plan_bores(
    sections: Sections,
    *,
    height_mm: float,
    shadow: Sequence[tuple[float, float]],
    tolerances: Mapping[str, float],
    minimum_wall_mm: float,
    nest_wall_mm: float,
    plate_thickness_mm: float | None,
    default_plate_mm: float,
    plate_base_mm: float = 0.0,
) -> BorePlan:
    """Place every bore in the plate and check it against the part and its
    neighbours. Every problem is collected, so the user sees them all.

    ``plate_base_mm`` is the height of the plate's underside above the part's
    top plane: 0 when the plate rests on the part, and the gap for a ledge nest,
    where it stands clear."""

    errors: list[str] = []
    warnings: list[str] = []
    needed = required_thickness(sections, tolerances)

    if plate_thickness_mm is not None:
        thickness = plate_thickness_mm

        if sections.bores and thickness < needed - 1e-9:
            errors.append(
                f"plate.thickness_mm is {thickness:g}; the bores need {needed:g} mm: "
                "leave it out and the plate is sized to them"
            )
    elif sections.bores:
        thickness = needed
    else:
        thickness = default_plate_mm

    planned: list[PlannedBore] = []
    clearance = tolerances["sliding_clearance_per_side"]

    for bore in sections.bores:
        axis = axis_of(bore)
        hole, pocket = _hole_sizes(bore, sections.bushing, tolerances)
        item = PlannedBore(
            bore=bore,
            axis=axis,
            entry=(bore.x_mm, bore.y_mm),
            top=(0.0, 0.0),
            hole_diameter_mm=hole,
            pocket_diameter_mm=pocket,
            guide_length_mm=_guide_length(bore, sections.bushing),
        )
        top = axis_point(item, plate_base_mm + thickness)
        item = PlannedBore(
            bore=bore,
            axis=axis,
            entry=item.entry,
            top=top,
            hole_diameter_mm=hole,
            pocket_diameter_mm=pocket,
            guide_length_mm=item.guide_length_mm,
        )
        planned.append(item)
        errors.extend(
            _check_placement(
                item,
                sections=sections,
                height_mm=height_mm,
                shadow=shadow,
                minimum_wall_mm=minimum_wall_mm,
                outer_margin_mm=clearance + nest_wall_mm,
                thickness=thickness,
                plate_base_mm=plate_base_mm,
                warnings=warnings,
            )
        )

    for index, first in enumerate(planned):
        for second in planned[index + 1 :]:
            gap = (
                _closest_approach(
                    first, second, plate_base_mm, plate_base_mm + thickness
                )
                - _effective_radius(first, sections)
                - _effective_radius(second, sections)
            )

            if gap < minimum_wall_mm - 1e-9:
                errors.append(
                    f"Bores {first.bore.identifier} and {second.bore.identifier} "
                    f"leave {max(gap, 0.0):.2f} mm of plate between them; the "
                    f"printer's least wall is {minimum_wall_mm:g} mm"
                )

    if sections.bores and any(p.bore.kind == "printed" for p in planned):
        warnings.append(
            "A printed bore wears as the bit cuts it: it is good for a few holes, "
            "and a bushing bore lasts"
        )

    return BorePlan(tuple(planned), thickness, tuple(errors), tuple(warnings))


def _effective_radius(planned: PlannedBore, sections: Sections) -> float:
    """How wide a bore stands in the plate: its pocket, or the flange resting on
    its top, which must clear a neighbour too."""

    bushing = sections.bushing

    if (
        planned.bore.kind == "bushing"
        and bushing is not None
        and bushing.flange_diameter_mm is not None
    ):
        return max(bushing.flange_diameter_mm / 2, planned.outer_radius_mm)

    return planned.outer_radius_mm


def _check_placement(
    item: PlannedBore,
    *,
    sections: Sections,
    height_mm: float,
    shadow: Sequence[tuple[float, float]],
    minimum_wall_mm: float,
    outer_margin_mm: float,
    thickness: float,
    plate_base_mm: float,
    warnings: list[str],
) -> list[str]:
    bore, name = item.bore, item.bore.identifier
    errors: list[str] = []
    radius = item.outer_radius_mm
    dx, dy, dz = item.axis

    # The bore's foot on the part: inside its shadow with a wall to spare.
    foot = board_outline.depth_inside(shadow, item.entry)

    if foot < radius + minimum_wall_mm:
        errors.append(
            f"{name} stands at ({bore.x_mm:g}, {bore.y_mm:g}), {max(foot, 0.0):.2f} mm "
            f"inside the part's edge; it needs {radius + minimum_wall_mm:.2f} mm for "
            "its bore and a wall of plate"
        )

    # Its head on the plate: inside the plate's outline, with a wall unless a
    # flange rests there.
    flange = (
        sections.bushing.flange_diameter_mm
        if bore.kind == "bushing" and sections.bushing is not None
        else None
    )
    head_radius = flange / 2 if flange else radius
    head_wall = 0.0 if flange else minimum_wall_mm
    head = board_outline.depth_inside(shadow, item.top) + outer_margin_mm

    if head < head_radius + head_wall:
        errors.append(
            f"{name}'s top, at ({item.top[0]:.1f}, {item.top[1]:.1f}), is only "
            f"{max(head, 0.0):.2f} mm inside the plate's edge; it needs "
            f"{head_radius + head_wall:.2f} mm: move it, or tilt it less"
        )

    # A plate that stands clear of the part has an underside of its own, which
    # the bore must also leave a wall inside.
    if plate_base_mm > 0:
        underside = axis_point(item, plate_base_mm)
        under = board_outline.depth_inside(shadow, underside) + outer_margin_mm

        if under < radius + minimum_wall_mm:
            errors.append(
                f"{name} leaves the plate's underside at ({underside[0]:.1f}, "
                f"{underside[1]:.1f}), only {max(under, 0.0):.2f} mm inside its "
                f"edge; it needs {radius + minimum_wall_mm:.2f} mm"
            )

    # The drill's depth: not past the part's underside, and not out its side.
    cosine = -dz
    tip_z = -bore.depth_mm * cosine

    if tip_z < -height_mm + EXIT_MARGIN_MM and not bore.allow_exit:
        errors.append(
            f"{name} drills {bore.depth_mm:g} mm along its axis, to {-tip_z:.1f} mm "
            f"down in a part {height_mm:.1f} mm high: the bit would come out of the "
            "underside with nothing to take it. Shorten the depth, or set "
            "allow_exit if you will support it"
        )

    tip = (item.entry[0] + bore.depth_mm * dx, item.entry[1] + bore.depth_mm * dy)
    side = board_outline.depth_inside(shadow, tip)

    if side < bore.diameter_mm / 2 + minimum_wall_mm:
        errors.append(
            f"{name}'s drill would reach ({tip[0]:.1f}, {tip[1]:.1f}), {max(side, 0.0):.2f} "
            "mm inside the part's edge: it would break out of the side"
        )

    if abs(bore.tilt_deg) > STEEP_TILT_DEG:
        warnings.append(
            f"{name} is tilted {abs(bore.tilt_deg):g} degrees; a bore that steep "
            "prints across its layers and comes out roughest"
        )

    return errors


def play_bounds(
    planned: PlannedBore,
    sections: Sections,
    tolerances: Mapping[str, float],
    nest_clearance_mm: float,
) -> tuple[float, float]:
    """The most a drill can sit off its bore's axis, from the clearances alone:
    at the part's surface, and at the bottom of the hole, where the drill's
    tilt in the bore adds to it. It is a bound from the printer profile's
    provisional tolerances, and it is not a measured accuracy."""

    bushing = sections.bushing

    if planned.bore.kind == "bushing" and bushing is not None:
        bore_play = (bushing.inner_diameter_mm - planned.bore.diameter_mm) / 2
        seat = tolerances["press_fit_clearance_per_side"]
    else:
        bore_play = tolerances["sliding_clearance_per_side"]
        seat = 0.0

    entry = nest_clearance_mm + seat + bore_play
    tip = entry + planned.bore.depth_mm * 2 * bore_play / planned.guide_length_mm

    return round(entry, 3), round(tip, 3)


# --- the chuck --------------------------------------------------------------------


def _chuck(
    planned: PlannedBore, standoff: float, plate_top_z: float, radius: float
) -> cq.Solid:
    """The chuck, a cylinder on the bore's axis ``standoff`` above the plate."""

    up = cq.Vector(-planned.axis[0], -planned.axis[1], -planned.axis[2])
    base = cq.Vector(planned.top[0], planned.top[1], plate_top_z)

    return cq.Solid.makeCylinder(
        radius, CHUCK_LENGTH_MM, pnt=base + up * standoff, dir=up
    )


def chuck_standoff(
    assembly: cq.Shape, planned: PlannedBore, drill: Drill, plate_top_z: float
) -> float:
    """How far up its axis the chuck must stand before it clears the guide,
    found by sliding it up until it stops meeting the plate and any flange.

    Raises ``ValueError`` if it never clears: a bore leaning so far that the
    chuck cannot stand on the plate."""

    radius = drill.chuck_diameter_mm / 2

    def clear(standoff: float) -> bool:
        chuck = _chuck(planned, standoff, plate_top_z, radius)

        return intersection_volume(assembly, chuck) <= _TOLERANCE_MM3

    if clear(0.0):
        return 0.0

    high = 1.0

    while not clear(high):
        high *= 2

        if high > CHUCK_LIMIT_MM:
            raise ValueError(
                f"{planned.bore.identifier}: the {drill.chuck_diameter_mm:g} mm chuck "
                "cannot clear the guide at any height along its axis"
            )

    low = high / 2 if high > 1.0 else 0.0

    while high - low > CHUCK_RESOLUTION_MM:
        middle = (low + high) / 2

        if clear(middle):
            high = middle
        else:
            low = middle

    return round(high, 2)


def bit_needed(
    planned: PlannedBore, standoff: float, thickness: float, gap: float = 0.0
) -> float:
    """The bit that must stand beyond the chuck's face to cut to depth: up from
    the plate to the chuck, through the plate, across the gap to the part when
    the plate stands clear of it, and down the hole."""

    cosine = -planned.axis[2]

    return round(standoff + (thickness + gap) / cosine + planned.bore.depth_mm, 2)


def flange_solids(
    planned: Sequence[PlannedBore], sections: Sections, plate_top_z: float
) -> list[cq.Solid]:
    """The flanges of the bushings, standing on the plate's top: they are in
    the chuck's way, and are not part of the printed guide."""

    bushing = sections.bushing
    found: list[cq.Solid] = []

    if bushing is None or bushing.flange_diameter_mm is None:
        return found

    for item in planned:
        if item.bore.kind != "bushing":
            continue

        found.append(
            cq.Solid.makeCylinder(
                bushing.flange_diameter_mm / 2,
                bushing.flange_thickness_mm or 0.0,
                pnt=cq.Vector(item.top[0], item.top[1], plate_top_z),
                dir=cq.Vector(0, 0, 1),
            )
        )

    return found

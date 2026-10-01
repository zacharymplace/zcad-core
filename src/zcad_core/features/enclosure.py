"""Build a printable two-part enclosure around a board-and-display assembly.

The base carries the floor, walls, board supports, a heat-set insert boss in
each corner, and the cable opening; the lid carries screw clearance holes
over the bosses and the display window. A board with mounting holes sits on
standoffs; one without sits in a snap-in cradle. Both parts are derived from
the assembly through
:func:`~zcad_core.assemblies.derive_enclosure_specification`, and the
builder refuses to return an enclosure whose features intersect any part of
the assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import cadquery as cq

from zcad_core.assemblies import (
    DeviceAssembly,
    EnclosureSpecification,
    derive_enclosure_specification,
)
from zcad_core.features.board_cradle import BoardCradleParameters, add_board_cradle
from zcad_core.features.connector_cutouts import (
    MINIMUM_OPENING_WEB_MM,
    ConnectorCutoutParameters,
    cut_connector_opening,
    merge_close_openings,
)
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
from zcad_core.features.enclosure_lid import (
    LIP_DEPTH_MM,
    SNAP_SKIRT_DEPTH_MM,
    VENT_RIM_MM,
    Cavity,
    countersinks,
    notch_skirt,
    relief_slits,
    skirt,
    snap_grooves,
    snap_ridges,
    vents,
)
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_AMBIENT_C,
    DEFAULT_SERVICE_LIMIT_C,
    ThermalEstimate,
    estimate_thermal,
    require_not_too_hot,
)
from zcad_core.features.fan_bay import (
    FAN_DIRECTIONS,
    FAN_POSITIONS,
    FanPlan,
    FanReport,
    cut_fan_bay,
    fan_report,
    plan_fan,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.lid_hinge import HINGE_WEB_DEPTH_MM, HingeReport, add_hinge
from zcad_core.features.lid_slide import (
    SLIDE_VENT_DROP_MM,
    SlideReport,
    add_slide,
    slide_clearance_error,
)
from zcad_core.features.mounts import (
    MOUNTS,
    MountPads,
    MountPlate,
    add_mount_pads,
    build_mount,
    mount_pads,
    require_mount_clear,
)
from zcad_core.features.pcb_mounts import (
    BoardHolePattern,
    add_pcb_standoff,
    board_hole_pattern,
)
from zcad_core.features.vent_patterns import (
    PATTERNS,
    VentFill,
    VentReport,
    add_lid_outlets,
    add_wall_inlets,
)
from zcad_core.geometry.boxes import box_between
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    BoardSpec,
    DisplaySpec,
    FastenerSpec,
    get_fan,
    get_fastener,
    list_fans,
)

# Bosses and standoffs start this far down inside the floor, so they fuse to
# it and their pilot holes do not break through the underside.
_FLOOR_EMBED_MM = 0.5
_INTERFERENCE_TOLERANCE_MM3 = 1e-6
# Corner bosses overlap both walls by this much. Tangent contact leaves
# zero-width seams that mesh as non-manifold edges and fail STL validation.
_BOSS_WALL_OVERLAP_MM = 0.5
# The cable opening's cutter reaches this far past the wall's inner face.
_OPENING_OVERCUT_MM = 0.5
# An automatic side clearance starts at the minimum and widens X and Y
# independently in steps, taking the smallest footprint that works. Bosses
# must also clear the board outline grown by the support margin, so
# standoffs and cradle clips never fuse to a boss.
_MINIMUM_SIDE_CLEARANCE_MM = 2.0
# A hinged lid swings what hangs from it toward the closure wall by about
# b^2 / 2a, for b below the axis and a from it: 1 mm or so for a display's
# retainer, so the walls stand a millimetre further off.
_HINGE_SIDE_CLEARANCE_MM = 3.0
_AUTOMATIC_WIDENING_MM = tuple(0.5 * step for step in range(25))
_SUPPORT_MARGIN_MM = 2.0
# Supports are notched this far clear of the parts under the board.
_UNDER_BOARD_CLEARANCE_MM = 0.3
_DISPLAY_POST_WALL_MM = 1.2
# Printers print holes small far more often than large, and the cradle's
# 0.3 mm fit leaves little room to shrink.
HOLE_COMPENSATION_RANGE_MM = (-0.2, 1.0)
LID_ATTACHMENTS = ("screws", "snap", "hinge", "slide")
# A flat-head screw's head is about twice its thread (ISO 10642 M3: 6 mm).
_COUNTERSINK_HEAD_ALLOWANCE_MM = 0.0
# The builder's default fits, before hole compensation widens them.
_OPENING_CLEARANCE_MM = 0.6
# A board's declared wall openings pass a plug's shell, not just the socket:
# this much wider on each side and taller, as the group enclosure's ports.
_PLUG_MARGIN_MM = 1.5
# Slots through the lid over a part that draws air from above, such as a
# cooler's fan, as the group enclosure's.
_LID_VENT_WIDTH_MM = 2.4
_LID_VENT_PITCH_MM = 5.0
_CRADLE_CLEARANCE_MM = 0.3
_RETAINER_CLEARANCE_MM = 0.3


@dataclass(frozen=True)
class EnclosureDesign:
    """Wall, floor, and lid thicknesses, the lid fastener, the gaps between
    the hardware and the cavity, and the cable plug the opening must pass.

    ``side_clearance_mm`` sets how far the walls, and so the corner bosses,
    stand off the hardware; left unset, it starts at 2 mm and widens X and Y
    separately, in 0.5 mm steps, to the smallest footprint at which the
    bosses clear the hardware and the cable opening; ``bottom_clearance_mm`` is the standoff height
    under the lowest part; ``top_clearance_mm`` is the gap under the lid.
    The cable opening is at least ``cable_plug_width_mm`` by
    ``cable_plug_height_mm``, so a cable's moulded plug body reaches the
    connector through the wall and the gap inside it; the defaults fit
    common USB-C and micro-USB cables. Set both to zero for an opening sized
    to the connector alone. ``display_retainer`` holds the display under
    its window: screw posts over a display's mounting holes, for
    ``display_fastener`` self-tapping screws, or, for a display without
    holes, corner posts and snap clips.
    """

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 2.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    side_clearance_mm: float | None = None
    bottom_clearance_mm: float = 2.0
    top_clearance_mm: float = 2.0
    cable_plug_width_mm: float = 12.5
    cable_plug_height_mm: float = 7.5
    display_retainer: bool = True
    display_fastener: str = "M2"
    # How much wider than intended every hole and opening is modelled, to
    # make up for a printer that prints them undersized. A trial measures
    # the intended sizes; ``enclosure revise`` sets this from the shortfall.
    hole_compensation_mm: float = 0.0
    # "screws" into heat-set inserts, a "snap" lid with no fasteners, a
    # "hinge" lid on a pin that closes with a catch, or a "slide" lid that
    # runs in grooves and is held by a detent.
    lid_attachment: str = "screws"
    # The gap, per side, around a sliding lid; the printer profile recommends
    # one, and the export checks this against it.
    slide_clearance_mm: float = 0.2
    # The fastener used as the hinge pin (with a nut), for a "hinge" lid.
    hinge_pin: str = "M3"
    # For the temperature estimate: power the catalog lacks, in watts (a hat,
    # an SSD), the room's temperature, and the material's limit for the air
    # inside. ``allow_hot`` builds a box the estimate says is too hot.
    declared_power_w: float = 0.0
    # The coefficient the estimate uses, W/m2K, and where it came from: the
    # default, or a profile pooled from measured trials.
    convection_w_m2k: float = CONVECTION_W_M2K
    convection_source: str = "the default, an assumption"
    ambient_c: float = DEFAULT_AMBIENT_C
    service_limit_c: float = DEFAULT_SERVICE_LIMIT_C
    allow_hot: bool = False
    # Sink flat-head lid screws flush (screwed lids only).
    countersunk_screws: bool = False
    # A skirt under a screwed lid that keys it onto the base.
    locating_lip: bool = False
    # Vertical vent slots in each long wall that carries no opening.
    vent_slots: int = 0
    # A vent pattern sized to a free area, in mm2, for each of the inlets low
    # in the long walls and the outlets in the lid; the outlets are never
    # smaller. ``vent_slots`` is a separate, fixed set of slots.
    vent_pattern: str = "slots"
    vent_area_mm2: float = 0.0
    # A catalogued fan, inside the lid or against a long wall, screwed from
    # outside through a guarded round opening. Which way it blows is recorded;
    # its offset from the middle of the lid (X, Y) or the wall (along, up).
    fan: str | None = None
    fan_position: str = "lid"
    fan_direction: str = "out"
    fan_offset_x_mm: float = 0.0
    fan_offset_y_mm: float = 0.0
    # Openings in one wall closer than this merge into one, so no thin web
    # of wall is left between them; zero keeps every opening apart.
    minimum_opening_web_mm: float = MINIMUM_OPENING_WEB_MM
    # A mount plate that bolts to four pads under the floor; none by default.
    mount: str | None = None
    mount_plate_mm: float = 4.0

    def validate(self) -> None:
        if self.mount is not None and self.mount not in MOUNTS:
            raise ValueError(f"mount must be one of {MOUNTS}")

        for name in ("wall_mm", "floor_mm", "lid_mm", "boss_radial_wall_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        low, high = HOLE_COMPENSATION_RANGE_MM

        if not low <= self.hole_compensation_mm <= high:
            raise ValueError(f"hole_compensation_mm must be from {low} to {high} mm")

        if self.side_clearance_mm is not None and self.side_clearance_mm < 0:
            raise ValueError("side_clearance_mm must not be negative")

        self._validate_lid()
        self._validate_fan()
        self._validate_thermal()

        for name in (
            "bottom_clearance_mm",
            "top_clearance_mm",
            "cable_plug_width_mm",
            "cable_plug_height_mm",
            "minimum_opening_web_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

    def _validate_fan(self) -> None:
        if self.fan is None:
            return

        if self.fan not in list_fans():
            raise ValueError(f"fan must be one of {list_fans()}")

        if self.fan_position not in FAN_POSITIONS:
            raise ValueError(f"fan_position must be one of {FAN_POSITIONS}")

        if self.fan_direction not in FAN_DIRECTIONS:
            raise ValueError(f"fan_direction must be one of {FAN_DIRECTIONS}")

    def _validate_thermal(self) -> None:
        if self.declared_power_w < 0:
            raise ValueError("declared_power_w must not be negative")

        if self.service_limit_c <= self.ambient_c:
            raise ValueError("service_limit_c must be above ambient_c")

        if self.convection_w_m2k <= 0:
            raise ValueError("convection_w_m2k must be greater than zero")

    def _validate_lid(self) -> None:
        if self.lid_attachment not in LID_ATTACHMENTS:
            raise ValueError(f"lid_attachment must be one of {LID_ATTACHMENTS}")

        snap = self.lid_attachment == "snap"
        hinge = self.lid_attachment == "hinge"
        slide = self.lid_attachment == "slide"

        if (snap or hinge or slide) and self.countersunk_screws:
            raise ValueError(
                "A snap-fit, hinged, or sliding lid has no screws to countersink"
            )

        if slide and self.locating_lip:
            raise ValueError("A sliding lid has no lip: it would catch in its grooves")

        error = slide_clearance_error(self.slide_clearance_mm) if slide else None

        if error is not None:
            raise ValueError(error)

        if snap and self.locating_lip:
            raise ValueError("A snap-fit lid already locates on its skirt")

        if hinge and self.locating_lip:
            raise ValueError(
                "A hinged lid has no lip: it would catch as the lid swings"
            )

        if self.vent_slots < 0:
            raise ValueError("vent_slots must not be negative")

        if self.vent_pattern not in PATTERNS:
            raise ValueError(f"vent_pattern must be one of {PATTERNS}")

        if self.vent_area_mm2 < 0:
            raise ValueError("vent_area_mm2 must not be negative")

        if self.vent_area_mm2 and self.vent_slots:
            raise ValueError("Set vent_slots or vent_area_mm2, not both")

        if self.vent_pattern != "slots" and not self.vent_area_mm2:
            raise ValueError("A vent pattern needs a vent_area_mm2 to size it to")

    @property
    def skirt_depth_mm(self) -> float | None:
        """How far the lid's skirt reaches into the base, if it has one."""
        if self.lid_attachment == "snap":
            return SNAP_SKIRT_DEPTH_MM

        return LIP_DEPTH_MM if self.locating_lip else None


@dataclass(frozen=True)
class Enclosure:
    """The two printable parts and the geometry they were built from."""

    base: cq.Workplane
    lid: cq.Workplane
    specification: EnclosureSpecification
    design: EnclosureDesign
    side_clearance_mm: tuple[float, float]
    fastener: FastenerSpec
    fastener_positions: tuple[tuple[float, float], ...]
    board_support: str
    display_support: str | None = None
    # Screws up through the display's PCB into its posts: how many, and the
    # longest that fits (PCB thickness plus post length).
    display_screw_count: int = 0
    display_screw_reach_mm: float | None = None
    # The cable opening first, then one per board part reached through a wall.
    openings: tuple[ConnectorCutoutParameters, ...] = ()
    # The pads under the floor and the plate that bolts to them, when the
    # design asks for a mount.
    mount_pads: MountPads | None = None
    mount: MountPlate | None = None
    # The hinge and its catch, for a hinged lid.
    hinge: HingeReport | None = None
    # The grooves and detent, for a sliding lid.
    slide: SlideReport | None = None
    # The temperature estimate for the closed box.
    thermal: ThermalEstimate | None = None
    # The vent pattern, when the design asks for one.
    vents: VentReport | None = None
    # The fan bay, when the design asks for one, and the fan's frame, which is
    # not printed but is shown in the review model.
    fan: FanReport | None = None
    fan_body: cq.Shape | None = None


def build_enclosure(
    assembly: DeviceAssembly,
    *,
    board: BoardSpec,
    display: DisplaySpec | None = None,
    board_identifier: str = "board",
    display_identifier: str = "display",
    connector_identifier: str = "board_connector",
    design: EnclosureDesign | None = None,
) -> Enclosure:
    """Build the base and lid for an assembly's board, display, and cable.

    Raises ``ValueError`` when a boss, support, or opening would intersect a
    part of the assembly or another feature; a larger ``side_clearance_mm``
    moves the corner bosses away from the board.
    """

    design = design or EnclosureDesign()
    design.validate()
    fastener = get_fastener(design.fastener)
    if design.side_clearance_mm is None:
        spec, side_clearance = _automatic_specification(
            assembly,
            design=design,
            fastener=fastener,
            board_identifier=board_identifier,
            connector_identifier=connector_identifier,
            display_identifier=display_identifier if display is not None else None,
            board=board,
        )
    else:
        spec = _specification(
            assembly, design, design.side_clearance_mm, connector_identifier
        )
        side_clearance = (design.side_clearance_mm, design.side_clearance_mm)

    cavity_top = spec.bottom_z_mm + spec.inner_height_mm
    positions = _corner_boss_positions(spec, fastener, design)

    base = _shell(spec, design)

    if positions:
        base = base.union(_corner_fills(spec, positions))

    for x, y in positions:
        base = add_heat_set_insert_boss(
            base,
            parameters=_compensated_boss(
                InsertBossParameters.from_fastener(
                    fastener=fastener,
                    x=x,
                    y=y,
                    base_height_mm=_FLOOR_EMBED_MM,
                    base_z_mm=spec.bottom_z_mm - _FLOOR_EMBED_MM,
                    boss_height_mm=spec.inner_height_mm,
                    radial_wall_mm=design.boss_radial_wall_mm,
                ),
                design.hole_compensation_mm,
            ),
        )

    base, board_support = _add_board_support(
        base,
        assembly=assembly,
        board=board,
        board_identifier=board_identifier,
        spec=spec,
        hole_compensation_mm=design.hole_compensation_mm,
    )
    base = _clear_parts_under_board(base, spec, assembly, board_identifier)
    openings = _openings(spec, design, assembly, board, board_identifier)
    base = _cut_openings(base, openings, design, fastener, positions)
    cavity = _cavity(spec, design)
    base = _lid_options_in_base(base, cavity, design, fastener, positions, openings)
    base, cooling = _plan_cooling(
        base,
        cavity,
        design,
        assembly,
        display,
        display_identifier,
        openings,
        fastener,
        positions,
    )
    lid = _lid(spec, design, cavity_top, fastener, positions)
    lid = _lid_options_in_lid(lid, cavity, design, fastener, positions, openings)

    display_support = None
    display_screws: tuple[int, float] | None = None

    if display is not None:
        lid, display_support, display_screws = _add_display_features(
            lid,
            assembly=assembly,
            display=display,
            display_identifier=display_identifier,
            design=design,
            cavity_top=cavity_top,
        )

    lid = _cut_lid_vents(
        lid, assembly, board_identifier, display_identifier, cavity_top, design
    )
    base, lid, guard = _cut_fan(base, lid, cooling, design)

    hinge = None

    if design.lid_attachment == "hinge":
        base, lid, hinge = add_hinge(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            pin=get_fastener(design.hinge_pin),
            hole_compensation_mm=design.hole_compensation_mm,
            openings=cooling.feature_openings,
            hardware=cooling.shapes,
            carried=cooling.carried,
        )

    slide = None

    if design.lid_attachment == "slide":
        base, lid, slide = add_slide(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            clearance_mm=design.slide_clearance_mm,
            hole_compensation_mm=design.hole_compensation_mm,
            openings=cooling.feature_openings,
            hardware=cooling.shapes,
            carried=cooling.carried,
        )

    lid, vents_report, fan_summary = _finish_cooling(
        lid, cavity, design, cooling, openings, guard
    )

    pads = None
    mount = None

    if design.mount is not None:
        half_x = spec.inner_width_mm / 2 + design.wall_mm
        half_y = spec.inner_depth_mm / 2 + design.wall_mm
        pads = mount_pads(
            x_span_mm=(spec.center_x_mm - half_x, spec.center_x_mm + half_x),
            y_span_mm=(spec.center_y_mm - half_y, spec.center_y_mm + half_y),
            floor_underside_z_mm=spec.bottom_z_mm - design.floor_mm,
            floor_mm=design.floor_mm,
            wall_mm=design.wall_mm,
            fastener=fastener,
            hole_compensation_mm=design.hole_compensation_mm,
        )
        base = add_mount_pads(base, pads)
        mount = build_mount(
            design.mount,
            pads,
            fastener=fastener,
            plate_mm=design.mount_plate_mm,
            hole_compensation_mm=design.hole_compensation_mm,
        )
        require_mount_clear(base, mount)

    _require_clear_of_assembly(assembly, base=base, lid=lid)
    _require_parts_clear(base, lid)
    thermal = _thermal_estimate(
        base, lid, assembly, board=board, display=display, design=design
    )

    return Enclosure(
        base=base,
        lid=lid,
        specification=spec,
        design=design,
        side_clearance_mm=side_clearance,
        fastener=fastener,
        fastener_positions=positions,
        board_support=board_support,
        display_support=display_support,
        openings=tuple(openings),
        display_screw_count=display_screws[0] if display_screws else 0,
        display_screw_reach_mm=display_screws[1] if display_screws else None,
        mount_pads=pads,
        mount=mount,
        hinge=hinge,
        slide=slide,
        thermal=thermal,
        vents=vents_report,
        fan=fan_summary,
        fan_body=cooling.fan_plan.body if cooling.fan_plan else None,
    )


def _is_closed(design: EnclosureDesign, assembly: DeviceAssembly) -> bool:
    """Whether the box has nothing that moves air: no vent, no fan, and no
    lid slots over a part that draws air from above."""

    lid_slots = any(
        component.metadata.get("lid_vent") for component in assembly.components
    )

    return not (design.vent_slots or design.vent_area_mm2 or design.fan or lid_slots)


def _thermal_estimate(
    base: cq.Workplane,
    lid: cq.Workplane,
    assembly: DeviceAssembly,
    *,
    board: BoardSpec,
    display: DisplaySpec | None,
    design: EnclosureDesign,
) -> ThermalEstimate:
    """Estimate the closed box, refusing one too hot unless allowed."""

    box = _all_solids(base).BoundingBox()
    cap = _all_solids(lid).BoundingBox()
    size = (
        max(box.xmax, cap.xmax) - min(box.xmin, cap.xmin),
        max(box.ymax, cap.ymax) - min(box.ymin, cap.ymin),
        max(box.zmax, cap.zmax) - min(box.zmin, cap.zmin),
    )
    parts = [board.identifier]

    if display is not None:
        parts.append(display.identifier)

    if design.fan:
        parts.append(design.fan)

    # A fitted Active Cooler is one more source of heat, its fan; the catalog
    # has no figure for it, so the estimate names it as unknown.
    for component in assembly.components:
        hardware = component.metadata.get("hardware_identifier")

        if hardware and str(hardware).endswith(":active-cooler-fan"):
            parts.append(str(hardware))

    estimate = estimate_thermal(
        parts,
        outer_size_mm=size,
        declared_power_w=design.declared_power_w,
        ambient_c=design.ambient_c,
        limit_c=design.service_limit_c,
        coefficient_w_m2k=design.convection_w_m2k,
        coefficient_source=design.convection_source,
        closed=_is_closed(design, assembly),
    )
    require_not_too_hot(estimate, allow_hot=design.allow_hot)

    return estimate


@dataclass
class _Cooling:
    """What the fan and the wall vents leave for the rest of the build: the
    parts inside, and those the lid carries, for the hinge and slide to sweep;
    the openings that take a wall; and the fan's plan and the inlets cut."""

    shapes: dict[str, cq.Shape]
    carried: dict[str, cq.Shape]
    feature_openings: list[ConnectorCutoutParameters]
    fan_plan: FanPlan | None
    inlets: list[VentFill]


def _plan_cooling(
    base: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    display: DisplaySpec | None,
    display_identifier: str,
    openings: list[ConnectorCutoutParameters],
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> tuple[cq.Workplane, _Cooling]:
    """Place the fan, if there is one, and cut the wall inlets, if there are
    any; nothing is cut in the lid yet."""

    shapes = {
        component.identifier: _all_solids(component.transformed_geometry())
        for component in assembly.components
        if component.identifier != display_identifier
    }
    # A display screws to the lid's posts, so it goes where the lid does.
    carried = (
        {
            display_identifier: _all_solids(
                assembly.get(display_identifier).transformed_geometry()
            )
        }
        if display is not None
        else {}
    )
    cooling = _Cooling(shapes, carried, list(openings), None, [])

    if design.fan:
        plan = plan_fan(
            base,
            cavity,
            fan=get_fan(design.fan),
            position=design.fan_position,
            direction=design.fan_direction,
            lid_mm=design.lid_mm,
            offset_mm=(design.fan_offset_x_mm, design.fan_offset_y_mm),
            openings=openings,
            wall_top_z_mm=_vent_top_z(cavity, design),
            hardware={**shapes, **carried},
            display_bounds=(
                _bounds(assembly, display_identifier) if display is not None else None
            ),
        )
        cooling.fan_plan = plan

        # A fan in a wall takes that wall, as an opening does, and is fixed;
        # one in the lid goes where the lid goes.
        if plan.opening is not None:
            cooling.feature_openings.append(plan.opening)
            shapes["fan"] = plan.body
        else:
            carried["fan"] = plan.body

    if design.vent_area_mm2:
        base, cooling.inlets = add_wall_inlets(
            base,
            cavity,
            kind=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            blocked_edges=[opening.edge for opening in cooling.feature_openings],
            top_z_mm=_vent_top_z(cavity, design),
            corner_keepout_mm=_vent_corner_keepout(fastener, design, positions),
            obstruction=cooling.fan_plan.body
            if cooling.fan_plan and cooling.fan_plan.opening
            else None,
        )

    return base, cooling


def _cut_fan(
    base: cq.Workplane,
    lid: cq.Workplane,
    cooling: _Cooling,
    design: EnclosureDesign,
) -> tuple[cq.Workplane, cq.Workplane, VentFill | None]:
    """Cut the fan's guard and mounting holes into the lid or the wall."""

    plan = cooling.fan_plan

    if plan is None:
        return base, lid, None

    screw = get_fastener(plan.fan.screw)

    if plan.position == "lid":
        lid, guard = cut_fan_bay(
            lid,
            plan,
            plate_mm=design.lid_mm,
            screw=screw,
            hole_compensation_mm=design.hole_compensation_mm,
        )
    else:
        base, guard = cut_fan_bay(
            base,
            plan,
            plate_mm=design.wall_mm,
            screw=screw,
            hole_compensation_mm=design.hole_compensation_mm,
        )

    return base, lid, guard


def _finish_cooling(
    lid: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    cooling: _Cooling,
    openings: list[ConnectorCutoutParameters],
    guard: VentFill | None,
) -> tuple[cq.Workplane, VentReport | None, FanReport | None]:
    """Cut the outlets in the lid, clear of a fan behind it, and report the
    vents and the fan."""

    plan = cooling.fan_plan
    vents_report = None

    if design.vent_area_mm2:
        inlet_mm2 = sum(fill.area_mm2 for fill in cooling.inlets)
        # The outlets are at least as large as the inlets, and of the same
        # pattern, but never louvers: those are for walls.
        lid, outlet = add_lid_outlets(
            lid,
            cavity,
            lid_mm=design.lid_mm,
            kind="slots" if design.vent_pattern == "louvers" else design.vent_pattern,
            target_mm2=max(design.vent_area_mm2, inlet_mm2),
            obstruction=plan.body if plan and plan.position == "lid" else None,
        )
        vents_report = VentReport(
            pattern=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            inlet_mm2=inlet_mm2,
            outlet_mm2=outlet.area_mm2,
            inlet_cells=sum(len(fill.centers) for fill in cooling.inlets),
            outlet_cells=len(outlet.centers),
            inlet=cooling.inlets[0].spec.describe(),
            outlet=outlet.spec.describe(),
        )

    if plan is None or guard is None:
        return lid, vents_report, None

    # An intake draws through the outlets and an exhaust through the inlets,
    # so those and the wall openings are what the fan draws on.
    drawn = 0.0

    if vents_report is not None:
        drawn = (
            vents_report.outlet_mm2
            if plan.direction == "in"
            else vents_report.inlet_mm2
        )

    summary = fan_report(
        plan,
        guard,
        plate_mm=design.lid_mm if plan.position == "lid" else design.wall_mm,
        screw=get_fastener(plan.fan.screw),
        openings=openings,
        vent_free_mm2=drawn,
    )

    return lid, vents_report, summary


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


def _specification(
    assembly: DeviceAssembly,
    design: EnclosureDesign,
    side_clearance: float,
    connector_identifier: str,
) -> EnclosureSpecification:
    return derive_enclosure_specification(
        assembly,
        connector_identifier=connector_identifier,
        side_clearance_mm=side_clearance,
        bottom_clearance_mm=design.bottom_clearance_mm,
        top_clearance_mm=design.top_clearance_mm,
    )


def _automatic_specification(
    assembly: DeviceAssembly,
    *,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    board_identifier: str,
    connector_identifier: str,
    display_identifier: str | None,
    board: BoardSpec,
) -> tuple[EnclosureSpecification, tuple[float, float]]:
    """The smallest cavity whose corner bosses, and lid skirt if it has one,
    clear the hardware, the board's supports, and the cable opening, with
    its X and Y clearances."""

    obstacles = _boss_obstacles(assembly, board_identifier, display_identifier)
    radius = _boss_radius(fastener, design)
    minimum = _specification(
        assembly, design, _minimum_side_clearance(design), connector_identifier
    )
    widenings = sorted(
        ((x, y) for x in _AUTOMATIC_WIDENING_MM for y in _AUTOMATIC_WIDENING_MM),
        key=lambda xy: (
            (minimum.inner_width_mm + 2 * xy[0]) * (minimum.inner_depth_mm + 2 * xy[1]),
            max(xy),
        ),
    )

    for widen_x, widen_y in widenings:
        spec = replace(
            minimum,
            inner_width_mm=minimum.inner_width_mm + 2 * widen_x,
            inner_depth_mm=minimum.inner_depth_mm + 2 * widen_y,
        )
        positions = _corner_boss_positions(spec, fastener, design)

        if _opening_hits_boss(
            _openings(spec, design, assembly, board, board_identifier),
            design,
            fastener,
            positions,
        ):
            continue

        blockers: list[cq.Shape] = [
            cq.Solid.makeCylinder(
                radius, spec.inner_height_mm, pnt=cq.Vector(x, y, spec.bottom_z_mm)
            )
            for x, y in positions
        ]

        if design.skirt_depth_mm is not None:
            blockers.append(
                _all_solids(skirt(_cavity(spec, design), design.skirt_depth_mm))
            )

        if all(
            intersection_volume(blocker, obstacle) <= _INTERFERENCE_TOLERANCE_MM3
            for blocker in blockers
            for obstacle in obstacles
        ):
            return spec, (
                _minimum_side_clearance(design) + widen_x,
                _minimum_side_clearance(design) + widen_y,
            )

    raise ValueError("No side clearance clears the corner bosses; set one")


def _minimum_side_clearance(design: EnclosureDesign) -> float:
    return (
        _HINGE_SIDE_CLEARANCE_MM
        if design.lid_attachment == "hinge"
        else _MINIMUM_SIDE_CLEARANCE_MM
    )


def _cavity(spec: EnclosureSpecification, design: EnclosureDesign) -> Cavity:
    return Cavity(
        center_x_mm=spec.center_x_mm,
        center_y_mm=spec.center_y_mm,
        width_mm=spec.inner_width_mm,
        depth_mm=spec.inner_depth_mm,
        floor_z_mm=spec.bottom_z_mm,
        top_z_mm=spec.bottom_z_mm + spec.inner_height_mm,
        wall_mm=design.wall_mm,
    )


def _boss_obstacles(
    assembly: DeviceAssembly, board_identifier: str, display_identifier: str | None
) -> list[cq.Shape]:
    """Every component, and the zones its supports and retainers use."""

    zones = [board_identifier]

    if display_identifier is not None:
        zones.append(display_identifier)

    return [
        *(
            _all_solids(component.transformed_geometry())
            for component in assembly.components
        ),
        *(
            _grown(_all_solids(assembly.get(name).transformed_geometry()))
            for name in zones
        ),
    ]


def _grown(shape: cq.Shape) -> cq.Shape:
    """A shape's bounding box grown by the support margin all round, where
    supports, cradle clips, and retainer clips reach."""

    bounds = shape.BoundingBox()

    return cq.Solid.makeBox(
        bounds.xlen + 2 * _SUPPORT_MARGIN_MM,
        bounds.ylen + 2 * _SUPPORT_MARGIN_MM,
        bounds.zlen + 2 * _SUPPORT_MARGIN_MM,
        pnt=cq.Vector(
            bounds.xmin - _SUPPORT_MARGIN_MM,
            bounds.ymin - _SUPPORT_MARGIN_MM,
            bounds.zmin - _SUPPORT_MARGIN_MM,
        ),
    )


def _boss_radius(fastener: FastenerSpec, design: EnclosureDesign) -> float:
    return (fastener.heat_set_insert_diameter_mm or 0) / 2 + design.boss_radial_wall_mm


def _add_board_support(
    base: cq.Workplane,
    *,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
    spec: EnclosureSpecification,
    hole_compensation_mm: float = 0.0,
) -> tuple[cq.Workplane, str]:
    """Standoffs under a board's holes, or a cradle for a board without."""

    component = assembly.get(board_identifier)
    placement = component.placement

    # The connector edge the cable opening is cut in is the board's own, so
    # a rotated board would put the opening in the wrong wall.
    if placement.rotation_x_deg or placement.rotation_y_deg or placement.rotation_z_deg:
        raise ValueError("The board must not be rotated; rotate the enclosure")

    bounds = _all_solids(component.transformed_geometry()).BoundingBox()
    floor_top = spec.bottom_z_mm
    support_height = bounds.zmin - floor_top

    if support_height <= 0:
        raise ValueError("The board must sit above the enclosure floor")

    pattern = board_hole_pattern(board)

    if pattern is None:
        cradle = BoardCradleParameters(
            center_x_mm=(bounds.xmin + bounds.xmax) / 2,
            center_y_mm=(bounds.ymin + bounds.ymax) / 2,
            board_width_mm=bounds.xlen,
            board_depth_mm=bounds.ylen,
            board_bottom_z_mm=bounds.zmin,
            board_thickness_mm=bounds.zlen,
            base_z_mm=floor_top - _FLOOR_EMBED_MM,
            connector_edge=spec.cable_edge,
            clearance_mm=_CRADLE_CLEARANCE_MM + hole_compensation_mm / 2,
        )

        return add_board_cradle(base, parameters=cradle), "cradle"

    for x, y in pattern.positions:
        standoff = pattern.standoff(
            x=placement.x_mm + x,
            y=placement.y_mm + y,
            base_height_mm=_FLOOR_EMBED_MM,
            base_z_mm=floor_top - _FLOOR_EMBED_MM,
            standoff_height_mm=support_height,
        )
        base = add_pcb_standoff(
            base,
            parameters=replace(
                standoff,
                hole_diameter_mm=standoff.hole_diameter_mm + hole_compensation_mm,
            ),
        )

    return base, "standoffs"


def _cable_opening(
    spec: EnclosureSpecification, design: EnclosureDesign
) -> ConnectorCutoutParameters:
    """The cable opening, big enough for the plug, through one wall only."""

    width = max(spec.cable_width_mm, design.cable_plug_width_mm)
    height = max(spec.cable_height_mm, design.cable_plug_height_mm)
    center_z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2
    bottom_z = max(center_z - height / 2, spec.bottom_z_mm)
    along_y = spec.cable_edge in ("negative_y", "positive_y")

    return ConnectorCutoutParameters(
        edge=spec.cable_edge,
        center_offset_mm=(spec.center_x_mm if along_y else spec.center_y_mm)
        + spec.cable_center_offset_mm,
        bottom_z_mm=bottom_z,
        width_mm=width,
        height_mm=center_z + height / 2 - bottom_z,
        cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
        width_clearance_mm=_OPENING_CLEARANCE_MM + design.hole_compensation_mm,
    )


def _openings(
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
) -> list[ConnectorCutoutParameters]:
    """The cable opening, the board's declared wall openings, and one for
    each other board part reached through a wall, such as a barrel jack."""

    declared = _declared_openings(design, assembly, board, board_identifier)
    openings = [_cable_opening(spec, design), *declared]
    board_top = _bounds(assembly, board_identifier).zmax

    for component in assembly.components:
        edge = component.metadata.get("access_edge")

        if component.metadata.get("board_identifier") != board_identifier or not edge:
            continue

        bounds = _bounds(assembly, component.identifier)

        # Only the part above the board is reached; its pins below are not.
        if bounds.zmin < board_top - 1e-6:
            continue

        along_y = edge in ("negative_y", "positive_y")
        opening = ConnectorCutoutParameters(
            edge=edge,
            center_offset_mm=(
                (bounds.xmin + bounds.xmax) / 2
                if along_y
                else (bounds.ymin + bounds.ymax) / 2
            ),
            bottom_z_mm=bounds.zmin,
            width_mm=bounds.xlen if along_y else bounds.ylen,
            height_mm=bounds.zlen,
            cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
            width_clearance_mm=_OPENING_CLEARANCE_MM + design.hole_compensation_mm,
        )

        # A declared opening already passes the plug for this part.
        if not any(_overlap(opening, other) for other in declared):
            openings.append(opening)

    return merge_close_openings(openings, design.minimum_opening_web_mm)


def _declared_openings(
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
) -> list[ConnectorCutoutParameters]:
    """The openings the board declares, placed with it and grown for the
    plug that passes each."""

    if not board.wall_openings:
        return []

    bounds = _bounds(assembly, board_identifier)
    center_x = (bounds.xmin + bounds.xmax) / 2
    center_y = (bounds.ymin + bounds.ymax) / 2

    return [
        ConnectorCutoutParameters(
            edge=wall.edge,
            center_offset_mm=wall.center_offset_mm
            + (center_x if wall.edge in ("negative_y", "positive_y") else center_y),
            bottom_z_mm=bounds.zmax
            + wall.bottom_offset_from_board_top_mm
            - _PLUG_MARGIN_MM / 2,
            width_mm=wall.width_mm,
            height_mm=wall.height_mm,
            width_clearance_mm=2 * _PLUG_MARGIN_MM + design.hole_compensation_mm,
            height_clearance_mm=_PLUG_MARGIN_MM,
            cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
        )
        for wall in board.wall_openings
    ]


def _overlap(a: ConnectorCutoutParameters, b: ConnectorCutoutParameters) -> bool:
    """Whether two openings in the same wall overlap."""

    along = (
        abs(a.center_offset_mm - b.center_offset_mm)
        < (a.opening_width_mm + b.opening_width_mm) / 2
    )
    up = (
        a.bottom_z_mm < b.bottom_z_mm + b.opening_height_mm
        and b.bottom_z_mm < a.bottom_z_mm + a.opening_height_mm
    )

    return a.edge == b.edge and along and up


def _bounds(assembly: DeviceAssembly, identifier: str) -> cq.BoundBox:
    return _all_solids(assembly.get(identifier).transformed_geometry()).BoundingBox()


def _opening_hits_boss(
    openings: list[ConnectorCutoutParameters],
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> bool:
    radius = _boss_radius(fastener, design)

    return any(
        abs(
            (x if opening.edge in ("negative_y", "positive_y") else y)
            - opening.center_offset_mm
        )
        < opening.opening_width_mm / 2 + radius
        for opening in openings
        for x, y in positions
    )


def _cut_openings(
    base: cq.Workplane,
    openings: list[ConnectorCutoutParameters],
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> cq.Workplane:
    if _opening_hits_boss(openings, design, fastener, positions):
        raise ValueError(
            "An opening in the wall would cut a corner boss; increase "
            "side_clearance_mm or reduce cable_plug_width_mm"
        )

    for opening in openings:
        base = cut_connector_opening(base, parameters=opening)

    return base


def _clear_parts_under_board(
    base: cq.Workplane,
    spec: EnclosureSpecification,
    assembly: DeviceAssembly,
    board_identifier: str,
) -> cq.Workplane:
    """Notch the board's supports around the parts on its underside, such as
    header pins, so a standoff beside them still reaches the board."""

    board_bottom = _bounds(assembly, board_identifier).zmin

    for component in assembly.components:
        if component.metadata.get("board_identifier") != board_identifier:
            continue

        part = _bounds(assembly, component.identifier)

        if part.zmax > board_bottom + 1e-6:
            continue

        bottom = max(part.zmin - _UNDER_BOARD_CLEARANCE_MM, spec.bottom_z_mm)
        base = base.cut(
            cq.Workplane("XY")
            .box(
                part.xlen + 2 * _UNDER_BOARD_CLEARANCE_MM,
                part.ylen + 2 * _UNDER_BOARD_CLEARANCE_MM,
                board_bottom - bottom,
                centered=False,
            )
            .translate(
                (
                    part.xmin - _UNDER_BOARD_CLEARANCE_MM,
                    part.ymin - _UNDER_BOARD_CLEARANCE_MM,
                    bottom,
                )
            )
        )

    return base


def _compensated_boss(
    boss: InsertBossParameters, hole_compensation_mm: float
) -> InsertBossParameters:
    return replace(
        boss,
        insert_pocket_diameter_mm=boss.insert_pocket_diameter_mm + hole_compensation_mm,
        pilot_hole_diameter_mm=boss.pilot_hole_diameter_mm + hole_compensation_mm,
    )


def _corner_boss_positions(
    spec: EnclosureSpecification,
    fastener: FastenerSpec,
    design: EnclosureDesign,
) -> tuple[tuple[float, float], ...]:
    """Boss centres at each cavity corner, sunk slightly into both walls;
    none for a snap-fit or hinged lid."""

    if design.lid_attachment != "screws":
        return ()

    insert_diameter = fastener.heat_set_insert_diameter_mm

    if insert_diameter is None:
        raise ValueError(
            f"Fastener {fastener.identifier} has no heat-set insert dimensions"
        )

    inset = insert_diameter / 2 + design.boss_radial_wall_mm - _BOSS_WALL_OVERLAP_MM
    half_x = spec.inner_width_mm / 2 - inset
    half_y = spec.inner_depth_mm / 2 - inset

    if half_x <= 0 or half_y <= 0:
        raise ValueError("The cavity is too small for corner insert bosses")

    return tuple(
        (spec.center_x_mm + sx * half_x, spec.center_y_mm + sy * half_y)
        for sx in (-1, 1)
        for sy in (-1, 1)
    )


def _shell(spec: EnclosureSpecification, design: EnclosureDesign) -> cq.Workplane:
    """Floor and walls around the cavity, open at the top."""

    outer = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm + 2 * design.wall_mm,
            spec.inner_depth_mm + 2 * design.wall_mm,
            spec.inner_height_mm + design.floor_mm,
            centered=(True, True, False),
        )
        .translate(
            (spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm - design.floor_mm)
        )
    )
    cavity = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm,
            spec.inner_depth_mm,
            spec.inner_height_mm + 1.0,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm))
    )

    return outer.cut(cavity)


def _corner_fills(
    spec: EnclosureSpecification, positions: tuple[tuple[float, float], ...]
) -> cq.Workplane:
    """Fill each cavity corner behind its boss, where a round boss meeting
    two walls would otherwise leave a narrow void the full cavity height."""

    fills = cq.Workplane("XY")

    for x, y in positions:
        corner_x = spec.center_x_mm + (
            spec.inner_width_mm / 2
            if x > spec.center_x_mm
            else -spec.inner_width_mm / 2
        )
        corner_y = spec.center_y_mm + (
            spec.inner_depth_mm / 2
            if y > spec.center_y_mm
            else -spec.inner_depth_mm / 2
        )
        fills = fills.add(
            cq.Solid.makeBox(
                abs(corner_x - x),
                abs(corner_y - y),
                spec.inner_height_mm + _FLOOR_EMBED_MM,
                pnt=cq.Vector(
                    min(x, corner_x),
                    min(y, corner_y),
                    spec.bottom_z_mm - _FLOOR_EMBED_MM,
                ),
            )
        )

    return fills.combine()


def _cut_lid_vents(
    lid: cq.Workplane,
    assembly: DeviceAssembly,
    board_identifier: str,
    display_identifier: str,
    cavity_top: float,
    design: EnclosureDesign,
) -> cq.Workplane:
    """Slots through the lid across the footprint of each board part that
    draws air from above; refused where the display would cover them."""

    for component in assembly.components:
        metadata = component.metadata

        if metadata.get("board_identifier") != board_identifier or not metadata.get(
            "lid_vent"
        ):
            continue

        vent = _bounds(assembly, component.identifier)

        if display_identifier in assembly.identifiers:
            display = _bounds(assembly, display_identifier)

            if (
                vent.xmin < display.xmax
                and display.xmin < vent.xmax
                and vent.ymin < display.ymax
                and display.ymin < vent.ymax
            ):
                raise ValueError(
                    f"The display covers the lid vent over '{component.identifier}'; "
                    "a fan under it would draw no air"
                )

        count = int((vent.ylen - _LID_VENT_WIDTH_MM) // _LID_VENT_PITCH_MM) + 1
        middle = (vent.ymin + vent.ymax) / 2

        for index in range(count):
            y = middle + (index - (count - 1) / 2) * _LID_VENT_PITCH_MM
            lid = lid.cut(
                box_between(
                    (vent.xmin, vent.xmax),
                    (y - _LID_VENT_WIDTH_MM / 2, y + _LID_VENT_WIDTH_MM / 2),
                    (cavity_top - 1.0, cavity_top + design.lid_mm + 1.0),
                )
            )

    return lid


def _lid(
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    cavity_top: float,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> cq.Workplane:
    """A plate over the walls with a clearance hole above each boss."""

    lid = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm + 2 * design.wall_mm,
            spec.inner_depth_mm + 2 * design.wall_mm,
            design.lid_mm,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, cavity_top))
    )
    if not positions:
        return lid

    holes = (
        cq.Workplane("XY")
        .pushPoints(list(positions))
        .circle((fastener.clearance_hole_mm + design.hole_compensation_mm) / 2)
        .extrude(design.lid_mm + 2.0)
        .translate((0, 0, cavity_top - 1.0))
    )

    return lid.cut(holes)


def _lid_options_in_base(
    base: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
    openings: list[ConnectorCutoutParameters],
) -> cq.Workplane:
    """Cut the snap grooves and the vents into the walls."""

    if design.lid_attachment == "snap":
        base = base.cut(snap_grooves(cavity))

    if design.vent_slots:
        base = base.cut(
            vents(
                cavity,
                slots_per_wall=design.vent_slots,
                blocked_edges=[opening.edge for opening in openings],
                top_z_mm=_vent_top_z(cavity, design),
                corner_keepout_mm=_vent_corner_keepout(fastener, design, positions),
            )
        )

    return base


def _vent_top_z(cavity: Cavity, design: EnclosureDesign) -> float:
    """The highest a wall vent may reach: below the lid's skirt, and below the
    hinge's webs or the slide's thickening where there are any."""

    skirt = design.skirt_depth_mm

    return cavity.top_z_mm - (
        skirt + 1.0
        if skirt is not None
        else VENT_RIM_MM
        + (HINGE_WEB_DEPTH_MM if design.lid_attachment == "hinge" else 0.0)
        + (SLIDE_VENT_DROP_MM if design.lid_attachment == "slide" else 0.0)
    )


def _vent_corner_keepout(
    fastener: FastenerSpec,
    design: EnclosureDesign,
    positions: tuple[tuple[float, float], ...],
) -> float:
    return 2 * _boss_radius(fastener, design) + 1.0 if positions else 3.0


def _lid_options_in_lid(
    lid: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
    openings: list[ConnectorCutoutParameters],
) -> cq.Workplane:
    """Countersink the screw holes and hang the lip or snap skirt."""

    if design.countersunk_screws:
        lid = lid.cut(
            countersinks(
                positions,
                hole_diameter_mm=fastener.clearance_hole_mm
                + design.hole_compensation_mm,
                head_diameter_mm=2 * fastener.nominal_diameter_mm
                + _COUNTERSINK_HEAD_ALLOWANCE_MM,
                lid_top_z_mm=cavity.top_z_mm + design.lid_mm,
                lid_thickness_mm=design.lid_mm,
            )
        )

    depth = design.skirt_depth_mm

    if depth is None:
        return lid

    body = skirt(cavity, depth)

    if design.lid_attachment == "snap":
        body = body.union(snap_ridges(cavity)).cut(relief_slits(cavity))

    return lid.union(
        notch_skirt(
            body,
            boss_positions=positions,
            boss_radius_mm=_boss_radius(fastener, design),
            openings=openings,
            cavity=cavity,
            depth_mm=depth,
        )
    )


def _all_solids(model: cq.Workplane) -> cq.Shape:
    """Every shape on the workplane, not just the first ``val()``."""

    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _require_parts_clear(base: cq.Workplane, lid: cq.Workplane) -> None:
    """Refuse a lid whose retainer would run into the base's features."""

    overlap = intersection_volume(_all_solids(base), _all_solids(lid))

    if overlap > _INTERFERENCE_TOLERANCE_MM3:
        raise ValueError(
            f"The enclosure lid intersects the base by {overlap:.3f} mm3; "
            "increase side_clearance_mm or move the display"
        )


def _require_clear_of_assembly(
    assembly: DeviceAssembly, *, base: cq.Workplane, lid: cq.Workplane
) -> None:
    """Refuse an enclosure whose material intersects any assembly part."""

    parts = {"base": _all_solids(base), "lid": _all_solids(lid)}

    for component in assembly.components:
        geometry = _all_solids(component.transformed_geometry())

        for part_name, part in parts.items():
            overlap = intersection_volume(part, geometry)

            if overlap > _INTERFERENCE_TOLERANCE_MM3:
                raise ValueError(
                    f"The enclosure {part_name} intersects '{component.identifier}' "
                    f"by {overlap:.3f} mm3; increase the design's clearances or "
                    "move the part"
                )

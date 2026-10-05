"""Print records for enclosures: what was built, and how the print fitted.

``enclosure build`` writes an ``enclosure.json`` build record beside the
exported parts: the hardware, the design settings, each part's STL hash, and
the nominal dimensions a trial measures. A trial then records one print of
exactly those parts:

1. :func:`start_enclosure_trial` writes ``trials/trial-NNN/`` with an
   ``observations.json`` and a ``measurements.json`` template listing only
   the checks and dimensions that apply to this enclosure.
2. Fill both in after printing and assembling.
3. :func:`complete_enclosure_trial` validates them and writes
   ``enclosure-trial.json``. A completed trial is never overwritten; record
   another print as the next trial.

A hinged or sliding lid also gets a ``lid.json``: what a hand and a spring scale
find of the pin, the swing, the slide force, and how many openings the lid took.
The engine states no figure for any of these; a trial records them, and a
completed trial keeps them beside what the build designed.

An enclosure with a **stack top** also gets a ``stack_top.json``: the **gap** a feeler gauge
finds under the plate, whether the **screws pass** every hole, the length of screw used, and, of a
bin stacked on it, its **wobble**, the **force** a spring scale reads lifting it off, and a **count of
stackings** with whether anything wore. The engine states no limit for any of them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.enclosure import Enclosure
from zcad_core.features.insert_bosses import InsertBossParameters
from zcad_core.features.lid_hinge import HingeReport
from zcad_core.features.lid_slide import SlideReport
from zcad_core.features.mount_stack import StackTop
from zcad_core.hardware import DisplaySpec, get_fastener
from zcad_core.validation.measurements import PhysicalMeasurement

ENCLOSURE_BUILD_SCHEMA_VERSION = "1.1.0"
ENCLOSURE_TRIAL_SCHEMA_VERSION = "1.1.0"
BUILD_RECORD = "enclosure.json"
TRIAL_RECORD = "enclosure-trial.json"
OBSERVATIONS = "observations.json"
MEASUREMENTS = "measurements.json"
THERMAL = "thermal.json"
LID = "lid.json"
STACK_TOP = "stack_top.json"
# A temperature is only a figure once it has stopped changing.
MINIMUM_SETTLED_MINUTES = 10.0
THERMAL_GUIDANCE = (
    "Run the board under steady load with the lid on. Put a thermocouple or "
    "probe in the middle of the cavity, away from the hottest part, and measure "
    "the room with another a metre from the box. Log the input power with a "
    "USB meter. Wait until the air temperature moves by less than 0.5 C in 10 "
    "minutes, and record that settled value; then say whether the plastic "
    "deformed."
)


class EnclosureCheck(str, Enum):
    """What a printed enclosure must do, each checked by hand."""

    PARTS_PRINTED_CLEANLY = "parts_printed_cleanly"
    INSERTS_INSTALLED = "inserts_installed"
    LID_CLOSES_FLUSH = "lid_closes_flush"
    BOARD_SEATS = "board_seats"
    BOARD_RETAINED = "board_retained"
    CABLE_PLUGS_IN = "cable_plugs_in"
    ACCESS_OPENINGS_CLEAR = "access_openings_clear"
    DISPLAY_ALIGNED = "display_aligned"
    DISPLAY_RETAINED = "display_retained"
    NOTHING_RATTLES = "nothing_rattles"
    HINGE_SWINGS = "hinge_swings_free"
    CATCH_HOLDS = "catch_holds_lid"
    LID_SLIDES = "lid_slides_free"
    DETENT_HOLDS = "detent_holds_lid"
    STACK_TOP_SITS_FLAT = "stack_top_sits_flat"
    STACK_TOP_SCREWS_REACH = "stack_top_screws_reach"
    STACK_TOP_HOLDS = "stack_top_holds"
    STACK_TOP_VENTS_OPEN = "stack_top_vents_open"


CHECK_GUIDANCE = {
    EnclosureCheck.PARTS_PRINTED_CLEANLY: (
        "Base and lid printed without warping, stringing into openings, or "
        "failed features"
    ),
    EnclosureCheck.INSERTS_INSTALLED: (
        "Every heat-set insert went in square and sits flush with its boss"
    ),
    EnclosureCheck.LID_CLOSES_FLUSH: (
        "The lid sits flat on the rim and stays shut: screws draw it down "
        "without cracking a boss, or both snaps click home"
    ),
    EnclosureCheck.BOARD_SEATS: "The board sits level on its standoffs or cradle",
    EnclosureCheck.BOARD_RETAINED: (
        "The board is held without rocking: screwed to its standoffs, or "
        "clipped into its cradle"
    ),
    EnclosureCheck.CABLE_PLUGS_IN: (
        "A real cable plugs fully into the connector through the opening"
    ),
    EnclosureCheck.ACCESS_OPENINGS_CLEAR: (
        "Each other wall opening reaches its part, such as a barrel jack"
    ),
    EnclosureCheck.DISPLAY_ALIGNED: (
        "The whole active area shows through the window; no lid edge covers a pixel"
    ),
    EnclosureCheck.DISPLAY_RETAINED: (
        "The display is held against the lid: screwed to its posts, or "
        "clipped into its retainer"
    ),
    EnclosureCheck.NOTHING_RATTLES: "Nothing moves or rattles when shaken",
    EnclosureCheck.HINGE_SWINGS: (
        "With the pin in, the lid swings from shut to fully open without "
        "catching the base, a part inside, or the display's cable, and turns "
        "on the pin without binding"
    ),
    EnclosureCheck.CATCH_HOLDS: (
        "The catch clicks home as the lid closes, holds it shut when the box "
        "is shaken, and releases when you lift its lip"
    ),
    EnclosureCheck.LID_SLIDES: (
        "The lid pushes in along its grooves and out over the entry wall "
        "without binding or scraping, and stops against the far wall"
    ),
    EnclosureCheck.DETENT_HOLDS: (
        "The detent clicks as the lid reaches home and holds it shut when "
        "the box is shaken"
    ),
    EnclosureCheck.STACK_TOP_SITS_FLAT: (
        "The stack top lies flat on the lid, with no rocking and no gap you can see "
        "at any corner, and a bin stands in its pockets"
    ),
    EnclosureCheck.STACK_TOP_HOLDS: (
        "A bin stands in the plate's pockets and is held: its magnets seat flush and "
        "attract, or its hooks click into the keepers and let go to a pull"
    ),
    EnclosureCheck.STACK_TOP_VENTS_OPEN: (
        "Each window in the plate lies over its outlet with nothing across it, and air "
        "can pass through; the cells with no pocket are left empty"
    ),
    EnclosureCheck.STACK_TOP_SCREWS_REACH: (
        "A screw goes through the plate, the lid and into its insert at every corner, "
        "its head sitting in the recess below the pocket's floor, and draws the plate "
        "down without cracking it"
    ),
}
LID_GUIDANCE = {
    "hinge": (
        "Fit the pin and open and close the lid. Turn the pin by hand, then swing "
        "the lid to its limit and read the angle against a protractor. Pull the "
        "catch's lip with a spring scale at the lip until it lets go. Then open "
        "and close the lid as many times as you will, counting, and say whether "
        "anything cracked, whitened, or wore loose."
    ),
    "slide": (
        "Push the lid open and closed along its grooves with a spring scale on its "
        "end, and write down the force that starts it moving out of the detent. "
        "Then open and close it as many times as you will, counting, and say "
        "whether the grooves, the detent tongues, or the lid wore, cracked, or "
        "whitened."
    ),
}


class EnclosureTrialDisposition(str, Enum):
    """What the print says to do next."""

    PASS = "pass"
    REVISE = "revise"
    FAIL = "fail"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def print_oriented_parts(enclosure: Enclosure) -> dict[str, cq.Shape]:
    """Each part as it goes on the bed: the base on its floor, the lid on
    its outer face, so its screw posts or retainer point up."""

    base = enclosure.base.val()
    lid = enclosure.lid.val()

    if not isinstance(base, cq.Shape) or not isinstance(lid, cq.Shape):
        raise TypeError("Expected a shape for each enclosure part")

    return {"base": base, "lid": lid.rotate((0, 0, 0), (1, 0, 0), 180)}


def applicable_checks(enclosure: Enclosure) -> tuple[EnclosureCheck, ...]:
    """The checks that apply to this enclosure's hardware."""

    skipped = set()

    if len(enclosure.openings) < 2:
        skipped.add(EnclosureCheck.ACCESS_OPENINGS_CLEAR)

    if not enclosure.fastener_positions:
        skipped.add(EnclosureCheck.INSERTS_INSTALLED)

    if enclosure.display_support is None:
        skipped |= {EnclosureCheck.DISPLAY_ALIGNED, EnclosureCheck.DISPLAY_RETAINED}

    if enclosure.hinge is None:
        skipped |= {EnclosureCheck.HINGE_SWINGS, EnclosureCheck.CATCH_HOLDS}

    if enclosure.slide is None:
        skipped |= {EnclosureCheck.LID_SLIDES, EnclosureCheck.DETENT_HOLDS}

    if enclosure.stack_top is None:
        skipped |= {
            EnclosureCheck.STACK_TOP_SITS_FLAT,
            EnclosureCheck.STACK_TOP_SCREWS_REACH,
            EnclosureCheck.STACK_TOP_HOLDS,
            EnclosureCheck.STACK_TOP_VENTS_OPEN,
        }
    else:
        if not top_holds(enclosure.stack_top.stack):
            skipped.add(EnclosureCheck.STACK_TOP_HOLDS)

        if not enclosure.stack_top.stack.get("vent_cells"):
            skipped.add(EnclosureCheck.STACK_TOP_VENTS_OPEN)

    return tuple(check for check in EnclosureCheck if check not in skipped)


def top_holds(stack: dict[str, Any]) -> bool:
    """Whether a stack top holds by anything but the lip: magnets, or latch keepers."""

    return stack.get("holding", "lip") != "lip" or bool(stack.get("latch_sides"))


def stack_top_nominals(top: StackTop | None) -> dict[str, float]:
    """The sizes of a stack top a trial measures with calipers and a depth gauge, in mm."""

    if top is None:
        return {}

    return {
        "stack_top_width_mm": top.size_mm[0],
        "stack_top_depth_mm": top.size_mm[1],
        "stack_top_thickness_mm": top.thickness_mm,
        "stack_top_floor_mm": top.floor_mm,
        "stack_top_recess_depth_mm": top.screw_recess_mm,
        "stack_top_recess_diameter_mm": float(top.stack["recess_diameter_mm"]),
    }


def nominal_measurements(
    enclosure: Enclosure, display: DisplaySpec | None
) -> dict[str, float]:
    """The designed dimensions a trial measures with calipers, in mm."""

    spec = enclosure.specification
    design = enclosure.design
    boss = InsertBossParameters.from_fastener(
        fastener=enclosure.fastener,
        x=0,
        y=0,
        base_height_mm=1.0,
        boss_height_mm=spec.inner_height_mm,
        radial_wall_mm=design.boss_radial_wall_mm,
    )
    cable = enclosure.openings[0] if enclosure.openings else None
    nominals = {
        "base_outer_width_mm": spec.inner_width_mm + 2 * design.wall_mm,
        "base_outer_depth_mm": spec.inner_depth_mm + 2 * design.wall_mm,
        "base_height_mm": spec.inner_height_mm + design.floor_mm,
        "wall_thickness_mm": design.wall_mm,
        "lid_thickness_mm": design.lid_mm,
    }

    if enclosure.fastener_positions:
        nominals["insert_pocket_diameter_mm"] = boss.insert_pocket_diameter_mm
        nominals["lid_hole_diameter_mm"] = enclosure.fastener.clearance_hole_mm

    if cable is not None:
        nominals["cable_opening_width_mm"] = cable.opening_width_mm
        nominals["cable_opening_height_mm"] = cable.opening_height_mm

    if enclosure.hinge is not None:
        # The pin hole as modelled: the pin's clearance hole grown for the printer.
        nominals["hinge_pin_hole_diameter_mm"] = (
            get_fastener(design.hinge_pin).clearance_hole_mm
            + design.hole_compensation_mm
        )

    if enclosure.slide is not None:
        nominals["slide_clearance_per_side_mm"] = enclosure.slide.clearance_mm

    nominals.update(stack_top_nominals(enclosure.stack_top))

    if display is not None:
        clearance = display.recommended_window_clearance_mm
        nominals["display_window_width_mm"] = display.active_width_mm + 2 * clearance
        nominals["display_window_height_mm"] = display.active_height_mm + 2 * clearance

    return {name: round(value, 3) for name, value in nominals.items()}


def lid_summary(enclosure: Enclosure) -> dict[str, Any] | None:
    """What a hinged or sliding lid was designed to do, for a trial to compare
    with: ``None`` for a screwed or snap lid."""

    return lid_summary_of(enclosure.hinge, enclosure.slide)


def lid_summary_of(
    hinge: HingeReport | None, slide: SlideReport | None
) -> dict[str, Any] | None:
    """The same, from a lid's hinge or slide report."""

    if hinge is not None:
        return {
            "kind": "hinge",
            "pin": hinge.pin_description,
            "knuckles": hinge.knuckles,
            "swing_degrees": hinge.swing_degrees,
            "catch_strain_percent": round(100 * hinge.catch.strain, 2),
        }

    if slide is not None:
        return {
            "kind": "slide",
            "entry_edge": slide.entry_edge,
            "clearance_per_side_mm": slide.clearance_mm,
            "travel_mm": round(slide.travel_mm, 1),
            "detent_strain_percent": round(100 * slide.detent.strain, 2),
        }

    return None


def write_build_record(
    output_directory: Path,
    *,
    enclosure: Enclosure,
    design_name: str,
    board_identifier: str,
    display: DisplaySpec | None,
    part_stls: dict[str, Path],
    printer_profile_id: str,
    assembly_settings: dict[str, float | bool | None] | None = None,
    revision_of: dict[str, Any] | None = None,
    compensation_profile: dict[str, Any] | None = None,
    thermal_profile: dict[str, Any] | None = None,
    board_source: dict[str, Any] | None = None,
) -> Path:
    """Write ``enclosure.json``; refuses to replace one.

    ``assembly_settings`` records how the hardware was placed (display
    height, clearances, and any fitted cooler), so a revision can rebuild the
    same assembly; ``revision_of`` records the build and trial a revision
    came from.
    """

    path = output_directory / BUILD_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    record = {
        "schema_version": ENCLOSURE_BUILD_SCHEMA_VERSION,
        "design_name": design_name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "board": board_identifier,
        "board_source": board_source,
        "display": display.identifier if display is not None else None,
        "design": asdict(enclosure.design),
        "stack": enclosure.mount.stack if enclosure.mount else None,
        "stack_top": enclosure.stack_top.stack if enclosure.stack_top else None,
        "assembly": assembly_settings or {},
        "revision_of": revision_of,
        "compensation_profile": compensation_profile,
        "thermal_profile": thermal_profile,
        "side_clearance_mm": list(enclosure.side_clearance_mm),
        "board_support": enclosure.board_support,
        "display_support": enclosure.display_support,
        "lid": lid_summary(enclosure),
        "thermal": enclosure.thermal.to_dict() if enclosure.thermal else None,
        "vents": enclosure.vents.to_dict() if enclosure.vents else None,
        "fan": enclosure.fan.to_dict() if enclosure.fan else None,
        "printer_profile_id": printer_profile_id,
        "parts": {
            name: {"stl_path": str(stl), "stl_sha256": sha256(stl)}
            for name, stl in part_stls.items()
        },
        "checks": [check.value for check in applicable_checks(enclosure)],
        "nominal_measurements_mm": nominal_measurements(enclosure, display),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def start_enclosure_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation and measurement templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations = {
        check: {
            "result": "pending",
            "guidance": CHECK_GUIDANCE[EnclosureCheck(check)],
            "notes": "",
        }
        for check in build["checks"]
    }
    measurements = {
        name: {"nominal_mm": nominal, "value_mm": None, "notes": ""}
        for name, nominal in build["nominal_measurements_mm"].items()
    }
    (trial / THERMAL).write_text(
        json.dumps(_thermal_template(build), indent=2) + "\n", encoding="utf-8"
    )

    if build.get("lid"):
        (trial / LID).write_text(
            json.dumps(_lid_template(build["lid"]), indent=2) + "\n", encoding="utf-8"
        )

    if build.get("stack_top"):
        (trial / STACK_TOP).write_text(
            json.dumps(_stack_top_template(build["stack_top"]), indent=2) + "\n",
            encoding="utf-8",
        )

    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )

    return trial


STACK_TOP_GUIDANCE = (
    "gap_under_plate_mm: the gap a feeler gauge finds between the plate and the lid at the worst "
    "corner with the screws in; screws_pass_all_holes: a screw goes through plate, lid and "
    "insert at every corner; screw_length_mm: the length you used; bin_wobble_mm: the gap a "
    "feeler gauge finds at a corner of a bin stacked on it when the bin is pressed down at the "
    "opposite side; separation_force_n: the highest force a spring scale reads lifting that bin "
    "off; stackings_counted: how many times it was stacked and lifted off, and anything_wore "
    "whether the plate, the lid or a boss wore, cracked or went slack"
)


def _stack_top_template(stack: dict[str, Any]) -> dict[str, Any]:
    """The stack top template: what the build designed, and blanks for a feeler gauge, a spring
    scale and a count. Leave a reading blank when it was not taken."""

    return {
        "not_a_limit": (
            "The engine states no limit for any reading here, and no load rating: it records "
            "what was measured and what was seen"
        ),
        "guidance": STACK_TOP_GUIDANCE,
        "designed": {
            "cells": stack["cells"],
            "floor_mm": stack["floor_mm"],
            "thickness_mm": stack["thickness_mm"],
            "recommended_screw_mm": stack["recommended_screw_mm"],
            "screw_reach_mm": stack["screw_reach_mm"],
            "holding": stack.get("holding", "lip"),
            "magnet": stack.get("magnet", ""),
            "latch_sides": stack.get("latch_sides", []),
            "latch_engagement_mm": stack.get("latch_engagement_mm"),
            "vent_cells": stack.get("vent_cells", []),
            "vent_windows_mm": stack.get("vent_windows_mm", []),
        },
        "gap_under_plate_mm": None,
        "screws_pass_all_holes": None,
        "screw_length_mm": None,
        "bin_wobble_mm": None,
        "separation_force_n": None,
        "stackings_counted": None,
        "anything_wore": None,
        "notes": "",
    }


def _lid_template(lid: dict[str, Any]) -> dict[str, Any]:
    """The lid template: what the build designed, and blanks for what a
    protractor, a spring scale, and a count of openings say. Leave it blank for
    a trial that does not try the lid."""

    common = {"openings_counted": None, "damage_observed": None, "notes": ""}

    if lid["kind"] == "hinge":
        return {
            "guidance": LID_GUIDANCE["hinge"],
            "designed": {"swing_degrees": lid["swing_degrees"], "pin": lid["pin"]},
            "pin_turns_freely": None,
            "swing_degrees_reached": None,
            "catch_release_force_n": None,
            **common,
        }

    return {
        "guidance": LID_GUIDANCE["slide"],
        "designed": {
            "clearance_per_side_mm": lid["clearance_per_side_mm"],
            "travel_mm": lid["travel_mm"],
        },
        "slide_force_n": None,
        **common,
    }


def _thermal_template(build: dict[str, Any]) -> dict[str, Any]:
    """The thermal template: what the build predicted, and blanks for what a
    thermocouple and a power meter say. Leave it blank for a fit-only trial."""

    estimate = build.get("thermal") or {}

    return {
        "guidance": THERMAL_GUIDANCE,
        "estimate": {
            key: estimate.get(key)
            for key in (
                "typical_w",
                "peak_w",
                "rise_peak_c",
                "temperature_peak_c",
                "surface_m2",
                "coefficient_w_m2k",
                "coefficient_source",
                "closed",
                "complete",
            )
        },
        "ambient_c": None,
        "internal_air_c": None,
        "power_w": None,
        "settled_minutes": None,
        "deformation_observed": None,
        "sensor": "",
        "notes": "",
    }


def _number(entry: dict[str, Any], name: str) -> float:
    value = entry.get(name)

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"thermal.json: {name} must be a number, not {value!r}")

    return float(value)


def _thermal(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's thermal record, validated and compared with the estimate;
    ``None`` when no temperature was recorded."""

    path = trial / THERMAL

    if not path.is_file():
        return None

    entry = _read(path)

    if entry.get("internal_air_c") is None:
        return None

    estimate = build.get("thermal")

    if not estimate:
        raise ValueError(
            "The build record has no thermal estimate, so a temperature has "
            "nothing to be compared with; rebuild with this version"
        )

    ambient = _number(entry, "ambient_c")
    internal = _number(entry, "internal_air_c")
    power = _number(entry, "power_w")
    minutes = _number(entry, "settled_minutes")
    deformed = entry.get("deformation_observed")

    if not isinstance(deformed, bool):
        raise TypeError("thermal.json: deformation_observed must be true or false")

    if power <= 0:
        raise ValueError("thermal.json: power_w must be greater than zero")

    if minutes < MINIMUM_SETTLED_MINUTES:
        raise ValueError(
            f"thermal.json: a settled reading is held for at least "
            f"{MINIMUM_SETTLED_MINUTES:g} minutes, not {minutes:g}"
        )

    rise = internal - ambient

    if rise <= 0:
        raise ValueError(
            "thermal.json: the air inside is no warmer than the room, so there "
            "is no rise to measure; check the power and the sensor"
        )

    surface = float(estimate["surface_m2"])
    coefficient = float(estimate["coefficient_w_m2k"])
    conductance = power / rise
    estimated_rise = power / (coefficient * surface)

    return {
        "ambient_c": ambient,
        "internal_air_c": internal,
        "power_w": power,
        "settled_minutes": minutes,
        "deformation_observed": deformed,
        "sensor": entry.get("sensor", ""),
        "notes": entry.get("notes", ""),
        "rise_c": round(rise, 2),
        "surface_m2": surface,
        "conductance_w_k": round(conductance, 4),
        "h_effective_w_m2k": round(conductance / surface, 3),
        "estimated_rise_c_at_measured_power": round(estimated_rise, 2),
        # Above 1, the box ran hotter than the estimate said it would.
        "estimate_error_ratio": round(rise / estimated_rise, 2),
        "closed": bool(estimate.get("closed")),
        "configuration": {
            "vent_slots": build["design"].get("vent_slots", 0),
            "vents": build.get("vents"),
            "fan": build.get("fan"),
        },
    }


def _positive(entry: dict[str, Any], name: str, where: str) -> float | None:
    value = entry.get(name)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{where}: {name} must be a number above zero, not {value!r}")

    return float(value)


def _lid(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's lid record, validated and set beside what was designed;
    ``None`` when the lid was not tried."""

    path = trial / LID

    if not path.is_file():
        return None

    entry = _read(path)
    designed = build.get("lid")
    where = "lid.json"

    if not designed:
        raise ValueError(
            "The build record has no hinged or sliding lid, so a lid trial has "
            "nothing to be compared with"
        )

    names = (
        ("swing_degrees_reached", "catch_release_force_n", "pin_turns_freely")
        if designed["kind"] == "hinge"
        else ("slide_force_n",)
    )
    measured = {name: entry.get(name) for name in (*names, "openings_counted")}

    if all(value is None for value in measured.values()):
        return None

    record: dict[str, Any] = {"kind": designed["kind"], "designed": designed}

    if designed["kind"] == "hinge":
        turns = entry.get("pin_turns_freely")

        if turns is not None and not isinstance(turns, bool):
            raise TypeError(f"{where}: pin_turns_freely must be true or false")

        reached = _positive(entry, "swing_degrees_reached", where)

        if reached is not None and reached > 180.0:
            raise ValueError(f"{where}: swing_degrees_reached cannot exceed 180")

        record |= {
            "pin_turns_freely": turns,
            "swing_degrees_reached": reached,
            "catch_release_force_n": _positive(entry, "catch_release_force_n", where),
            # Above zero, the lid opened less than designed.
            "swing_shortfall_degrees": (
                None
                if reached is None
                else round(designed["swing_degrees"] - reached, 1)
            ),
        }
    else:
        record["slide_force_n"] = _positive(entry, "slide_force_n", where)

    record |= _wear(entry, where)
    record["notes"] = entry.get("notes", "")

    return record


def _stack_top(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's stack top readings, validated and set beside what was designed; ``None``
    when none was taken."""

    stack = build.get("stack_top")
    path = trial / STACK_TOP
    entry = _read(path) if path.is_file() else {}

    if not stack:
        if entry:
            raise ValueError(
                "stack_top.json: this enclosure was built with no stack top"
            )

        return None

    where = STACK_TOP
    gap = _non_negative(entry, "gap_under_plate_mm", where)
    wobble = _non_negative(entry, "bin_wobble_mm", where)
    force = _positive(entry, "separation_force_n", where)
    length = _positive(entry, "screw_length_mm", where)
    passes = entry.get("screws_pass_all_holes")
    count, wore = entry.get("stackings_counted"), entry.get("anything_wore")

    if passes is not None and not isinstance(passes, bool):
        raise TypeError(f"{where}: screws_pass_all_holes must be true or false")

    if count is None:
        if wore is not None:
            raise ValueError(f"{where}: anything_wore needs stackings_counted")
    elif isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: stackings_counted must be a whole number from 1")
    elif not isinstance(wore, bool):
        raise TypeError(f"{where}: anything_wore must be true or false")

    readings = (gap, wobble, force, length, passes, count)

    if all(value is None for value in readings):
        return None

    return {
        "gap_under_plate_mm": gap,
        "screws_pass_all_holes": passes,
        "screw_length_mm": length,
        "recommended_screw_mm": stack["recommended_screw_mm"],
        "bin_wobble_mm": wobble,
        "separation_force_n": force,
        "stackings_counted": count,
        "anything_wore": wore,
        "designed": {
            "cells": stack["cells"],
            "floor_mm": stack["floor_mm"],
            "thickness_mm": stack["thickness_mm"],
            "screw_reach_mm": stack["screw_reach_mm"],
            "holding": stack.get("holding", "lip"),
            "magnet": stack.get("magnet", ""),
            "latch_sides": stack.get("latch_sides", []),
            "latch_engagement_mm": stack.get("latch_engagement_mm"),
        },
        "notes": entry.get("notes", ""),
        "not_a_limit": (
            "The engine states no limit for any reading here, and no load rating"
        ),
    }


def _non_negative(entry: dict[str, Any], name: str, where: str) -> float | None:
    value = entry.get(name)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"{where}: {name} must be a number from zero, not {value!r}")

    return float(value)


def _wear(entry: dict[str, Any], where: str) -> dict[str, Any]:
    """The count of openings and whether the lid was damaged by them. Damage
    needs a count: a lid is only as worn as the number of times it was worked."""

    count = entry.get("openings_counted")
    damage = entry.get("damage_observed")

    if count is None:
        if damage is not None:
            raise ValueError(f"{where}: damage_observed needs openings_counted")

        return {"openings_counted": None, "damage_observed": None}

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: openings_counted must be a whole number from 1")

    if not isinstance(damage, bool):
        raise TypeError(f"{where}: damage_observed must be true or false")

    return {"openings_counted": count, "damage_observed": damage}


def _observations(trial: Path, required: list[str]) -> list[dict[str, Any]]:
    payload = _read(trial / OBSERVATIONS)
    missing = sorted(set(required) - set(payload))
    unknown = sorted(set(payload) - set(required))

    if missing or unknown:
        raise ValueError(
            f"Observations must cover exactly this enclosure's checks; "
            f"missing: {missing}, unexpected: {unknown}"
        )

    observations = []

    for check in required:
        entry = payload[check]
        result = entry.get("result")

        if result not in ("pass", "fail"):
            raise ValueError(
                f"Observation {check} must be pass or fail, not {result!r}"
            )

        observations.append(
            {
                "check": check,
                "passed": result == "pass",
                "notes": entry.get("notes", ""),
            }
        )

    return observations


def _measurements(trial: Path) -> list[PhysicalMeasurement]:
    payload = _read(trial / MEASUREMENTS)

    return [
        PhysicalMeasurement(
            name=name,
            value_mm=float(entry["value_mm"]),
            nominal_mm=entry.get("nominal_mm"),
            notes=entry.get("notes", ""),
        )
        for name, entry in payload.items()
        if entry.get("value_mm") is not None
    ]


def _printed_slice(build_directory: Path) -> dict[str, Any] | None:
    """The slice a trial was printed from, checked: its G-code and the
    print-oriented copies the slicer was given, each still the file the slice
    summary records. The build's own STLs are not what was printed (the lid is
    printed turned), so this is what ties the trial to the plate. None for a
    build that was never sliced."""

    summary_path = build_directory / "slice" / "slice-summary.json"

    if not summary_path.is_file():
        return None

    summary = _read(summary_path)
    files = {
        "plate_1.gcode": (
            summary_path.parent / "plate_1.gcode",
            summary.get("gcode_sha256"),
        )
    }

    for model in summary.get("models") or ():
        path = Path(str(model["path"]))
        files[f"print/{path.name}"] = (path, model.get("sha256"))

    changed = [
        name
        for name, (path, digest) in files.items()
        if not path.is_file() or sha256(path) != digest
    ]

    if changed:
        raise ValueError(
            "The slice this trial was printed from no longer matches its summary: "
            f"{changed}; slice again and print that"
        )

    return {
        "slice_summary_sha256": sha256(summary_path),
        "gcode_sha256": summary.get("gcode_sha256"),
        "models": [
            {"path": str(model["path"]), "sha256": model.get("sha256")}
            for model in summary.get("models") or ()
        ],
    }


def complete_enclosure_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in trial and write its record."""

    record_path = trial / TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as "
            "the next trial"
        )

    build_path = trial.parent.parent / BUILD_RECORD
    build = _read(build_path)
    changed = [
        name
        for name, part in build["parts"].items()
        if not Path(part["stl_path"]).is_file()
        or sha256(Path(part["stl_path"])) != part["stl_sha256"]
    ]

    if changed:
        raise ValueError(
            f"The printed parts no longer match the build record: {changed}"
        )

    printed_from = _printed_slice(trial.parent.parent)
    observations = _observations(trial, build["checks"])
    measurements = _measurements(trial)
    thermal = _thermal(trial, build)
    lid = _lid(trial, build)
    stack_top = _stack_top(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and thermal is None
        and lid is None
        and stack_top is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement, a "
            "recorded temperature, a lid reading, or a stack top reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": ENCLOSURE_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "printed_from": printed_from,
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "disposition": disposition.value,
        "passed": disposition is EnclosureTrialDisposition.PASS,
        "failed_checks": failed,
        "observations": observations,
        "measurements": [
            {**asdict(measurement), "deviation_mm": measurement.deviation_mm}
            for measurement in measurements
        ],
        "thermal": thermal,
        "lid": lid,
        "stack_top": stack_top,
        "notes": notes,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path

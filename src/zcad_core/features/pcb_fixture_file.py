"""A PCB test fixture described in a file, and the board it holds.

The file names a board file (by path and hash) and says which test points to
probe, with what pin, how far the pins are pressed, how the board is located,
and how the plate closes. It never repeats the board's data: outline, holes and
test points come from the board file, so there is one place to correct them.

The engine does not trust it. :func:`check_fixture_data` refuses what cannot be
right, and :func:`check_fixture_file` also reads the board and refuses a fixture
that cannot reach its points: a pad the pin's tip is wider than, a pin pitch the
printer cannot wall, locating by holes the board does not have.

The pin is either catalogued, or the user's own figures with where they came from.
A catalogued pin's source says which figures no read datasheet supports.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.features.pcb_fixture_closure import (
    DEFAULT_SCREW,
    ClosurePlan,
    plan_closure,
)
from zcad_core.features.pcb_fixture_plan import (
    DEFAULT_WALL_MM,
    FixturePlan,
    bore_diameter,
    plan_fixture,
)
from zcad_core.hardware import PogoSource, PogoSpec, get_pogo_pin, load_board
from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.fasteners import list_fasteners

FIXTURE_SCHEMA_VERSION = "1.0.0"
# Only the board's top side is probed in this version.
SIDES = ("top",)
LOCATING = ("outline", "holes")
CLOSURES = ("screws", "hinge")
WORKING_TRAVEL_RANGE_MM = (0.1, 20.0)
# A tip wider than this share of its pad leaves little slack for misalignment.
TIGHT_TIP_SHARE = 0.5
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "board",
        "side",
        "points",
        "pin",
        "working_travel_mm",
        "locating",
        "closure",
        "screw",
        "hinge",
        "nest",
        "plate",
        "needs_review",
    }
)
_PIN_FIGURES = (
    "barrel_diameter_mm",
    "tip_diameter_mm",
    "free_length_mm",
    "travel_mm",
    "force_n",
    "force_at_travel_mm",
)


@dataclass(frozen=True)
class FixtureCheck:
    """What a check found: errors make a fixture unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # What reading the board and the pin found, when they could be read.
    summary: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PcbFixtureSpec:
    """A fixture as its file describes it."""

    identifier: str
    name: str
    board_path: Path
    board_sha256: str
    side: str
    # The test points to probe, or all of the side's when None.
    points: tuple[str, ...] | None
    pin: PogoSpec
    working_travel_mm: float
    locating: str
    closure: str
    # The screw the closure uses, and, if the user gives one, its tensile limit.
    screw_size: str
    screw_limit_n: float | None
    screw_source: str
    # The pin a hinged closure turns on, and, if the user gives one, the load
    # its catch is given to hold.
    hinge_pin: str
    catch_limit_n: float | None
    catch_source: str
    # The nest's wall, and the plate's thickness (None: sized to the pin).
    nest_wall_mm: float
    plate_thickness_mm: float | None
    source: str
    notes: str
    file_path: Path
    file_sha256: str


def _check_pin(data: Mapping[str, Any], findings: Findings) -> None:
    before = len(findings.errors)
    pin = section(data, "pin", findings)

    if pin is None:
        return

    if pin.get("catalog") is not None:
        try:
            get_pogo_pin(str(pin["catalog"]))
        except ValueError as error:
            findings.errors.append(str(error))

        return

    for name in ("maker", "model"):
        value = pin.get(name)

        if not isinstance(value, str) or not value.strip():
            findings.errors.append(f"pin.{name} must say which pin it is")

    for name in _PIN_FIGURES:
        number(pin, name, "pin", findings, low=0.01, high=500.0)

    source = pin.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "pin.source must say where the figures came from: they are your own "
            "until a maker's datasheet has been read"
        )

    if len(findings.errors) == before:
        _validate_user_pin(pin, findings)


def _validate_user_pin(pin: Mapping[str, Any], findings: Findings) -> None:
    try:
        _user_pin(pin).validate()
    except ValueError as error:
        findings.errors.append(f"pin: {error}")


def _catch_limit(data: Mapping[str, Any]) -> float | None:
    value = (data.get("hinge") or {}).get("catch_load_limit_n")

    return float(value) if value is not None else None


def closure_for(
    spec: PcbFixtureSpec,
    board: BoardFileSpec,
    plan: FixturePlan,
    profile: Mapping[str, Any],
) -> ClosurePlan:
    """The closure a fixture file asks for, planned against its layout."""

    return plan_closure(
        board=board,
        plan=plan,
        kind=spec.closure,
        screw=spec.screw_size,
        limit_n=spec.screw_limit_n,
        limit_source=spec.screw_source,
        profile=profile,
        hinge_pin=spec.hinge_pin,
        catch_limit_n=spec.catch_limit_n,
        catch_limit_source=spec.catch_source,
    )


def _screw_limit(data: Mapping[str, Any]) -> float | None:
    value = (data.get("screw") or {}).get("tensile_limit_n")

    return float(value) if value is not None else None


def _user_pin(pin: Mapping[str, Any]) -> PogoSpec:
    return PogoSpec(
        identifier="USER-"
        + re.sub(r"[^A-Za-z0-9]+", "-", str(pin["model"])).strip("-"),
        maker=str(pin["maker"]),
        model=str(pin["model"]),
        barrel_diameter_mm=float(pin["barrel_diameter_mm"]),
        tip_diameter_mm=float(pin["tip_diameter_mm"]),
        free_length_mm=float(pin["free_length_mm"]),
        travel_mm=float(pin["travel_mm"]),
        force_n=float(pin["force_n"]),
        force_at_travel_mm=float(pin["force_at_travel_mm"]),
        source=PogoSource(
            kind="user",
            title="the fixture file",
            url="",
            detail=str(pin["source"]),
            read=False,
        ),
    )


def _check_board_section(data: Mapping[str, Any], findings: Findings) -> None:
    board = section(data, "board", findings)

    if board is None:
        return

    file = board.get("file")

    if not isinstance(file, str) or not file.strip():
        findings.errors.append("board.file must be the path of a board file")

    digest = board.get("sha256")

    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        findings.errors.append(
            "board.sha256 must be the board file's SHA-256 as 64 lower-case hex digits"
        )


def _check_choices(data: Mapping[str, Any], findings: Findings) -> None:
    side = data.get("side", "top")

    if side not in SIDES:
        findings.errors.append(
            f"side must be one of {SIDES}, not {side!r}; probing the bottom side "
            "comes in a later release"
        )

    if data.get("locating", "outline") not in LOCATING:
        findings.errors.append(f"locating must be one of {LOCATING}")

    if data.get("closure", "screws") not in CLOSURES:
        findings.errors.append(f"closure must be one of {CLOSURES}")

    points = data.get("points")

    if points is not None and (
        not isinstance(points, Sequence)
        or isinstance(points, str)
        or not points
        or not all(isinstance(p, str) for p in points)
    ):
        findings.errors.append(
            "points must be a list of test point names, or left out for all of them"
        )
    elif points is not None and len(set(points)) != len(points):
        findings.errors.append("points lists a test point twice")


def _check_screw(data: Mapping[str, Any], findings: Findings) -> None:
    screw = section(data, "screw", findings, required=False)

    if screw is None:
        return

    size = screw.get("size", DEFAULT_SCREW)

    if size not in list_fasteners():
        findings.errors.append(f"screw.size must be one of {list_fasteners()}")

    limit = number(
        screw, "tensile_limit_n", "screw", findings, low=1.0, high=1e5, required=False
    )
    source = screw.get("source")

    if limit is not None and (not isinstance(source, str) or not source.strip()):
        findings.errors.append(
            "screw.source must say where the tensile limit came from: it is your "
            "own until a maker's datasheet has been read"
        )


def _check_hinge(data: Mapping[str, Any], findings: Findings) -> None:
    hinge = section(data, "hinge", findings, required=False)

    if hinge is None:
        return

    pin = hinge.get("pin", DEFAULT_SCREW)

    if pin not in list_fasteners():
        findings.errors.append(f"hinge.pin must be one of {list_fasteners()}")

    limit = number(
        hinge,
        "catch_load_limit_n",
        "hinge",
        findings,
        low=0.1,
        high=1e4,
        required=False,
    )
    source = hinge.get("source")

    if limit is not None and (not isinstance(source, str) or not source.strip()):
        findings.errors.append(
            "hinge.source must say where the catch's load limit came from: it is "
            "your own until it has been measured"
        )


def check_fixture_data(data: Any) -> FixtureCheck:
    """Check a fixture file's contents without reading the board."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return FixtureCheck(("A fixture file must hold a JSON object",), ())

    if data.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {FIXTURE_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.errors.append(f"Unknown field(s): {', '.join(unknown)}")

    if data.get("units", "mm") != "mm":
        findings.errors.append("units must be 'mm'; every number is millimetres")

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        findings.errors.append("identifier must be a name of letters, digits, _ . -")

    if data.get("needs_review"):
        findings.errors.append(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    _check_board_section(data, findings)
    _check_choices(data, findings)
    _check_pin(data, findings)
    _check_screw(data, findings)
    _check_hinge(data, findings)
    nest = section(data, "nest", findings, required=False)

    if nest is not None:
        number(nest, "wall_mm", "nest", findings, low=0.8, high=20.0, required=False)

    plate = section(data, "plate", findings, required=False)

    if plate is not None:
        number(
            plate, "thickness_mm", "plate", findings, low=1.2, high=40.0, required=False
        )

    number(
        data,
        "working_travel_mm",
        "",
        findings,
        low=WORKING_TRAVEL_RANGE_MM[0],
        high=WORKING_TRAVEL_RANGE_MM[1],
    )

    if not data.get("source"):
        findings.warnings.append(
            "No source is stated: say what this fixture is for and which board it tests"
        )

    return FixtureCheck(tuple(findings.errors), tuple(findings.warnings))


def read_fixture_file(path: Path) -> tuple[Any, str]:
    """A fixture file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def fixture_from_data(
    data: Mapping[str, Any], path: Path, sha256: str
) -> PcbFixtureSpec:
    """Build a fixture from checked contents; refuses a file with errors."""

    report = check_fixture_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid fixture file:\n- " + "\n- ".join(report.errors)
        )

    board = data["board"]
    board_path = Path(board["file"])
    pin = data["pin"]
    points = data.get("points")

    return PcbFixtureSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        board_path=(
            board_path
            if board_path.is_absolute()
            else (path.parent / board_path).resolve()
        ),
        board_sha256=str(board["sha256"]),
        side=str(data.get("side", "top")),
        points=tuple(points) if points is not None else None,
        pin=get_pogo_pin(str(pin["catalog"])) if "catalog" in pin else _user_pin(pin),
        working_travel_mm=float(data["working_travel_mm"]),
        locating=str(data.get("locating", "outline")),
        closure=str(data.get("closure", "screws")),
        screw_size=str((data.get("screw") or {}).get("size", DEFAULT_SCREW)),
        screw_limit_n=_screw_limit(data),
        screw_source=str((data.get("screw") or {}).get("source", "")),
        hinge_pin=str((data.get("hinge") or {}).get("pin", DEFAULT_SCREW)),
        catch_limit_n=_catch_limit(data),
        catch_source=str((data.get("hinge") or {}).get("source", "")),
        nest_wall_mm=float((data.get("nest") or {}).get("wall_mm", DEFAULT_WALL_MM)),
        plate_thickness_mm=(
            float(data["plate"]["thickness_mm"])
            if isinstance(data.get("plate"), Mapping)
            and data["plate"].get("thickness_mm") is not None
            else None
        ),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
    )


def load_fixture(path: Path) -> PcbFixtureSpec:
    """Load and check a fixture file, refusing one that cannot be right."""

    data, sha256 = read_fixture_file(path)

    return fixture_from_data(data, path, sha256)


def load_fixture_board(spec: PcbFixtureSpec) -> BoardFileSpec:
    """The board a fixture holds, refused if its file is missing, has changed
    since the fixture file was written, or is itself not a valid board file."""

    if not spec.board_path.is_file():
        raise ValueError(f"The board file is missing: {spec.board_path}")

    digest = hashlib.sha256(spec.board_path.read_bytes()).hexdigest()

    if digest != spec.board_sha256:
        raise ValueError(
            f"{spec.board_path.name} has changed since the fixture file was "
            f"written: its SHA-256 is {digest}, the file says {spec.board_sha256}"
        )

    return load_board(spec.board_path)


def _hole_count(board: BoardFileSpec) -> int:
    if board.mounting_hole_diameter_mm is None:
        return 0

    if board.mounting_hole_positions_mm is not None:
        return len(board.mounting_hole_positions_mm)

    return 4


def check_fixture_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> FixtureCheck:
    """Check a fixture file, the board it names, and whether the pins can reach
    the points. Given a printer profile, the pins' pitch is checked against its
    minimum wall."""

    data, sha256 = read_fixture_file(path)
    report = check_fixture_data(data)

    if not report.valid:
        return report

    spec = fixture_from_data(data, path, sha256)

    try:
        board = load_fixture_board(spec)
    except ValueError as error:
        return FixtureCheck((*report.errors, str(error)), report.warnings)

    errors: list[str] = []
    warnings = list(report.warnings)
    probed = _probed_points(spec, board, errors)
    summary: dict[str, Any] = {
        "board": {
            "identifier": board.identifier,
            "path": str(spec.board_path),
            "sha256": spec.board_sha256,
            "size_mm": [board.board_width_mm, board.board_length_mm],
            "outline": "rectangle"
            if board.outline_points_mm is None
            else f"polygon, {len(board.outline_points_mm)} points",
            "mounting_holes": _hole_count(board),
        },
        "pin": _pin_summary(spec.pin),
        "side": spec.side,
        "working_travel_mm": spec.working_travel_mm,
        "locating": spec.locating,
        "closure": spec.closure,
        "points": [],
    }

    _check_pin_against_points(spec, probed, errors, warnings, summary)

    if spec.locating == "holes" and _hole_count(board) < 2:
        errors.append(
            f"Locating by the mounting holes needs at least two, and "
            f"{board.identifier} has {_hole_count(board)}: locate by the outline"
        )

    if spec.working_travel_mm > spec.pin.travel_mm:
        errors.append(
            f"working_travel_mm is {spec.working_travel_mm:g}, more than the pin's "
            f"{spec.pin.travel_mm:g} mm of travel"
        )

    _check_pitch(spec, probed, profile, errors, warnings, summary)

    if profile is not None and probed:
        plan = plan_fixture(
            board=board,
            points=probed,
            pin=spec.pin,
            working_travel_mm=spec.working_travel_mm,
            locating=spec.locating,
            profile=profile,
            nest_wall_mm=spec.nest_wall_mm,
            plate_thickness_mm=spec.plate_thickness_mm,
        )
        errors.extend(plan.errors)
        warnings.extend(plan.warnings)
        summary["plan"] = plan.to_dict()

        if not plan.errors:
            closure = closure_for(spec, board, plan, profile)
            errors.extend(closure.errors)
            warnings.extend(closure.warnings)
            summary["closure_plan"] = closure.to_dict()

    return FixtureCheck((*report.errors, *errors), tuple(warnings), summary)


def _probed_points(
    spec: PcbFixtureSpec, board: BoardFileSpec, errors: list[str]
) -> list[Any]:
    """The test points to probe: those named, or all of the side's."""

    on_side = [p for p in board.test_points if p.side == spec.side]

    if not on_side:
        errors.append(
            f"{board.identifier} has no test points on its {spec.side} side: list "
            "them under test_points in the board file"
        )

        return []

    if spec.points is None:
        return on_side

    by_name = {p.identifier: p for p in on_side}
    missing = [name for name in spec.points if name not in by_name]

    if missing:
        errors.append(
            f"The board has no {spec.side}-side test point named "
            f"{', '.join(missing)}; it has {', '.join(sorted(by_name))}"
        )

    return [by_name[name] for name in spec.points if name in by_name]


def probed_points(spec: PcbFixtureSpec, board: BoardFileSpec) -> list[Any]:
    """The test points a fixture probes: those named, or all of the side's."""

    return _probed_points(spec, board, [])


def _pin_summary(pin: PogoSpec) -> dict[str, Any]:
    return {
        "identifier": pin.identifier,
        "maker": pin.maker,
        "model": pin.model,
        "barrel_diameter_mm": pin.barrel_diameter_mm,
        "tip_diameter_mm": pin.tip_diameter_mm,
        "free_length_mm": pin.free_length_mm,
        "travel_mm": pin.travel_mm,
        "force_n": pin.force_n,
        "force_at_travel_mm": pin.force_at_travel_mm,
        "figures_from": pin.figures_from,
    }


def _check_pin_against_points(
    spec: PcbFixtureSpec,
    probed: list[Any],
    errors: list[str],
    warnings: list[str],
    summary: dict[str, Any],
) -> None:
    tip = spec.pin.tip_diameter_mm

    for point in probed:
        slack = point.pad_diameter_mm / 2 - tip / 2
        summary["points"].append(
            {
                "identifier": point.identifier,
                "position_mm": [point.x_mm, point.y_mm],
                "pad_diameter_mm": point.pad_diameter_mm,
                "net": point.net,
                # How far the tip may sit off the pad's centre and still touch it.
                "slack_mm": round(slack, 3),
            }
        )

        if slack < 0:
            errors.append(
                f"{point.identifier}: the pin's {tip:g} mm tip is wider than the "
                f"{point.pad_diameter_mm:g} mm pad it must land on"
            )
        elif tip > TIGHT_TIP_SHARE * point.pad_diameter_mm:
            warnings.append(
                f"{point.identifier}: the {tip:g} mm tip covers more than half its "
                f"{point.pad_diameter_mm:g} mm pad, leaving {slack:.2f} mm of slack "
                "for everything that can move it"
            )


def _check_pitch(
    spec: PcbFixtureSpec,
    probed: list[Any],
    profile: Mapping[str, Any] | None,
    errors: list[str],
    warnings: list[str],
    summary: dict[str, Any],
) -> None:
    """The plate's wall between two pins' bores, against the printer's minimum."""

    if len(probed) < 2:
        return

    closest = min(
        math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm)
        for i, a in enumerate(probed)
        for b in probed[i + 1 :]
    )
    summary["closest_pitch_mm"] = round(closest, 3)

    if profile is None:
        warnings.append(
            "The pins' pitch was not checked against a printer: give --printer-profile"
        )

        return

    try:
        fits, _, _ = printer_numbers(profile)
    except ValueError as error:
        errors.append(str(error))

        return

    # A bore for a pin: the barrel is pressed in, so the barrel, the press-fit
    # clearance each side, and the allowance for a printer that prints holes small.
    bore = bore_diameter(spec.pin, fits)
    wall = float(profile.get("minimums_mm", {}).get("wall", 1.2))
    summary["bore_diameter_mm"] = round(bore, 3)
    summary["minimum_wall_mm"] = wall

    for index, a in enumerate(probed):
        for b in probed[index + 1 :]:
            left = math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm) - bore

            if left < wall - 1e-9:
                errors.append(
                    f"Pins on {a.identifier} and {b.identifier} are "
                    f"{math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm):.2f} mm apart; "
                    f"their {bore:.2f} mm bores leave {max(left, 0.0):.2f} mm of plate "
                    f"and the printer's least wall is {wall:g} mm"
                )


def fixture_template(board_file: Path | None = None) -> dict[str, Any]:
    """A valid example fixture file to copy and edit. Given a board file, it
    names that file and its real hash."""

    digest = (
        hashlib.sha256(board_file.read_bytes()).hexdigest()
        if board_file is not None
        else "0" * 64
    )

    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "identifier": "EXAMPLE_FIXTURE",
        "name": "Example fixture: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what this fixture is for and which board it tests",
        "notes": (
            "The fixture holds a board and presses spring pins onto its test "
            "points from a plate above. The board's outline, holes and test points "
            "are in its own file; this file says which to probe and with what. The "
            "pin's figures are yours until a maker's datasheet has been read."
        ),
        "board": {
            "file": str(board_file) if board_file is not None else "board.json",
            "sha256": digest,
        },
        "side": "top",
        "pin": {
            "maker": "EXAMPLE ONLY",
            "model": "EXAMPLE-PIN",
            "barrel_diameter_mm": 1.0,
            "tip_diameter_mm": 0.6,
            "free_length_mm": 14.0,
            "travel_mm": 4.0,
            "force_n": 1.0,
            "force_at_travel_mm": 2.0,
            "source": "EXAMPLE ONLY: the maker's datasheet, or your own measurement",
        },
        "working_travel_mm": 2.0,
        "locating": "outline",
        "closure": "screws",
    }

"""A stack profile: how an item's top and bottom faces meet another's.

A profile file is the interface every stackable item adopts. It holds a cell's pitch and
a height unit, the **foot** section an item stands on, the **lip** section it receives
the foot of the item above in, and the corner radius of a cell. Each section is a short
list of ``[inset, height]`` points: how far in from the item's outer wall, at a height
above where the section starts. A foot rises from a narrow bottom to the full outline
at its top; a lip falls from its widest inward reach at its base to the outer wall at
its tip.

The engine ships **no profile of its own** and every figure carries the file's
``source``: a file whose source is still an ``EXAMPLE`` is refused. The template holds
the figures of the Gridfinity Rebuilt OpenSCAD library, which follows the open
Gridfinity specification, as an example to check and cite, not as a claim.

The check does not take the sections on trust. It lays the foot in the lip at each height
where either turns, reports the least gap between them, and refuses a profile whose foot
would stand outside the lip, or leave less gap than the file says it has.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from zcad_core.features.guide_common import IDENTIFIER, Findings, number

PROFILE_SCHEMA_VERSION = "1.0.0"
PROFILE_KIND = "stack-profile"
# The steepest a section may lean: 45 degrees, the printer's limit without support.
MAXIMUM_LEAN = 1.0
_EPSILON = 1e-9
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "file_kind",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "pitch_mm",
        "height_unit_mm",
        "gap_mm",
        "corner_radius_mm",
        "foot",
        "lip",
        "min_nest_clearance_mm",
        "holding_points",
        "latch",
        "needs_review",
    }
)
Section = tuple[tuple[float, float], ...]

# The Gridfinity Rebuilt OpenSCAD library's figures, which follow the Gridfinity
# specification: src/core/standard.scad, commit 910e22d. An example, to check and cite.
_EXAMPLE_FOOT = [[2.95, 0.0], [2.15, 0.8], [2.15, 2.6], [0.0, 4.75]]
_EXAMPLE_LIP = [[2.6, 0.0], [1.9, 0.7], [1.9, 2.5], [0.0, 4.4]]
# The library's holes sit 8 mm in from the side of the 42 mm cell: 13 mm from its centre.
_EXAMPLE_HOLDING_POINTS = [[13.0, 13.0], [13.0, -13.0], [-13.0, 13.0], [-13.0, -13.0]]
MAXIMUM_HOLDING_POINTS = 16
MINIMUM_POINT_SPACING_MM = 5.0


@dataclass(frozen=True)
class StackProfile:
    """A checked stack profile."""

    identifier: str
    name: str
    pitch_mm: float
    height_unit_mm: float
    gap_mm: float
    corner_radius_mm: float
    foot: Section
    lip: Section
    min_nest_clearance_mm: float
    source: str
    sha256: str
    path: Path
    # Where, from a cell's centre, a magnet pocket or a bolt goes: in the foot's bottom
    # and in a baseplate's floor.
    holding_points: tuple[tuple[float, float], ...] = ()
    # How far a latch's hook engages its keeper, if the profile says: the profile owner's figure,
    # with its source. The engine's own default is used otherwise.
    latch_engagement_mm: float | None = None
    latch_source: str = ""

    @property
    def cell_top_mm(self) -> float:
        """A cell's outline where the foot is widest, and where a bin's walls stand."""

        return self.pitch_mm - self.gap_mm

    @property
    def foot_height_mm(self) -> float:
        return self.foot[-1][1]

    @property
    def lip_height_mm(self) -> float:
        return self.lip[-1][1]


@dataclass(frozen=True)
class ProfileCheck:
    """What a check found: errors make a profile unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def profile_template() -> dict[str, Any]:
    """An example profile file to edit; its source must be replaced."""

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "file_kind": PROFILE_KIND,
        "identifier": "EXAMPLE_PROFILE",
        "name": "Example stack profile: replace every value",
        "units": "mm",
        "source": (
            "EXAMPLE ONLY: say where these figures came from. They are the Gridfinity "
            "Rebuilt OpenSCAD library's (src/core/standard.scad), which follows "
            "https://gridfinity.xyz/specification/; check them against a source you "
            "trust and cite it"
        ),
        "pitch_mm": 42.0,
        "height_unit_mm": 7.0,
        "gap_mm": 0.5,
        "corner_radius_mm": 3.75,
        "foot": _EXAMPLE_FOOT,
        "lip": _EXAMPLE_LIP,
        "min_nest_clearance_mm": 0.25,
        "holding_points": _EXAMPLE_HOLDING_POINTS,
    }


def inset_at(section: Sequence[Sequence[float]], height: float) -> float:
    """How far in from the outer wall the section is at ``height``: its end value
    beyond its top, and its start value below its base."""

    if height <= section[0][1]:
        return float(section[0][0])

    for (inset_a, z_a), (inset_b, z_b) in pairwise(section):
        if height <= z_b:
            return float(inset_a + (inset_b - inset_a) * (height - z_a) / (z_b - z_a))

    return float(section[-1][0])


def nest_clearance_mm(foot: Section, lip: Section) -> float:
    """The least gap, across the wall, between a foot laid in a lip with its base on the
    lip's base: the foot's inset less the lip's, at each height either section turns."""

    top = min(foot[-1][1], lip[-1][1])
    heights = {z for _, z in (*foot, *lip) if z <= top}

    return min(inset_at(foot, z) - inset_at(lip, z) for z in heights)


def _points(entry: Any, name: str, findings: Findings) -> Section | None:
    """A section's points, or ``None`` with the problem recorded."""

    if not isinstance(entry, list) or len(entry) < 2:
        findings.errors.append(
            f"{name} must be a list of at least two [inset, height] points"
        )

        return None

    points: list[tuple[float, float]] = []

    for index, point in enumerate(entry):
        valid = (
            isinstance(point, list)
            and len(point) == 2
            and all(
                isinstance(v, int | float) and not isinstance(v, bool) for v in point
            )
        )

        if not valid:
            findings.errors.append(f"{name}[{index}] must be [inset, height] numbers")

            return None

        points.append((float(point[0]), float(point[1])))

    return tuple(points)


def _check_section(entry: Any, name: str, findings: Findings) -> Section | None:
    points = _points(entry, name, findings)

    if points is None:
        return None

    errors = len(findings.errors)

    if points[0][1] != 0.0:
        findings.errors.append(f"{name} must start at height 0")

    if points[-1][0] != 0.0:
        findings.errors.append(f"{name} must end at inset 0, on the item's outer wall")

    for (inset_a, z_a), (inset_b, z_b) in pairwise(points):
        if z_b <= z_a:
            findings.errors.append(f"{name} heights must rise at every point")
        elif inset_b > inset_a + _EPSILON:
            findings.errors.append(
                f"{name} must not move back in as it rises: {inset_b:g} follows {inset_a:g}"
            )
        elif (inset_a - inset_b) / (z_b - z_a) > MAXIMUM_LEAN + _EPSILON:
            findings.errors.append(
                f"{name} leans more than 45 degrees between heights {z_a:g} and "
                f"{z_b:g}, and would print with support"
            )

    if any(inset < 0 for inset, _ in points):
        findings.errors.append(f"{name} insets cannot be negative")

    return points if len(findings.errors) == errors else None


def _check_source(data: Mapping[str, Any], findings: Findings) -> None:
    source = data.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "source must say where the figures came from: they are yours, and the "
            "engine has none of its own"
        )
    elif source.strip().upper().startswith("EXAMPLE"):
        findings.errors.append(
            "source is still the template's example: check the figures and say where "
            "they came from"
        )


def _check_holding_points(
    data: Mapping[str, Any], findings: Findings
) -> tuple[tuple[float, float], ...]:
    """Where a magnet or a bolt goes in a cell: each ``[x, y]`` from the cell's centre,
    inside the cell and clear of the others."""

    entries = data.get("holding_points")

    if entries is None:
        return ()

    if not isinstance(entries, list) or len(entries) > MAXIMUM_HOLDING_POINTS:
        findings.errors.append(
            f"holding_points must be a list of up to {MAXIMUM_HOLDING_POINTS} [x, y] points"
        )

        return ()

    pitch = data.get("pitch_mm")
    half = pitch / 2 if isinstance(pitch, int | float) else 150.0
    points: list[tuple[float, float]] = []

    for index, entry in enumerate(entries):
        valid = (
            isinstance(entry, list)
            and len(entry) == 2
            and all(
                isinstance(v, int | float) and not isinstance(v, bool) for v in entry
            )
        )

        if not valid:
            findings.errors.append(f"holding_points[{index}] must be [x, y] numbers")
        elif max(abs(entry[0]), abs(entry[1])) >= half:
            findings.errors.append(
                f"holding_points[{index}] is outside the cell: it must be within "
                f"{half:g} mm of the centre"
            )
        else:
            points.append((float(entry[0]), float(entry[1])))

    for index, (x, y) in enumerate(points):
        for other_x, other_y in points[index + 1 :]:
            if (x - other_x) ** 2 + (y - other_y) ** 2 < MINIMUM_POINT_SPACING_MM**2:
                findings.errors.append(
                    f"holding points ({x:g}, {y:g}) and ({other_x:g}, {other_y:g}) are "
                    f"under {MINIMUM_POINT_SPACING_MM:g} mm apart"
                )

    return tuple(points)


def _check_latch(data: Mapping[str, Any], findings: Findings) -> None:
    """The profile's own latch engagement, if it gives one: a figure and its source."""

    entry = data.get("latch")

    if entry is None:
        return

    if not isinstance(entry, Mapping):
        findings.errors.append("latch must be an object")

        return

    unknown = sorted(set(entry) - {"engagement_mm", "source"})

    if unknown:
        findings.errors.append(f"latch has unknown fields: {', '.join(unknown)}")

    number(entry, "engagement_mm", "latch", findings, low=0.1, high=1.5)
    source = entry.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "latch.source must say where the engagement came from: it is your figure"
        )
    elif source.strip().upper().startswith("EXAMPLE"):
        findings.errors.append(
            "latch.source is still an example: say where it came from"
        )


def _check_geometry(
    profile: Mapping[str, float], foot: Section, findings: Findings
) -> None:
    widest = foot[0][0]
    bottom_radius = profile["corner_radius_mm"] - widest

    if bottom_radius < 0.1:
        findings.errors.append(
            f"corner_radius_mm is {profile['corner_radius_mm']:g}: the foot's bottom "
            f"corner would be {bottom_radius:g} mm, under 0.1 mm"
        )

    if profile["pitch_mm"] - profile["gap_mm"] - 2 * widest <= 2 * max(
        bottom_radius, 0
    ):
        findings.errors.append(
            "the foot's bottom would have no width: its inset is too deep for the pitch"
        )


def check_profile_data(data: Any) -> ProfileCheck:
    """Check a profile file's contents."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return ProfileCheck(("A stack profile must hold a JSON object",), ())

    if data.get("schema_version") != PROFILE_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {PROFILE_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    if data.get("file_kind") != PROFILE_KIND:
        findings.errors.append(
            f"file_kind must be {PROFILE_KIND!r}: this is not a stack profile"
        )

    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.errors.append(f"Unknown field(s): {', '.join(unknown)}")

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        findings.errors.append("identifier must be a name of letters, digits, _ . -")

    if data.get("needs_review"):
        findings.errors.append(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    _check_source(data, findings)
    numbers = {
        name: number(data, name, "", findings, low=low, high=high)
        for name, low, high in (
            ("pitch_mm", 5.0, 300.0),
            ("height_unit_mm", 1.0, 100.0),
            ("gap_mm", 0.0, 5.0),
            ("corner_radius_mm", 0.5, 50.0),
            ("min_nest_clearance_mm", 0.0, 2.0),
        )
    }
    points = _check_holding_points(data, findings)
    _check_latch(data, findings)
    foot = _check_section(data.get("foot"), "foot", findings)
    lip = _check_section(data.get("lip"), "lip", findings)

    figures = {name: value for name, value in numbers.items() if value is not None}

    if len(figures) < len(numbers) or foot is None or lip is None:
        return ProfileCheck(tuple(findings.errors), tuple(findings.warnings))

    _check_geometry(figures, foot, findings)
    clearance = nest_clearance_mm(foot, lip)
    stated = float(data["min_nest_clearance_mm"])

    if clearance <= 0:
        findings.errors.append(
            f"the foot does not fit in the lip: it stands {-clearance:g} mm outside it "
            "at its tightest"
        )
    elif clearance < stated - _EPSILON:
        findings.errors.append(
            f"the foot leaves {clearance:g} mm in the lip at its tightest, under the "
            f"{stated:g} mm min_nest_clearance_mm the file states"
        )

    summary = {
        "identifier": data.get("identifier"),
        "pitch_mm": figures["pitch_mm"],
        "height_unit_mm": figures["height_unit_mm"],
        "foot_height_mm": foot[-1][1],
        "lip_height_mm": lip[-1][1],
        "nest_clearance_mm": round(clearance, 4),
        "holding_points": [list(point) for point in points],
    }

    return ProfileCheck(tuple(findings.errors), tuple(findings.warnings), summary)


def read_profile_file(path: Path) -> tuple[Any, str]:
    """A profile file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def load_profile(path: Path) -> StackProfile:
    """A stack profile from a checked file; refuses a file with errors."""

    data, digest = read_profile_file(path)
    report = check_profile_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid stack profile:\n- " + "\n- ".join(report.errors)
        )

    return StackProfile(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        pitch_mm=float(data["pitch_mm"]),
        height_unit_mm=float(data["height_unit_mm"]),
        gap_mm=float(data["gap_mm"]),
        corner_radius_mm=float(data["corner_radius_mm"]),
        foot=tuple((float(i), float(z)) for i, z in data["foot"]),
        lip=tuple((float(i), float(z)) for i, z in data["lip"]),
        min_nest_clearance_mm=float(data["min_nest_clearance_mm"]),
        source=str(data["source"]),
        sha256=digest,
        path=path,
        holding_points=tuple(
            (float(x), float(y)) for x, y in data.get("holding_points", [])
        ),
        latch_engagement_mm=(
            None if "latch" not in data else float(data["latch"]["engagement_mm"])
        ),
        latch_source=("" if "latch" not in data else str(data["latch"]["source"])),
    )

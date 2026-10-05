"""A caliper capture of a wearable device: the measured replacement for the
published dimensions its snap-shell candidates start from, and the **wearable
file** a housing is built round.

The device is one of the catalog's (the Dexcom G7, the Tandem Mobi), whose published
sizes a measurement is checked against, or ``"custom"`` with a ``name``: any sealed
device of the user's own, which has no published size, so nothing stands behind its
numbers but the three readings and the capture's ``source``.

A capture is a JSON file. It holds three caliper readings of each body
dimension, of which the median is used, and every feature on the device's
edges that a clip must not cover, such as the Tandem Mobi's fill port,
buttons, and charging contacts. ``check_capture`` refuses what cannot be
right and warns of what probably is not; ``capture_template`` writes an
example to fill in.

The frame is the snap-shell scripts': the device lies with the face away
from the body up, its length along X and its width along Y, centred on the
origin. The edges are ``north`` (+Y), ``south`` (-Y), ``east`` (+X), and
``west`` (-X). A feature's ``center_offset_mm`` runs along its edge from the
edge's middle: toward +X on ``north`` and ``south``, toward +Y on ``east``
and ``west``.

Beyond the body and its edges a capture may also give, all optional so a capture made
before they existed is still valid:

- ``outline``: ``"rectangle"``, or an object ``{"type": "rounded_rectangle",
  "radius_mm": r}``, the shape of the body seen from above;
- ``face_features``: the buttons, windows, screens and ports on the face away from the
  body that a housing must leave open, each a box ``center_x_mm``, ``center_y_mm``,
  ``width_mm``, ``depth_mm`` in the same frame, lying inside the outline; and
- ``mass``: ``{"value_g": g, "source": where}``, which only a trial's readings use.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from zcad_core.hardware.wearables.dexcom import get_dexcom_g7
from zcad_core.hardware.wearables.tandem import get_tandem_mobi

SCHEMA_VERSION = "1.0.0"
EDGES = ("north", "south", "east", "west")
DIMENSIONS = ("length_mm", "width_mm", "thickness_mm")
READINGS = 3
# Readings of one dimension further apart than this were taken carelessly
# or across a seam; a second pass is cheaper than a print.
SPREAD_WARNING_MM = 0.1
# A measured size this far from the published one is worth a second look,
# and this far off is a wrong unit or two dimensions swapped.
DIFFERENCE_WARNING_MM = 2.0
DIFFERENCE_ERROR_FRACTION = 0.25

CUSTOM = "custom"
OUTLINES = ("rectangle", "rounded_rectangle")
MAXIMUM_MASS_G = 5000.0
_TOP_FIELDS = {
    "schema_version",
    "units",
    "device",
    "name",
    "outline",
    "face_features",
    "mass",
    "measured_by",
    "measured_on",
    "caliper",
    "orientation",
    "source",
    "body_readings",
    "edge_features",
    "edge_features_checked",
    "needs_review",
}
_FEATURE_FIELDS = {"identifier", "edge", "center_offset_mm", "width_mm", "notes"}
_FACE_FIELDS = {
    "identifier",
    "center_x_mm",
    "center_y_mm",
    "width_mm",
    "depth_mm",
    "notes",
}


@dataclass(frozen=True)
class WearableDevice:
    """A device a capture can describe, and what it publishes."""

    key: str
    name: str
    published_mm: tuple[float, float, float]
    # Features a capture of this device should say it located.
    expected_features: tuple[str, ...]


DEVICES = {
    "dexcom-g7": WearableDevice(
        key="dexcom-g7",
        name="Dexcom G7 sensor",
        published_mm=(
            get_dexcom_g7().body_length_mm,
            get_dexcom_g7().body_width_mm,
            get_dexcom_g7().body_thickness_mm,
        ),
        expected_features=(),
    ),
    "tandem-mobi": WearableDevice(
        key="tandem-mobi",
        name="Tandem Mobi pump",
        published_mm=(
            get_tandem_mobi().body_length_mm,
            get_tandem_mobi().body_width_mm,
            get_tandem_mobi().body_thickness_mm,
        ),
        expected_features=("fill-port", "button", "charging-contacts"),
    ),
}


@dataclass(frozen=True)
class EdgeFeature:
    """Something on an edge that a clip must not cover."""

    identifier: str
    edge: str
    center_offset_mm: float
    width_mm: float


@dataclass(frozen=True)
class FaceFeature:
    """Something on the face away from the body that a housing leaves open: a
    box in the capture's frame."""

    identifier: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    depth_mm: float


@dataclass(frozen=True)
class WearableCapture:
    """A checked capture: the median of each dimension, and the features."""

    device: str
    length_mm: float
    width_mm: float
    thickness_mm: float
    edge_features: tuple[EdgeFeature, ...]
    measured_by: str
    measured_on: str
    caliper: str
    source: str
    sha256: str
    path: Path
    # The device's name: the catalog's, or a custom device's own.
    name: str = ""
    # The corner radius when the outline is a rounded rectangle, else ``None``.
    outline_radius_mm: float | None = None
    face_features: tuple[FaceFeature, ...] = ()
    mass_g: float | None = None
    mass_source: str = ""

    def edge_length_mm(self, edge: str) -> float:
        return self.length_mm if edge in ("north", "south") else self.width_mm


@dataclass(frozen=True)
class CaptureCheck:
    """What a capture gets wrong (errors) and what it probably gets wrong."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def capture_template(device: str) -> dict[str, Any]:
    """An example capture for ``device`` to fill in: the published sizes,
    repeated, and a ``needs_review`` note the check refuses until removed."""

    if device == CUSTOM:
        return _custom_template()

    spec = _device(device)
    length, width, thickness = spec.published_mm

    return {
        "schema_version": SCHEMA_VERSION,
        "units": "mm",
        "device": spec.key,
        "needs_review": (
            "EXAMPLE ONLY: every reading below is the published size, not a "
            "measurement. Replace them, fill in who measured and with what, "
            "then delete this line."
        ),
        "measured_by": "EXAMPLE: your name",
        "measured_on": "EXAMPLE: 2026-10-01",
        "caliper": "EXAMPLE: digital caliper, 0.01 mm resolution",
        "orientation": (
            "EXAMPLE: which face is up and which end is east, so the "
            "next person lays the device the same way"
        ),
        "source": "EXAMPLE: one device, measured three times across each face",
        "body_readings": {
            "length_mm": [length] * READINGS,
            "width_mm": [width] * READINGS,
            "thickness_mm": [thickness] * READINGS,
        },
        "edge_features": [
            {
                "identifier": feature,
                "edge": "east",
                "center_offset_mm": 0.0,
                "width_mm": 5.0,
                "notes": "EXAMPLE: where it is and how you measured it",
            }
            for feature in spec.expected_features
        ],
        "edge_features_checked": False,
    }


def _custom_template() -> dict[str, Any]:
    """An example capture of a device of the user's own: example readings that
    are not a measurement, and each optional section shown."""

    return {
        "schema_version": SCHEMA_VERSION,
        "units": "mm",
        "device": CUSTOM,
        "name": "EXAMPLE: the device's name",
        "needs_review": (
            "EXAMPLE ONLY: every reading below is an invented example, not a "
            "measurement. Replace them, fill in who measured and with what, then "
            "delete this line."
        ),
        "measured_by": "EXAMPLE: your name",
        "measured_on": "EXAMPLE: 2026-10-01",
        "caliper": "EXAMPLE: digital caliper, 0.01 mm resolution",
        "orientation": (
            "EXAMPLE: which face is up and which end is east, so the next person "
            "lays the device the same way"
        ),
        "source": "EXAMPLE: one device, measured three times across each face",
        "body_readings": {
            "length_mm": [30.0] * READINGS,
            "width_mm": [20.0] * READINGS,
            "thickness_mm": [8.0] * READINGS,
        },
        "outline": {"type": "rounded_rectangle", "radius_mm": 3.0},
        "edge_features": [
            {
                "identifier": "EXAMPLE-port",
                "edge": "east",
                "center_offset_mm": 0.0,
                "width_mm": 5.0,
                "notes": "EXAMPLE: where it is and how you measured it",
            }
        ],
        "edge_features_checked": False,
        "face_features": [
            {
                "identifier": "EXAMPLE-button",
                "center_x_mm": 0.0,
                "center_y_mm": 0.0,
                "width_mm": 6.0,
                "depth_mm": 6.0,
                "notes": "EXAMPLE: what it is and how you measured it",
            }
        ],
        "mass": {
            "value_g": 10.0,
            "source": "EXAMPLE: a kitchen scale, one device",
        },
    }


def check_capture_data(data: dict[str, Any]) -> CaptureCheck:
    """Every problem with a capture at once."""

    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    if data.get("units") != "mm":
        errors.append('units must be "mm"')

    unknown = sorted(set(data) - _TOP_FIELDS)

    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")

    if "needs_review" in data:
        errors.append(
            "the file still carries needs_review: replace the example values, "
            "then delete that field"
        )

    for field in ("measured_by", "measured_on", "caliper", "orientation", "source"):
        if not str(data.get(field, "")).strip():
            errors.append(f"{field} is required")

    custom = data.get("device") == CUSTOM
    device = DEVICES.get(str(data.get("device")))

    if device is None and not custom:
        errors.append(f"device must be one of {', '.join([*sorted(DEVICES), CUSTOM])}")

    if custom and not str(data.get("name", "")).strip():
        errors.append("a custom device needs a name")
    elif not custom and "name" in data:
        errors.append(f"name is for a custom device; {data.get('device')} has its own")

    medians = _check_readings(data.get("body_readings"), errors, warnings)

    if device is not None and medians is not None:
        _compare_published(device, medians, errors, warnings)

    if data.get("edge_features_checked") is not True:
        errors.append(
            "edge_features_checked must be true: say you looked at every edge "
            "and listed what a clip must not cover (an empty list is allowed)"
        )

    _check_features(data.get("edge_features"), medians, device, errors, warnings)
    radius = _check_outline(data.get("outline"), medians, errors)
    _check_face_features(
        data.get("face_features"), medians, radius, custom, errors, warnings
    )
    _check_mass(data.get("mass"), errors)

    return CaptureCheck(errors=tuple(errors), warnings=tuple(warnings))


def _check_outline(
    outline: object, medians: dict[str, float] | None, errors: list[str]
) -> float | None:
    """The corner radius of a rounded-rectangle outline, or ``None``."""

    if outline is None or outline == "rectangle":
        return None

    if not isinstance(outline, dict) or outline.get("type") != "rounded_rectangle":
        errors.append(
            f"outline must be 'rectangle' or an object with type "
            f"'rounded_rectangle' and radius_mm, not {outline!r}"
        )

        return None

    unknown = sorted(set(outline) - {"type", "radius_mm"})

    if unknown:
        errors.append(f"outline has unknown fields: {', '.join(unknown)}")

    radius = outline.get("radius_mm")

    if not _number(radius) or radius < 0.1:
        errors.append("outline.radius_mm must be a number of at least 0.1")

        return None

    if medians is not None:
        smaller = min(medians["length_mm"], medians["width_mm"])

        if radius > smaller / 2:
            errors.append(
                f"outline.radius_mm is {radius:g}, more than half the device's "
                f"{smaller:g} mm width"
            )

            return None

    return float(radius)


def _inside_outline(
    x: float, y: float, medians: dict[str, float], radius: float | None
) -> bool:
    """Whether a point lies in the body seen from above: the rectangle, less its
    rounded corners."""

    half_x, half_y = medians["length_mm"] / 2, medians["width_mm"] / 2

    if abs(x) > half_x or abs(y) > half_y:
        return False

    if radius is None:
        return True

    dx = abs(x) - (half_x - radius)
    dy = abs(y) - (half_y - radius)

    return dx <= 0 or dy <= 0 or (dx * dx + dy * dy) <= radius * radius


def _check_face_features(
    features: object,
    medians: dict[str, float] | None,
    radius: float | None,
    custom: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Each face feature: a named box lying inside the outline."""

    if features is None:
        if custom:
            warnings.append(
                "no face_features listed: list the buttons, windows and ports on the "
                "face away from the body, or give an empty list if there are none"
            )

        return

    if not isinstance(features, list):
        errors.append("face_features must be a list (empty if there are none)")

        return

    seen: set[str] = set()

    for index, feature in enumerate(features):
        label = f"face_features[{index}]"

        if not isinstance(feature, dict):
            errors.append(f"{label} must be an object")

            continue

        unknown = sorted(set(feature) - _FACE_FIELDS)

        if unknown:
            errors.append(f"{label} has unknown fields: {', '.join(unknown)}")

        name = str(feature.get("identifier", "")).strip()

        if not name:
            errors.append(f"{label} needs an identifier")
        elif name in seen:
            errors.append(f"{label}: {name} is listed twice")

        seen.add(name)
        values: list[Any] = [
            feature.get(key)
            for key in ("center_x_mm", "center_y_mm", "width_mm", "depth_mm")
        ]

        if not all(_number(v) for v in values) or values[2] <= 0 or values[3] <= 0:
            errors.append(
                f"{label} needs center_x_mm, center_y_mm and a positive width_mm "
                "and depth_mm"
            )

            continue

        if medians is None:
            continue

        cx, cy, width, depth = (float(v) for v in values)
        corners = [
            (cx + sx * width / 2, cy + sy * depth / 2)
            for sx in (-1, 1)
            for sy in (-1, 1)
        ]

        if not all(_inside_outline(x, y, medians, radius) for x, y in corners):
            errors.append(f"{label} ({name}) does not lie inside the device's outline")


def _check_mass(mass: object, errors: list[str]) -> None:
    if mass is None:
        return

    if not isinstance(mass, dict):
        errors.append("mass must be an object with value_g and source")

        return

    unknown = sorted(set(mass) - {"value_g", "source"})

    if unknown:
        errors.append(f"mass has unknown fields: {', '.join(unknown)}")

    value = mass.get("value_g")

    if not _number(value) or not 0 < value <= MAXIMUM_MASS_G:
        errors.append(
            f"mass.value_g must be a number above zero and at most "
            f"{MAXIMUM_MASS_G:g} grams"
        )

    if not str(mass.get("source", "")).strip():
        errors.append("mass.source is required: say how the mass was found")


def check_capture(path: Path) -> CaptureCheck:
    """Check a capture file without building anything from it."""

    return check_capture_data(_read(path))


def load_capture(path: Path) -> WearableCapture:
    """A checked capture; raises ``ValueError`` listing every error."""

    data = _read(path)
    check = check_capture_data(data)

    if not check.valid:
        raise ValueError(f"{path} cannot be used: " + "; ".join(check.errors))

    readings = data["body_readings"]
    median = {name: statistics.median(readings[name]) for name in DIMENSIONS}

    outline = data.get("outline")
    radius = (
        float(outline["radius_mm"])
        if isinstance(outline, dict) and outline.get("type") == "rounded_rectangle"
        else None
    )
    mass = data.get("mass") or {}
    key = str(data["device"])

    return WearableCapture(
        device=key,
        name=str(data["name"]) if key == CUSTOM else DEVICES[key].name,
        outline_radius_mm=radius,
        face_features=tuple(
            FaceFeature(
                identifier=str(feature["identifier"]),
                center_x_mm=float(feature["center_x_mm"]),
                center_y_mm=float(feature["center_y_mm"]),
                width_mm=float(feature["width_mm"]),
                depth_mm=float(feature["depth_mm"]),
            )
            for feature in data.get("face_features") or []
        ),
        mass_g=float(mass["value_g"]) if mass else None,
        mass_source=str(mass.get("source", "")),
        length_mm=median["length_mm"],
        width_mm=median["width_mm"],
        thickness_mm=median["thickness_mm"],
        edge_features=tuple(
            EdgeFeature(
                identifier=str(feature["identifier"]),
                edge=str(feature["edge"]),
                center_offset_mm=float(feature["center_offset_mm"]),
                width_mm=float(feature["width_mm"]),
            )
            for feature in data["edge_features"]
        ),
        measured_by=str(data["measured_by"]),
        measured_on=str(data["measured_on"]),
        caliper=str(data["caliper"]),
        source=str(data["source"]),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        path=path,
    )


def _device(device: str) -> WearableDevice:
    try:
        return DEVICES[device]
    except KeyError:
        raise ValueError(
            f"Unknown device {device!r}; one of {', '.join(sorted(DEVICES))}"
        ) from None


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise TypeError(f"{path} must hold a JSON object")

    return data


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_readings(
    readings: object, errors: list[str], warnings: list[str]
) -> dict[str, float] | None:
    """The median of each dimension, or None if any cannot be read."""

    if not isinstance(readings, dict):
        errors.append("body_readings must hold length_mm, width_mm, and thickness_mm")
        return None

    unknown = sorted(set(readings) - set(DIMENSIONS))

    if unknown:
        errors.append(f"unknown body_readings: {', '.join(unknown)}")

    medians: dict[str, float] = {}

    for name in DIMENSIONS:
        values = readings.get(name)

        if (
            not isinstance(values, list)
            or len(values) != READINGS
            or not all(_number(value) and value > 0 for value in values)
        ):
            errors.append(f"body_readings.{name} must be {READINGS} positive readings")
            continue

        spread = max(values) - min(values)

        if spread > SPREAD_WARNING_MM:
            warnings.append(
                f"{name} readings spread {spread:.2f} mm (over "
                f"{SPREAD_WARNING_MM} mm): measure it again"
            )

        medians[name] = float(statistics.median(values))

    return medians if len(medians) == len(DIMENSIONS) else None


def _compare_published(
    device: WearableDevice,
    medians: dict[str, float],
    errors: list[str],
    warnings: list[str],
) -> None:
    for name, published in zip(DIMENSIONS, device.published_mm, strict=True):
        measured = medians[name]
        difference = measured - published

        if abs(difference) > DIFFERENCE_ERROR_FRACTION * published:
            errors.append(
                f"{name} {measured:g} is {abs(difference):.1f} mm from the "
                f"published {published:g}: check the unit and that length, "
                "width, and thickness are not swapped"
            )
        elif abs(difference) > DIFFERENCE_WARNING_MM:
            warnings.append(
                f"{name} {measured:g} differs from the published {published:g} "
                f"by {difference:+.1f} mm: confirm it before printing"
            )


def _check_features(
    features: object,
    medians: dict[str, float] | None,
    device: WearableDevice | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(features, list):
        errors.append("edge_features must be a list (empty if there are none)")
        return

    for index, feature in enumerate(features):
        label = f"edge_features[{index}]"

        if not isinstance(feature, dict):
            errors.append(f"{label} must be an object")
            continue

        unknown = sorted(set(feature) - _FEATURE_FIELDS)

        if unknown:
            errors.append(f"{label} has unknown fields: {', '.join(unknown)}")

        if not str(feature.get("identifier", "")).strip():
            errors.append(f"{label} needs an identifier")

        edge = feature.get("edge")

        if edge not in EDGES:
            errors.append(f"{label}.edge must be one of {', '.join(EDGES)}")

        raw_offset, raw_width = feature.get("center_offset_mm"), feature.get("width_mm")

        if not _number(raw_offset) or not _number(raw_width) or raw_width <= 0:
            errors.append(f"{label} needs center_offset_mm and a positive width_mm")
            continue

        offset, width = float(raw_offset), float(raw_width)

        if medians is not None and edge in EDGES:
            half = (
                medians["length_mm"]
                if edge in ("north", "south")
                else medians["width_mm"]
            ) / 2

            if abs(offset) + width / 2 > half:
                errors.append(f"{label} runs off the end of the {edge} edge")

    # Each one left out would be walled over by a cradle, which notches only
    # the features listed, so a missing one is an error, not a warning.
    if device is not None:
        listed = {
            str(feature.get("identifier", "")).strip()
            for feature in features
            if isinstance(feature, dict)
        }
        missing = [name for name in device.expected_features if name not in listed]

        if missing:
            errors.append(
                f"a {device.name} has {', '.join(device.expected_features)}; "
                f"edge_features leaves out {', '.join(missing)}: list each on "
                "the edge where you found it"
            )

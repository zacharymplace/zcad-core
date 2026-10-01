"""A caliper capture of a wearable device, the measured replacement for the
published dimensions its snap-shell candidates start from.

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

_TOP_FIELDS = {
    "schema_version",
    "units",
    "device",
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

    device = DEVICES.get(str(data.get("device")))

    if device is None:
        errors.append(f"device must be one of {', '.join(sorted(DEVICES))}")

    medians = _check_readings(data.get("body_readings"), errors, warnings)

    if device is not None and medians is not None:
        _compare_published(device, medians, errors, warnings)

    if data.get("edge_features_checked") is not True:
        errors.append(
            "edge_features_checked must be true: say you looked at every edge "
            "and listed what a clip must not cover (an empty list is allowed)"
        )

    _check_features(data.get("edge_features"), medians, device, errors, warnings)

    return CaptureCheck(errors=tuple(errors), warnings=tuple(warnings))


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

    return WearableCapture(
        device=str(data["device"]),
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

    if device is not None and device.expected_features and not features:
        warnings.append(
            f"no edge features listed: a {device.name} has "
            f"{', '.join(device.expected_features)}; list those on an edge"
        )

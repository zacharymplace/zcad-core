"""A ledge nest: a guide for a part with no flat top, resting on its shoulder."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.features.guide import build_guide, guide_record
from zcad_core.features.guide_file import (
    check_guide_data,
    guide_template,
    inspect_guide_file,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
LEDGE = {"depth_mm": 12.0, "wall_mm": 2.0, "bearing": "ledge", "gap_mm": 1.0}


@pytest.fixture(scope="module")
def dome(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A hemisphere of 12 mm radius on a 40 mm cylinder: no flat top, and a
    shoulder where the cylinder is wider."""

    path = tmp_path_factory.mktemp("dome") / "dome.step"
    base = cq.Workplane("XY").circle(20).extrude(10)
    cap = cq.Workplane("XY").sphere(12).translate((0, 0, 10))
    cq.exporters.export(base.union(cap), str(path))

    return path


@pytest.fixture(scope="module")
def pipe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A plain cylinder: no shoulder anywhere."""

    path = tmp_path_factory.mktemp("pipe") / "pipe.step"
    cq.exporters.export(cq.Workplane("XY").circle(15).extrude(30), str(path))

    return path


def data_for(part: Path, **nest: Any) -> dict[str, Any]:
    data = copy.deepcopy(guide_template(part))
    data["nest"] = {**LEDGE, **nest}
    data["plate"] = {}
    data["drill"]["depth_mm"] = 6.0
    data["bores"] = [{"identifier": "B1", "x_mm": 0.0, "y_mm": 0.0}]

    return data


def inspect(directory: Path, data: dict[str, Any]) -> Any:
    path = directory / "guide.json"
    path.write_text(json.dumps(data))

    return inspect_guide_file(path, PROFILE)


def inside(shape: cq.Shape, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, shape).isInside(cq.Vector(x, y, z)))


# --- the file ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("nest", "expect"),
    [
        ({"bearing": "ledge", "gap_mm": 0.1, "depth_mm": 5}, "nest.gap_mm"),
        ({"bearing": "ledge", "gap_mm": 90, "depth_mm": 5}, "nest.gap_mm"),
        ({"bearing": "top", "gap_mm": 1.0, "depth_mm": 5}, "for a ledge bearing"),
        ({"bearing": "wedge", "depth_mm": 5}, "nest.bearing must be one of"),
    ],
)
def test_a_nest_that_cannot_be_right_is_refused(
    nest: dict[str, Any], expect: str
) -> None:
    data = copy.deepcopy(guide_template())
    data["nest"] = nest
    report = check_guide_data(data)

    assert any(expect in error for error in report.errors), report.errors


def test_a_ledge_nest_without_a_gap_is_valid_and_takes_the_default() -> None:
    data = copy.deepcopy(guide_template())
    data["nest"] = {"bearing": "ledge", "depth_mm": 5.0}

    assert check_guide_data(data).valid


# --- the part -----------------------------------------------------------------


def test_a_dome_has_no_flat_top_for_the_plate(dome: Path, tmp_path: Path) -> None:
    report, _, _ = inspect(tmp_path, data_for(dome, bearing="top", gap_mm=None))

    assert any("no flat top" in e for e in report.errors)
    assert any("'ledge'" in e for e in report.errors)


def test_a_dome_rests_a_ledge_nest_on_its_shoulder(dome: Path, tmp_path: Path) -> None:
    report, spec, part = inspect(tmp_path, data_for(dome))

    assert report.valid, report.errors
    assert report.part is not None
    assert report.part["bearing"] == "ledge"
    assert report.part["gap_mm"] == 1.0
    # The annulus where the 40 mm cylinder is wider than the dome's 24 mm
    # footprint, under the rim.
    assert report.part["bearing_area_mm2"] > 100
    assert spec is not None and part is not None


def test_a_nest_with_no_shoulder_under_it_is_refused(
    pipe: Path, tmp_path: Path
) -> None:
    report, _, _ = inspect(tmp_path, data_for(pipe, depth_mm=10.0))

    assert any("widens under a ledge nest by only" in e for e in report.errors)
    assert any("a shoulder of the part" in e for e in report.errors)


def test_a_nest_that_reaches_the_bottom_has_nothing_under_it(
    dome: Path, tmp_path: Path
) -> None:
    report, _, _ = inspect(tmp_path, data_for(dome, depth_mm=24.0))

    assert any("no shoulder under the nest" in e for e in report.errors)


# --- the guide -----------------------------------------------------------------


@pytest.fixture(scope="module")
def guide(dome: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("guide")
    report, spec, part = inspect(directory, data_for(dome))
    assert report.valid and spec is not None and part is not None

    return build_guide(spec, part, PROFILE)


def test_the_ledge_guide_passes_its_checks(guide: Any) -> None:
    assert guide.passed, (guide.checks, guide.problems)
    assert guide.plate_base_mm == 1.0
    assert guide.bearing_area_mm2 > 100


def test_the_plate_stands_a_gap_above_the_dome(guide: Any) -> None:
    solid = guide.body.val()

    # The plate occupies 1.0 to 7.0 mm above the dome's top; the nest's walls
    # run 12 mm down beside it.
    assert inside(solid, 8.0, 0.0, 4.0)
    assert not inside(solid, 8.0, 0.0, 0.5)
    assert inside(solid, 13.3, 0.0, -6.0)
    assert not inside(solid, 0.0, 0.0, 4.0)  # the bore


def test_the_nest_wall_stops_at_the_shoulder_and_rests_there(guide: Any) -> None:
    solid = guide.body.val()
    box = solid.BoundingBox()

    assert box.zmin == pytest.approx(-12.0, abs=0.05)
    assert box.zmax == pytest.approx(7.0, abs=0.05)

    # Lowered a little further, the rim meets the part: that is what it rests on.
    lowered = solid.moved(cq.Location(cq.Vector(0, 0, -0.3)))
    assert intersection_volume(lowered, guide.part.shape) > 1.0
    assert intersection_volume(solid, guide.part.shape) < 1e-6


def test_the_bit_must_cross_the_gap_too(guide: Any) -> None:
    (planned,) = guide.bores

    # Up from the plate (0), through the 6 mm plate, across the 1 mm gap, and the
    # 6 mm hole.
    assert planned.bit_needed_mm == pytest.approx(13.0)
    assert planned.chuck_standoff_mm == 0.0


def test_the_record_says_how_the_nest_rests(guide: Any) -> None:
    record = guide_record(guide, {})

    assert record["nest"]["bearing"] == "ledge"
    assert record["nest"]["gap_mm"] == 1.0
    assert record["nest"]["bearing_area_mm2"] > 100
    assert record["verified"] is False


def test_a_top_nest_is_unchanged(tmp_path: Path) -> None:
    plate = tmp_path / "plate.step"
    cq.exporters.export(
        cq.Workplane("XY").box(50, 30, 10, centered=(True, True, False)), str(plate)
    )
    data = copy.deepcopy(guide_template(plate))
    data["nest"] = {"depth_mm": 8.0, "wall_mm": 2.0, "bearing": "top"}
    report, spec, part = inspect(tmp_path, data)
    assert report.valid and spec is not None and part is not None
    built = build_guide(spec, part, PROFILE)

    assert built.passed
    assert built.plate_base_mm == 0.0
    assert built.bearing_area_mm2 is None
    assert built.bores[0].bit_needed_mm == pytest.approx(12.0)

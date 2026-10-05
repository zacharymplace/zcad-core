"""Vent windows: a stack top that leaves a lid's outlets open."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.mount_stack import (
    MAXIMUM_WINDOWS,
    _merge,
    _offsets,
    build_stack_top,
    lid_openings,
    plain_lid,
    vent_cells,
)
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import load_profile, profile_template
from zcad_core.hardware import get_fastener

SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
M3 = get_fastener("M3")
LID_TOP = 8.0
LID_Z = 6.0
# A lid three cells long: screws at the two ends, an outlet in the middle.
SCREWS = [(-40.0, -10.0), (-40.0, 10.0), (40.0, -10.0), (40.0, 10.0)]


def write_profile(directory: Path) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def top_for(
    tmp_path: Path,
    openings: Any,
    positions: Any = SCREWS,
    size: tuple[float, float] = (124.0, 40.0),
) -> Any:
    return build_stack_top(
        positions,
        centre=(0.0, 0.0),
        lid_size_mm=size,
        lid_top_z_mm=LID_TOP,
        lid_mm=2.0,
        fastener=M3,
        profile=load_profile(write_profile(tmp_path)),
        compensation=0.0,
        openings=openings,
    )


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue() or "{}"))


# --- finding the openings -----------------------------------------------------------------------


def test_close_rectangles_are_one_and_far_ones_stay_apart() -> None:
    near = [(0.0, 0.0, 2.0, 2.0), (3.0, 0.0, 5.0, 2.0)]
    far = [(0.0, 0.0, 2.0, 2.0), (30.0, 0.0, 32.0, 2.0)]

    assert _merge(near, 4.0) == [(0.0, 0.0, 5.0, 2.0)]
    assert _merge(far, 4.0) == far
    assert _merge([], 4.0) == []


def slot(x: float, y: float, w: float, h: float, z0: float, z1: float) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(w, h, z1 - z0, centered=(True, True, False))
        .translate((x, y, z0))
    )


def test_the_openings_are_what_the_lid_has_cut_right_through() -> None:
    reference = plain_lid((0.0, 0.0), (124.0, 40.0), LID_Z, 2.0, SCREWS, 3.4)
    lid = reference.cut(slot(-4.0, 0.0, 2.0, 12.0, LID_Z - 1, LID_Z + 3))
    lid = lid.cut(slot(0.0, 0.0, 2.0, 12.0, LID_Z - 1, LID_Z + 3))
    lid = lid.cut(slot(4.0, 0.0, 2.0, 12.0, LID_Z - 1, LID_Z + 3))
    # A pocket in the top that does not go through is not an opening.
    lid = lid.cut(slot(30.0, 0.0, 6.0, 6.0, LID_Z + 1.0, LID_Z + 3))
    openings = lid_openings(lid, reference, LID_Z, LID_Z + 2.0)

    assert len(openings) == 1
    x0, y0, x1, y1 = openings[0]

    assert (x0, x1) == (pytest.approx(-5.0, abs=0.1), pytest.approx(5.0, abs=0.1))
    assert (y0, y1) == (pytest.approx(-6.0, abs=0.1), pytest.approx(6.0, abs=0.1))


def test_a_lid_with_only_its_screw_holes_has_no_openings() -> None:
    reference = plain_lid((0.0, 0.0), (124.0, 40.0), LID_Z, 2.0, SCREWS, 3.4)

    assert lid_openings(reference, reference, LID_Z, LID_Z + 2.0) == []


# --- the plate ----------------------------------------------------------------------------------


def test_the_cells_a_window_touches_are_the_vent_cells(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path))

    assert vent_cells([(-12.0, -10.0, 12.0, 10.0)], (3, 1), profile) == {1}
    assert vent_cells([(-30.0, -10.0, 12.0, 10.0)], (3, 1), profile) == {0, 1}
    assert vent_cells([], (3, 1), profile) == frozenset()


def test_a_vent_cell_has_a_window_through_it_and_no_pocket(tmp_path: Path) -> None:
    top = top_for(tmp_path, [(-10.0, -8.0, 10.0, 8.0)])
    floor_top = LID_TOP + top.floor_mm

    assert top.cells == (3, 1) and top.vent_cells == (1,)
    assert top.stack["cells_usable"] == 2
    # The window goes right through, clear of the screws.
    for z in (LID_TOP + 0.5, floor_top - 1.0, floor_top + 2.0):
        assert not inside(top.plate, 0.0, 0.0, z)

    # Beside the window in the vent cell the plate is solid to its full height, with no pocket.
    assert inside(top.plate, 15.0, 15.0, floor_top + 2.0)
    # A cell with no window has its pocket.
    assert not inside(top.plate, -42.0, 0.0, floor_top + 0.5)
    assert inside(top.plate, -42.0, 0.0, floor_top - 0.5)
    assert top.stack["vent_cells"] == [1] and len(top.stack["vent_windows_mm"]) == 1
    # The window is the opening grown by a margin each way.
    x0, y0, x1, y1 = top.stack["vent_windows_mm"][0]

    assert (x0, y0, x1, y1) == (-12.0, -10.0, 12.0, 10.0)


def test_openings_whose_windows_would_leave_a_fin_are_one_window(
    tmp_path: Path,
) -> None:
    # 4.5 mm apart, they are two openings; grown 2 mm each way they would leave a 0.5 mm fin
    # of plate the full height between them, so they are one window.
    top = top_for(tmp_path, [(-10.0, -5.0, -2.25, 5.0), (2.25, -5.0, 10.0, 5.0)])

    assert top.windows == ((-12.0, -7.0, 12.0, 7.0),)
    assert not inside(top.plate, 0.0, 0.0, LID_TOP + 0.5)


def test_a_top_with_no_openings_has_no_vent_cells(tmp_path: Path) -> None:
    top = top_for(tmp_path, [])

    assert top.vent_cells == () and top.stack["vent_cells"] == []
    assert top.stack["cells_usable"] == top.cells[0] * top.cells[1]


def test_a_screw_in_a_cell_with_a_window_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="in a cell with no window"):
        top_for(tmp_path, [(-10.0, -8.0, 10.0, 8.0)], positions=[(0.0, 10.0)])


def test_openings_too_scattered_for_a_plate_are_refused(tmp_path: Path) -> None:
    many = [(10.0 * i, 0.0, 10.0 * i + 2.0, 2.0) for i in range(MAXIMUM_WINDOWS + 1)]

    with pytest.raises(ValueError, match="at most 4"):
        top_for(tmp_path, many)


def test_a_window_that_takes_every_cell_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No stack top"):
        top_for(tmp_path, [(-70.0, -25.0, 70.0, 25.0)])


# --- the enclosure and check-stack --------------------------------------------------------------


def build_group(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        "pi5",
        "--stack-top",
        "--stack-profile",
        str(write_profile(tmp_path)),
        "--output-directory",
        str(tmp_path / "group"),
    )

    assert code == 0, built

    return built, tmp_path / "group" / "enclosure-group.json"


def test_a_row_with_fan_slots_gets_a_window_and_asks_a_check(tmp_path: Path) -> None:
    built, record = build_group(tmp_path)
    data = json.loads(record.read_text())
    stack = data["stack_top"]

    assert built["validation_status"] == "PASS"
    assert stack["vent_cells"] == [1, 4] and stack["cells_usable"] == 7
    assert "stack_top_vents_open" in data["checks"]
    # The window covers the fan slots, which are the lid's only openings.
    assert len(stack["vent_windows_mm"]) == 1


def test_a_bin_stands_on_the_usable_cells_and_not_over_a_vent_cell(
    tmp_path: Path,
) -> None:
    _, record = build_group(tmp_path)
    data = stack_template(tmp_path / "profile.json")
    data["source"] = "a stack for tests"
    data["items"] = [
        {"kind": "bin", "name": "one", "cells": [1, 1], "units": 2},
        {"kind": "bin", "name": "all", "cells": [3, 3], "units": 2},
    ]
    stack = tmp_path / "stack.json"
    stack.write_text(json.dumps(data))
    code, report = run(
        "stack", "check-stack", "--upper", f"{stack}:one", "--lower", f"{record}:top"
    )

    assert code == 0 and report["stacks"] is True, report
    code, report = run(
        "stack", "check-stack", "--upper", f"{stack}:all", "--lower", f"{record}:top"
    )

    assert code == 1
    assert any("vent cells [1, 4]" in e for e in report["errors"]), report


def test_a_pico_with_an_outlet_is_refused_because_its_screws_share_the_cells(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--vent-area-mm2",
        "300",
        "--stack-top",
        "--stack-profile",
        str(write_profile(tmp_path)),
        "--output-directory",
        str(tmp_path / "pico"),
    )

    assert code == 1
    assert "in a cell with no window" in capsys.readouterr().err


# --- shifting the plate off the lid's centre ----------------------------------------------------


def test_with_no_windows_the_plate_is_not_shifted(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path))

    assert _offsets((3, 1), (60.0, 40.0), profile, False) == [(0.0, 0.0)]
    assert top_for(tmp_path, []).stack["offset_mm"] == [0.0, 0.0]


def test_the_shifts_tried_are_the_least_first_and_keep_the_lid_covered(
    tmp_path: Path,
) -> None:
    profile = load_profile(write_profile(tmp_path))
    shifts = _offsets((3, 1), (60.0, 40.0), profile, True)

    assert shifts[0] == (0.0, 0.0)
    sizes = [x * x + y * y for x, y in shifts[1:]]

    assert sizes == sorted(sizes)
    # A plate of three cells is 128.4 mm long against a 60 mm lid, so it may move 34 mm along
    # it; across, 44.4 mm against 40 mm leaves 2.2 mm, so 2 mm.
    assert max(abs(x) for x, _ in shifts) == 34.0
    assert max(abs(y) for _, y in shifts) == 2.0


def test_a_window_off_the_middle_is_met_by_shifting_the_plate(tmp_path: Path) -> None:
    # The window is over a cell at the left that holds a screw, with the plate centred.
    top = top_for(
        tmp_path,
        [(-24.0, -5.0, -16.0, 5.0)],
        positions=[(-34.0, -10.0), (-34.0, 10.0), (34.0, -10.0), (34.0, 10.0)],
        size=(60.0, 40.0),
    )

    assert top.cells == (3, 1) and top.vent_cells == (1,)
    assert top.stack["offset_mm"] == [-5.0, 0.0]
    box = top.plate.val().BoundingBox()

    assert (box.xmin + box.xmax) / 2 == pytest.approx(-5.0, abs=0.01)
    # The window is through the plate, and a screw's hole is open beside the pockets.
    assert not inside(top.plate, -20.0, 0.0, LID_TOP + 1.0)
    assert not inside(top.plate, 34.0, 10.0, LID_TOP + 0.5)
    # The pockets are where the shifted cells are: left of the vent cell, and right of it.
    floor_top = LID_TOP + top.floor_mm
    assert not inside(top.plate, -47.0, 0.0, floor_top + 0.5)
    assert not inside(top.plate, 37.0, 0.0, floor_top + 0.5)
    assert inside(top.plate, -47.0, 0.0, floor_top - 0.5)


def test_a_lid_whose_outlet_fills_it_is_still_refused_with_the_shift_named(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="even with the plate shifted"):
        top_for(tmp_path, [(-70.0, -8.0, 70.0, 8.0)], positions=[(0.0, 10.0)])

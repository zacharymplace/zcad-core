"""The stack top: a baseplate over a screwed lid, held by the lid's own screws."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure import EnclosureDesign
from zcad_core.features.enclosure_checks import _require_stack_top_possible
from zcad_core.features.mount_stack import (
    build_stack_top,
    recess_depth_mm,
    require_top_fits_bed,
)
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import load_profile, profile_template
from zcad_core.hardware import get_fastener
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
M3 = get_fastener("M3")
LID_TOP = 8.0
SCREWS = [(-12.0, -31.0), (12.0, -31.0), (-12.0, 31.0), (12.0, 31.0)]


def write_profile(directory: Path, **changes: Any) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    data.update(changes)
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def top_for(tmp_path: Path, positions: Any = SCREWS, **changes: Any) -> Any:
    profile = load_profile(write_profile(tmp_path, **changes))

    return build_stack_top(
        positions,
        centre=(0.0, 0.0),
        lid_size_mm=(36.0, 80.0),
        lid_top_z_mm=LID_TOP,
        lid_mm=2.0,
        fastener=M3,
        profile=profile,
        compensation=0.0,
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


# --- the design ---------------------------------------------------------------------------------


def test_a_stack_top_goes_with_its_profile() -> None:
    with pytest.raises(ValueError, match="go together"):
        EnclosureDesign(stack_top=True).validate()

    with pytest.raises(ValueError, match="go together"):
        EnclosureDesign(stack_profile="p.json").validate()

    EnclosureDesign(stack_top=True, stack_profile="p.json").validate()
    EnclosureDesign(mount="stack", stack_top=True, stack_profile="p.json").validate()


def design(**changes: Any) -> EnclosureDesign:
    return EnclosureDesign(stack_top=True, stack_profile="p.json", **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"lid_attachment": "snap"}, "the lid is 'snap'"),
        ({"lid_attachment": "hinge"}, "the lid is 'hinge'"),
        ({"lid_attachment": "slide"}, "the lid is 'slide'"),
        (
            {"fan": "x", "fan_position": "lid"},
            "a fan is mounted on the lid",
        ),
    ],
)
def test_a_lid_that_moves_or_has_a_fan_on_it_is_refused_with_the_reason(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match="cannot go on this enclosure") as raised:
        _require_stack_top_possible(design(**changes))

    assert message in str(raised.value)


def test_a_plain_screwed_lid_is_allowed_with_vents_and_outlets() -> None:
    # Wall vents and lid outlets are not reasons: the plate leaves a window over an outlet.
    _require_stack_top_possible(design(vent_slots=2))
    _require_stack_top_possible(design(vent_area_mm2=300.0))


def test_every_reason_is_listed_at_once() -> None:
    with pytest.raises(ValueError) as raised:
        _require_stack_top_possible(
            design(lid_attachment="snap", fan="x", fan_position="lid")
        )

    assert str(raised.value).count("\n- ") == 2


# --- the plate ----------------------------------------------------------------------------------


def test_the_plate_is_whole_cells_with_its_underside_flat_on_the_lid(
    tmp_path: Path,
) -> None:
    top = top_for(tmp_path)
    box = top.plate.val().BoundingBox()

    assert top.cells == (1, 2)
    assert box.zmin == pytest.approx(LID_TOP, abs=1e-3)
    assert box.zlen == pytest.approx(top.thickness_mm)
    # A floor of the recess and a millimetre, and the pocket's depth on it.
    assert top.floor_mm == pytest.approx(recess_depth_mm(M3) + 1.0)
    assert top.thickness_mm == pytest.approx(top.floor_mm + 4.35, abs=0.01)
    assert box.xlen == pytest.approx(42.0 + 2 * 1.2, abs=0.01)
    assert box.ylen == pytest.approx(84.0 + 2 * 1.2, abs=0.01)


def test_each_lid_screw_goes_through_a_recess_sunk_in_a_pocket_floor(
    tmp_path: Path,
) -> None:
    top = top_for(tmp_path)
    floor_top = LID_TOP + top.floor_mm
    recess = top.screw_recess_mm
    x, y = SCREWS[0]

    # The hole is open the whole way, the recess wider and open above the floor under it.
    assert not inside(top.plate, x, y, LID_TOP + 0.5)
    assert not inside(top.plate, x, y, floor_top - recess + 0.5)
    assert inside(top.plate, x + 2.5, y, LID_TOP + 0.5)
    assert not inside(top.plate, x + 2.5, y, floor_top - 0.5)
    # A millimetre of floor is left under the head.
    assert inside(top.plate, x + 2.5, y, floor_top - recess - 0.5)
    # And the pocket's floor is flat elsewhere, with the pocket open above it.
    assert inside(top.plate, 0.0, 21.0 - 10.0, floor_top - 0.5)
    assert not inside(top.plate, 0.0, 21.0 - 10.0, floor_top + 0.5)


def test_the_screws_are_longer_by_the_plate_and_the_build_names_the_reach(
    tmp_path: Path,
) -> None:
    top = top_for(tmp_path)

    # A millimetre under the head, the 2 mm lid, and the insert's 5 mm.
    assert top.screw_reach_mm == pytest.approx(1.0 + 2.0 + 5.0)
    assert top.recommended_screw_mm == 8
    assert top.stack["recommended_screw_mm"] == 8
    assert top.stack["lid_top_z_mm"] == LID_TOP
    assert top.stack["floor_mm"] == pytest.approx(4.5)


def test_a_lid_with_no_screws_cannot_hold_a_top(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="this lid has none"):
        top_for(tmp_path, positions=[])


def test_screws_that_fit_no_grid_of_pockets_are_refused(tmp_path: Path) -> None:
    # One screw on a cell's middle and one on a ridge, whatever the cells.
    with pytest.raises(ValueError, match="No stack top of"):
        top_for(tmp_path, positions=[(0.0, 0.0), (21.0, 21.0)])


def test_a_top_bigger_than_the_bed_is_refused_with_its_cells(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path))
    top = build_stack_top(
        [(-80.0, -30.0), (80.0, -30.0), (-80.0, 30.0), (80.0, 30.0)],
        centre=(0.0, 0.0),
        lid_size_mm=(176.0, 96.0),
        lid_top_z_mm=LID_TOP,
        lid_mm=2.0,
        fastener=M3,
        profile=profile,
        compensation=0.0,
    )

    with pytest.raises(ValueError, match="The stack top is 5 x"):
        require_top_fits_bed(top, PRINTER["build_volume_mm"])

    require_top_fits_bed(None, PRINTER["build_volume_mm"])


# --- the enclosure ------------------------------------------------------------------------------


def build_pico(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any], Path]:
    profile = write_profile(tmp_path)
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--stack-top",
        "--stack-profile",
        str(profile),
        "--output-directory",
        str(tmp_path / "pico"),
        *extra,
    )

    return code, built, tmp_path / "pico" / "enclosure.json"


def test_an_enclosure_with_a_stack_top_builds_and_records_it(tmp_path: Path) -> None:
    code, built, record = build_pico(tmp_path)

    assert code == 0 and built["validation_status"] == "PASS"
    assert "stack_top" in built["parts"]
    top = built["stack_top"]

    assert top["cells"] == [1, 2] and top["floor_mm"] == pytest.approx(4.5)
    assert "M3 x 8 mm, 4 through the plate and the lid" in top["screws"]
    data = json.loads(record.read_text())

    assert data["stack_top"]["cells"] == [1, 2]
    assert data["stack_top"]["profile"]["identifier"] == "EXAMPLE_PROFILE"
    assert data["stack"] is None


def test_a_plain_enclosure_has_no_stack_top(tmp_path: Path) -> None:
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--output-directory",
        str(tmp_path / "plain"),
    )

    assert code == 0 and built["stack_top"] is None
    assert "stack_top" not in built["parts"]


def test_a_stack_top_with_a_snap_lid_is_refused_at_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = build_pico(tmp_path, "--lid", "snap")

    assert code == 1
    assert "the lid is 'snap'" in capsys.readouterr().err


def test_a_stack_top_without_a_profile_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--stack-top",
        "--output-directory",
        str(tmp_path / "bare"),
    )

    assert code == 1 and "go together" in capsys.readouterr().err


def write_stack_file(directory: Path, items: list[dict[str, Any]]) -> Path:
    data = stack_template(directory / "profile.json")
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def check(upper: str, lower: str) -> tuple[int, dict[str, Any]]:
    return run("stack", "check-stack", "--upper", upper, "--lower", lower)


def test_things_stack_on_the_top_as_on_a_baseplate(tmp_path: Path) -> None:
    _, _, record = build_pico(tmp_path)
    stack = write_stack_file(
        tmp_path,
        [
            {"kind": "bin", "name": "tub", "cells": [1, 2], "units": 2},
            {"kind": "bin", "name": "small", "cells": [1, 1], "units": 2},
            {"kind": "cap", "name": "lid", "cells": [1, 2]},
        ],
    )
    code, report = check(f"{stack}:tub", f"{record}:top")

    assert code == 0 and report["stacks"] is True, report
    assert report["lower"].startswith("raspberry-pi-pico-2-enclosure-top (baseplate")
    # A bin of fewer cells goes on a baseplate of more, a cap goes on nothing here.
    code, report = check(f"{stack}:small", f"{record}:top")
    assert code == 0 and report["stacks"] is True
    code, report = check(f"{stack}:lid", f"{record}:top")
    assert code == 1 and any("not a baseplate" in e for e in report["errors"])


def test_a_record_without_a_stack_top_says_how_to_build_one(tmp_path: Path) -> None:
    run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--output-directory",
        str(tmp_path / "plain"),
    )
    write_profile(tmp_path)
    stack = write_stack_file(
        tmp_path, [{"kind": "bin", "name": "tub", "cells": [1, 2], "units": 2}]
    )
    code, report = check(f"{stack}:tub", f"{tmp_path / 'plain' / 'enclosure.json'}:top")

    assert code == 1
    assert any("has no stack top" in e for e in report["errors"])

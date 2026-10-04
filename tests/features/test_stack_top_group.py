"""The stack top on a group enclosure: a baseplate over a screwed row's lid."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group_checks import _require_stack_top_possible
from zcad_core.features.enclosure_group_model import GroupDesign
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import profile_template

SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"


def write_profile(directory: Path, **changes: Any) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    data.update(changes)
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue() or "{}"))


def build_group(
    tmp_path: Path, *extra: str, bays: str = "pi5"
) -> tuple[int, dict[str, Any], Path]:
    profile = write_profile(tmp_path)
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        bays,
        "--stack-top",
        "--stack-profile",
        str(profile),
        "--no-vents",
        "--output-directory",
        str(tmp_path / "group"),
        *extra,
    )

    return code, built, tmp_path / "group" / "enclosure-group.json"


def test_a_group_stack_top_goes_with_its_profile() -> None:
    with pytest.raises(ValueError, match="go together"):
        GroupDesign(stack_top=True).validate()

    with pytest.raises(ValueError, match="go together"):
        GroupDesign(stack_profile="p.json").validate()

    GroupDesign(stack_top=True, stack_profile="p.json").validate()
    GroupDesign(mount="stack", stack_top=True, stack_profile="p.json").validate()


@pytest.mark.parametrize(
    ("changes", "fans", "message"),
    [
        ({"lid_attachment": "hinge"}, 0, "the lid is 'hinge'"),
        ({"lid_attachment": "slide"}, 0, "the lid is 'slide'"),
        ({}, 1, "a fan is mounted on the lid"),
    ],
)
def test_a_row_whose_lid_moves_or_has_a_fan_is_refused_with_the_reason(
    changes: dict[str, Any], fans: int, message: str
) -> None:
    design = GroupDesign(stack_top=True, stack_profile="p.json", **changes)

    with pytest.raises(ValueError, match="cannot go on this row") as raised:
        _require_stack_top_possible(design, fans=fans)

    assert message in str(raised.value)


def test_slots_and_outlets_are_not_reasons_to_refuse() -> None:
    design = GroupDesign(stack_top=True, stack_profile="p.json", vent_area_mm2=400.0)

    _require_stack_top_possible(design, fans=0)


def test_every_reason_is_listed_at_once() -> None:
    design = GroupDesign(stack_top=True, stack_profile="p.json", lid_attachment="hinge")

    with pytest.raises(ValueError) as raised:
        _require_stack_top_possible(design, fans=1)

    assert str(raised.value).count("\n- ") == 2


def test_a_one_bay_pi5_row_builds_a_top_and_records_it(tmp_path: Path) -> None:
    code, built, record = build_group(tmp_path)

    assert code == 0 and built["validation_status"] == "PASS"
    assert "stack_top" in built["parts"]
    top = built["stack_top"]

    assert top["floor_mm"] == pytest.approx(4.5)
    assert top["thickness_mm"] == pytest.approx(8.85, abs=0.01)
    # The group's lid is 3 mm: a millimetre under the head, the lid and the insert.
    assert top["screw_reach_mm"] == pytest.approx(1.0 + 3.0 + 5.0)
    assert "M3 x 8 mm" in top["screws"]
    data = json.loads(record.read_text())

    assert data["stack_top"]["cells"] == top["cells"]
    assert data["stack_top"]["profile"]["identifier"] == "EXAMPLE_PROFILE"
    assert data["stack"] is None
    assert data["design"]["stack_top"] is True


def test_the_plate_covers_the_lid_and_sits_on_its_top_face(tmp_path: Path) -> None:
    code, built, record = build_group(tmp_path)
    data = json.loads(record.read_text())
    top = built["stack_top"]

    assert code == 0
    assert top["size_mm"][0] >= data["outer_size_mm"][0]
    assert top["size_mm"][1] >= data["outer_size_mm"][1]
    # The plate stands on the lid's top, the row's height and the lid on it.
    assert data["stack_top"]["lid_top_z_mm"] == pytest.approx(
        data["outer_size_mm"][2] + data["design"]["lid_mm"], abs=0.01
    )


def test_the_default_row_with_its_fan_slots_builds_with_a_window_over_them(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path)
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        "pi5",
        "--stack-top",
        "--stack-profile",
        str(profile),
        "--output-directory",
        str(tmp_path / "default"),
    )

    assert code == 0 and built["validation_status"] == "PASS"
    stack = built["stack_top"]["stack"]

    assert stack["vent_cells"] and stack["vent_windows_mm"]
    assert stack["cells_usable"] == stack["cells"][0] * stack["cells"][1] - len(
        stack["vent_cells"]
    )


def test_a_sliding_row_is_refused_at_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = build_group(tmp_path, "--lid", "slide", bays="pi5,pi5")

    assert code == 1
    assert "the lid is 'slide'" in capsys.readouterr().err


def write_stack_file(directory: Path, items: list[dict[str, Any]]) -> Path:
    data = stack_template(directory / "profile.json")
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def test_things_stack_on_the_groups_top_as_on_a_baseplate(tmp_path: Path) -> None:
    _, built, record = build_group(tmp_path)
    cells = built["stack_top"]["cells"]
    stack = write_stack_file(
        tmp_path,
        [
            {"kind": "bin", "name": "tub", "cells": cells, "units": 2},
            {"kind": "bin", "name": "one", "cells": [1, 1], "units": 2},
        ],
    )
    code, report = run(
        "stack", "check-stack", "--upper", f"{stack}:tub", "--lower", f"{record}:top"
    )

    assert code == 0 and report["stacks"] is True, report
    assert report["lower"].startswith("pi5-group-1bay-top (baseplate")
    code, report = run(
        "stack", "check-stack", "--upper", f"{stack}:one", "--lower", f"{record}:top"
    )

    assert code == 0 and report["stacks"] is True


def test_a_row_too_wide_for_the_bed_is_refused_with_its_cells(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = build_group(tmp_path, bays="pi5,pi5")

    assert code == 1
    err = capsys.readouterr().err

    assert "row is" in err or "The stack top is" in err

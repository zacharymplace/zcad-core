"""Stack profiles, stack files, and the bins and baseplates built on them."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.stack import build_stack, require_fits_bed
from zcad_core.features.stack_check import check_stackable
from zcad_core.features.stack_file import (
    check_stack_data,
    check_stack_file,
    load_stack,
    stack_template,
)
from zcad_core.features.stack_profile import (
    check_profile_data,
    inset_at,
    load_profile,
    nest_clearance_mm,
    profile_template,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"


def profile_data(**changes: Any) -> dict[str, Any]:
    data = profile_template()
    data["source"] = SOURCE
    data.update(changes)

    return data


def write_profile(directory: Path, **changes: Any) -> Path:
    path = directory / "profile.json"
    path.write_text(json.dumps(profile_data(**changes)))

    return path


def write_stack(
    directory: Path, profile: Path, items: list[dict[str, Any]], **changes: Any
) -> Path:
    data = stack_template(profile)
    data["source"] = "a stack for tests"
    data["items"] = items
    data.update(changes)
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


def build(directory: Path, items: list[dict[str, Any]], **changes: Any) -> Any:
    profile = write_profile(directory, **changes)
    path = write_stack(directory, profile, items)

    return build_stack(load_stack(path), PRINTER)


@pytest.fixture(scope="module")
def basic(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("basic")

    return build(
        directory,
        [
            {"kind": "bin", "name": "bin", "cells": [1, 1], "units": 3},
            {"kind": "baseplate", "name": "plate", "cells": [1, 1]},
        ],
    )


# --- the profile --------------------------------------------------------------------------------


def test_the_template_is_refused_until_its_source_is_replaced() -> None:
    template = profile_template()
    report = check_profile_data(template)

    assert not report.valid
    assert any("still the template's example" in e for e in report.errors)

    template["source"] = SOURCE

    assert check_profile_data(template).valid


def test_a_profile_says_how_far_its_foot_sits_in_its_lip() -> None:
    report = check_profile_data(profile_data())

    assert report.summary is not None
    assert report.summary["nest_clearance_mm"] == pytest.approx(0.25)
    assert report.summary["foot_height_mm"] == 4.75
    assert report.summary["lip_height_mm"] == 4.4


def test_a_section_is_read_between_its_points() -> None:
    foot = ((2.95, 0.0), (2.15, 0.8), (2.15, 2.6), (0.0, 4.75))

    assert inset_at(foot, 0.0) == 2.95
    assert inset_at(foot, 0.4) == pytest.approx(2.55)
    assert inset_at(foot, 3.0) == pytest.approx(1.75)
    assert inset_at(foot, 9.0) == 0.0
    assert nest_clearance_mm(foot, ((1.0, 0.0), (0.0, 1.0))) == pytest.approx(1.95)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source": ""}, "source must say where the figures came from"),
        ({"file_kind": "stack"}, "file_kind must be"),
        ({"colour": "red"}, "Unknown field"),
        ({"pitch_mm": 2}, "pitch_mm"),
        ({"foot": [[2.0, 0.5], [0.0, 3.0]]}, "foot must start at height 0"),
        ({"foot": [[2.0, 0.0], [1.0, 3.0]]}, "foot must end at inset 0"),
        ({"foot": [[2.0, 0.0], [3.0, 1.0], [0.0, 3.0]]}, "move back in"),
        ({"foot": [[3.0, 0.0], [0.0, 1.0]]}, "leans more than 45 degrees"),
        ({"foot": [[2.0, 0.0], [0.0, 0.0]]}, "heights must rise"),
        ({"foot": "tall"}, "foot must be a list"),
        ({"foot": [[2.0, 0.0], ["x", 1.0]]}, "foot[1] must be"),
        ({"corner_radius_mm": 3.0}, "bottom corner"),
        ({"min_nest_clearance_mm": 0.5}, "under the 0.5 mm"),
        ({"needs_review": "unchecked"}, "not reviewed"),
    ],
)
def test_a_profile_that_cannot_be_right_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    report = check_profile_data(profile_data(**changes))

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_foot_that_stands_outside_its_lip_is_refused() -> None:
    wide = [[1.0, 0.0], [1.0, 1.0], [0.0, 2.0]]
    report = check_profile_data(profile_data(foot=wide))

    assert not report.valid
    assert any("does not fit in the lip" in e for e in report.errors), report.errors


# --- the stack file -----------------------------------------------------------------------------


def stack_data(items: list[dict[str, Any]]) -> dict[str, Any]:
    data = stack_template()
    data["items"] = items

    return data


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "at least one item"),
        (["bin"], "items[0] must be an object"),
        ([{"kind": "crate", "name": "a", "cells": [1, 1]}], "kind must be one of"),
        ([{"kind": "bin", "name": "a", "cells": [1.5, 1], "units": 1}], "whole number"),
        ([{"kind": "bin", "name": "a", "cells": [1], "units": 1}], "[across, deep]"),
        ([{"kind": "bin", "name": "a", "cells": [1, 1], "units": 0}], "units"),
        ([{"kind": "bin", "name": "a b", "cells": [1, 1], "units": 1}], "name"),
        (
            [
                {"kind": "bin", "name": "a", "cells": [1, 1], "units": 1},
                {"kind": "baseplate", "name": "a", "cells": [1, 1]},
            ],
            "used twice",
        ),
        (
            [{"kind": "bin", "name": "a", "cells": [1, 1], "units": 1, "rim_mm": 1}],
            "unknown fields: rim_mm",
        ),
        (
            [{"kind": "bin", "name": "a", "cells": [1, 1], "units": 1, "scoop": 1}],
            "scoop must be true or false",
        ),
    ],
)
def test_a_stack_file_that_cannot_be_right_is_refused(
    items: list[Any], message: str
) -> None:
    report = check_stack_data(stack_data(items))

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_the_stack_template_is_valid_until_it_meets_a_profile(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    path = write_stack(tmp_path, profile, stack_template()["items"])
    report = check_stack_file(path, PRINTER)

    assert report.valid, report.errors
    assert report.summary is not None
    assert [i["name"] for i in report.summary["items"]] == ["parts-bin", "base"]


def test_a_stack_is_refused_if_its_profile_has_changed(tmp_path: Path) -> None:
    profile = write_profile(tmp_path)
    path = write_stack(
        tmp_path, profile, [{"kind": "baseplate", "name": "p", "cells": [1, 1]}]
    )
    profile.write_text(json.dumps(profile_data(pitch_mm=43.0)))
    report = check_stack_file(path, PRINTER)

    assert not report.valid
    assert any("has changed since the stack file named it" in e for e in report.errors)


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ({"units": 1, "wall_mm": 0.8}, "under the printer's 1.2 mm minimum wall"),
        ({"units": 1, "floor_mm": 0.8}, "under the printer's 1.2 mm minimum floor"),
        ({"units": 1, "wall_mm": 3.0}, "thicker than the 2.6 mm"),
        ({"units": 3, "cells": [1, 1], "dividers": {"x": 7}}, "compartments"),
        ({"units": 2, "label_tab": True}, "a label tab needs"),
        ({"units": 2, "scoop": True}, "a scoop needs"),
    ],
)
def test_a_bin_that_cannot_be_built_is_refused_with_why(
    tmp_path: Path, item: dict[str, Any], message: str
) -> None:
    profile = write_profile(tmp_path)
    entry = {"kind": "bin", "name": "b", "cells": [1, 1], **item}
    report = check_stack_file(write_stack(tmp_path, profile, [entry]), PRINTER)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


# --- the solids ---------------------------------------------------------------------------------


def test_a_bin_is_one_solid_that_sits_on_a_baseplate_and_stacks_on_itself(
    basic: Any,
) -> None:
    assert basic.passed, basic.checks
    assert set(basic.checks) == {
        "bin.one_solid",
        "bin.stacks_on_itself",
        "bin.sits_on_baseplate",
        "plate.one_solid",
    }
    assert "no load rating" in basic.notes[0]


def test_a_bin_is_a_cell_wide_on_its_walls_and_narrower_on_its_foot(
    basic: Any,
) -> None:
    box = workplane_shape(basic.parts["bin"]).BoundingBox()

    assert box.xlen == pytest.approx(41.5, abs=0.01)
    assert box.ylen == pytest.approx(41.5, abs=0.01)
    # Three units to the walls' tops, and the lip cut where it comes to a 0.4 mm flat.
    assert box.zlen == pytest.approx(21.0 + 4.0, abs=0.01)
    assert basic.summary["items"]["bin"]["wall_height_mm"] == 21.0
    # The foot's bottom is drawn in by 2.95 mm and the wall is a floor above it.
    bin_ = basic.parts["bin"]

    assert inside(bin_, 0.0, 0.0, 0.1)
    assert not inside(bin_, 19.0, 0.0, 0.1)
    assert inside(bin_, 19.0, 0.0, 4.5)
    assert not inside(bin_, 0.0, 0.0, 6.5)
    assert inside(bin_, 0.0, 0.0, 5.0)


def test_a_bin_has_a_lip_that_reaches_in_over_the_wall(basic: Any) -> None:
    bin_ = basic.parts["bin"]

    # The wall is 1.2 mm; the lip's base reaches in further, held by a 45 degree support.
    assert inside(bin_, 20.75 - 1.0, 0.0, 21.0 + 0.1)
    assert inside(bin_, 20.75 - 2.0, 0.0, 21.0 + 0.1)
    assert not inside(bin_, 20.75 - 3.0, 0.0, 21.0 + 0.1)
    assert not inside(bin_, 20.75 - 1.0, 0.0, 21.0 + 4.2)
    assert not inside(bin_, 0.0, 0.0, 21.0 + 0.5)


def test_a_baseplate_has_a_pocket_for_each_cell_and_a_ridge_between(
    tmp_path: Path,
) -> None:
    stack = build(tmp_path, [{"kind": "baseplate", "name": "plate", "cells": [2, 1]}])
    plate = stack.parts["plate"]
    box = workplane_shape(plate).BoundingBox()

    assert stack.passed, stack.checks
    assert box.xlen == pytest.approx(2 * 42.0 + 2.4, abs=0.01)
    assert box.zlen == pytest.approx(1.2 + 4.35, abs=0.01)
    # A floor under each pocket, the ridge between them, and the rim round.
    assert inside(plate, -21.0, 0.0, 0.6)
    assert not inside(plate, -21.0, 0.0, 3.0)
    assert not inside(plate, 21.0, 0.0, 3.0)
    assert inside(plate, 0.0, 0.0, 3.0)
    assert inside(plate, 0.0, 0.0, 5.4)
    assert not inside(plate, 0.0, 0.0, 5.7)
    assert inside(plate, 42.5, 0.0, 2.0)


def test_a_bin_sunk_into_the_ridges_is_caught_as_an_overlap(tmp_path: Path) -> None:
    from zcad_core.geometry.intersection import intersection_volume

    stack = build(
        tmp_path,
        [
            {"kind": "bin", "name": "bin", "cells": [1, 1], "units": 2},
            {"kind": "baseplate", "name": "plate", "cells": [1, 1]},
        ],
    )
    bin_, plate = stack.parts["bin"], stack.parts["plate"]
    seated = intersection_volume(
        workplane_shape(bin_.translate((0, 0, 1.2))), workplane_shape(plate)
    )
    sunk = intersection_volume(
        workplane_shape(bin_.translate((0, 0, 0.2))), workplane_shape(plate)
    )

    assert seated < 1e-3
    assert sunk > 100.0


def test_dividers_a_label_tab_and_a_scoop_are_built(tmp_path: Path) -> None:
    stack = build(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "bin",
                "cells": [2, 2],
                "units": 5,
                "dividers": {"x": 1, "y": 1},
                "label_tab": True,
                "scoop": True,
            }
        ],
    )
    bin_ = stack.parts["bin"]

    assert stack.passed, stack.checks
    assert stack.summary["items"]["bin"]["dividers"] == {"x": 1, "y": 1}
    # A divider across each way, at the middle, standing up to the walls' tops.
    assert inside(bin_, 0.0, 20.0, 20.0)
    assert inside(bin_, 20.0, 0.0, 20.0)
    assert not inside(bin_, 20.0, 20.0, 20.0)
    # The label tab is a ledge on the back wall's inside, and the scoop fills the front
    # edge of the floor.
    assert inside(bin_, 20.0, 33.8, 32.5)
    assert inside(bin_, 20.0, -(41.0 - 1.2) + 1.0, 4.75 + 1.2 + 0.5)
    assert not inside(bin_, 20.0, -(41.0 - 1.2) + 9.5, 4.75 + 1.2 + 0.5 + 8.0)


def test_a_baseplate_too_big_for_the_bed_is_refused_with_its_cells(
    tmp_path: Path,
) -> None:
    stack = build(tmp_path, [{"kind": "baseplate", "name": "plate", "cells": [5, 1]}])

    with pytest.raises(ValueError, match="takes about 4 cells across"):
        require_fits_bed(stack, PRINTER)


def test_a_stack_names_its_profile_by_hash_and_refuses_a_changed_one(
    tmp_path: Path,
) -> None:
    profile = write_profile(tmp_path)
    path = write_stack(
        tmp_path, profile, [{"kind": "baseplate", "name": "p", "cells": [1, 1]}]
    )
    spec = load_stack(path)

    assert load_profile(profile).sha256 == spec.profile_sha256
    assert copy.deepcopy(spec.items)[0].cells == (1, 1)


# --- the commands -------------------------------------------------------------------------------


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def test_the_commands_write_check_and_build_a_stack(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    code, _ = run(
        "stack", "template", "--kind", "stack-profile", "--output", str(profile)
    )
    data = json.loads(profile.read_text())
    data["source"] = SOURCE
    profile.write_text(json.dumps(data))

    assert code == 0
    code, report = run("stack", "check", str(profile))

    assert code == 0 and report["valid"] is True
    assert report["profile"]["nest_clearance_mm"] == pytest.approx(0.25)
    stack = tmp_path / "stack.json"
    code, _ = run(
        "stack",
        "template",
        "--kind",
        "stack",
        "--profile-file",
        str(profile),
        "--output",
        str(stack),
    )
    stack_data_ = json.loads(stack.read_text())
    stack_data_["items"] = [
        {"kind": "bin", "name": "bin", "cells": [1, 1], "units": 2},
        {"kind": "baseplate", "name": "plate", "cells": [1, 1]},
    ]
    stack.write_text(json.dumps(stack_data_))
    code, report = run("stack", "check", str(stack))

    assert code == 0 and report["valid"] is True
    code, built = run(
        "stack",
        "build",
        "--stack-file",
        str(stack),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0
    assert built["validation_status"] == "PASS"
    assert set(built["parts"]) == {"bin", "plate"}
    assert all(built["checks"].values())
    assert "no load rating" in built["not_claimed"][0]


def test_the_check_command_exits_1_for_a_profile_it_cannot_use(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile_template()))
    code, report = run("stack", "check", str(path))

    assert code == 1 and report["valid"] is False


# --- holding ------------------------------------------------------------------------------------


def holding_items(**changes: Any) -> list[dict[str, Any]]:
    return [
        {"kind": "bin", "name": "bin", "cells": [1, 1], "units": 2, **changes},
        {
            "kind": "baseplate",
            "name": "plate",
            "cells": [1, 1],
            "floor_mm": 3.5,
            **changes,
        },
    ]


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ("corner", "holding_points must be a list"),
        ([[1.0]], "holding_points[0] must be [x, y]"),
        ([[30.0, 0.0]], "outside the cell"),
        ([[13.0, 13.0], [13.0, 11.0]], "under 5 mm apart"),
        ([[float(i), 0.0] for i in range(17)], "up to 16"),
    ],
)
def test_holding_points_that_cannot_be_right_are_refused(
    points: Any, message: str
) -> None:
    report = check_profile_data(profile_data(holding_points=points))

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"holding": "glue"}, "holding must be one of"),
        ({"holding": "magnet"}, "must name a catalogued magnet"),
        ({"holding": "magnet", "magnet": "D99X9"}, "must name a catalogued magnet"),
        ({"holding": "bolt"}, "must name a catalogued fastener"),
        ({"holding": "lip", "magnet": "D6X2"}, "magnets only"),
        ({"holding": "magnet", "magnet": "D6X2", "fastener": "M2"}, "bolts only"),
    ],
)
def test_a_holding_that_names_nothing_real_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    entry = {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2, **changes}
    report = check_stack_data(stack_data([entry]))

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_holding_needs_the_profile_to_have_points(tmp_path: Path) -> None:
    profile = write_profile(tmp_path, holding_points=[])
    entry = {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2}
    path = write_stack(
        tmp_path, profile, [{**entry, "holding": "magnet", "magnet": "D6X2"}]
    )
    report = check_stack_file(path, PRINTER)

    assert not report.valid
    assert any("needs holding_points in the profile" in e for e in report.errors)


def check(tmp_path: Path, items: list[dict[str, Any]], **profile: Any) -> Any:
    path = write_stack(tmp_path, write_profile(tmp_path, **profile), items)

    return check_stack_file(path, PRINTER)


MAGNET_PLATE = {
    "kind": "baseplate",
    "name": "p",
    "cells": [1, 1],
    "holding": "magnet",
    "magnet": "D6X2",
}
BOLT_BIN = {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2, "holding": "bolt"}


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([MAGNET_PLATE], "floor_mm must be at least 3.3"),
        ([{**BOLT_BIN, "fastener": "M3"}], "leaving -0.25 mm"),
        ([{**BOLT_BIN, "fastener": "M2.5"}], "leaving 0.75 mm"),
    ],
)
def test_a_holding_that_would_break_through_is_refused_with_why(
    tmp_path: Path, items: list[dict[str, Any]], message: str
) -> None:
    report = check(tmp_path, items)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_pocket_too_near_the_edge_of_the_foot_is_refused(tmp_path: Path) -> None:
    entry = {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2}
    report = check(
        tmp_path,
        [{**entry, "holding": "magnet", "magnet": "D6X2"}],
        holding_points=[[16.0, 0.0]],
    )

    assert not report.valid
    assert any("of the edge of the foot's bottom" in e for e in report.errors)


def test_magnet_pockets_are_cut_in_the_foot_and_the_baseplate_floor(
    tmp_path: Path,
) -> None:
    stack = build(tmp_path, holding_items(holding="magnet", magnet="D6X2"))
    bin_, plate = stack.parts["bin"], stack.parts["plate"]

    assert stack.passed, stack.checks
    assert stack.checks["bin.holding_points_open"]
    assert stack.checks["plate.holding_points_open"]
    summary = stack.summary["items"]["bin"]
    assert summary["holding"] == "magnet" and summary["holding_part"] == "D6X2"
    assert summary["pocket_diameter_mm"] == pytest.approx(6.3)
    assert summary["pocket_depth_mm"] == pytest.approx(2.1)
    # A pocket in the foot's bottom at each corner, solid between them and above.
    assert not inside(bin_, 13.0, 13.0, 1.0)
    assert not inside(bin_, -13.0, 13.0, 2.0)
    assert inside(bin_, 13.0, 13.0, 2.5)
    assert inside(bin_, 0.0, 0.0, 1.0)
    # And one sunk into the baseplate's floor from the pocket floor.
    assert not inside(plate, 13.0, -13.0, 3.5 - 1.0)
    assert inside(plate, 13.0, -13.0, 3.5 - 2.5)
    assert inside(plate, 0.0, 0.0, 1.0)


def test_a_bolt_is_an_insert_pocket_in_the_foot_and_a_hole_through_the_floor(
    tmp_path: Path,
) -> None:
    stack = build(tmp_path, holding_items(holding="bolt", fastener="M2"))
    bin_, plate = stack.parts["bin"], stack.parts["plate"]
    summary = stack.summary["items"]["plate"]

    assert stack.passed, stack.checks
    assert summary["holding_part"] == "M2"
    assert summary["pocket_diameter_mm"] == pytest.approx(3.2)
    assert summary["pocket_depth_mm"] == pytest.approx(3.0)
    # A screw passes the floor and reaches the insert's depth.
    assert summary["screw_length_at_least_mm"] == pytest.approx(3.5 + 3.0)
    assert not inside(bin_, 13.0, 13.0, 1.5)
    assert inside(bin_, 13.0, 13.0, 3.5)
    assert not inside(plate, 13.0, 13.0, 0.5)
    assert not inside(plate, -13.0, -13.0, 3.0)
    assert inside(plate, 0.0, 0.0, 1.0)


# --- check-stack --------------------------------------------------------------------------------


def two_files(
    tmp_path: Path,
    upper: dict[str, Any],
    lower: dict[str, Any],
    **profile: Any,
) -> tuple[Path, Path]:
    profile_path = write_profile(tmp_path, **profile)
    paths = []

    for name, item in (("upper", upper), ("lower", lower)):
        path = tmp_path / f"{name}.json"
        data = stack_template(profile_path)
        data["source"] = "a stack for tests"
        data["items"] = [item]
        path.write_text(json.dumps(data))
        paths.append(path)

    return paths[0], paths[1]


BIN = {"kind": "bin", "name": "up", "cells": [1, 1], "units": 2}
PLATE = {"kind": "baseplate", "name": "down", "cells": [2, 2], "floor_mm": 3.5}


def stackable(upper: Path, lower: Path, up: str, down: str) -> Any:
    return check_stackable(upper, up, lower, down, PRINTER)


def test_a_bin_stacks_on_a_baseplate_that_holds_it_the_same_way(
    tmp_path: Path,
) -> None:
    magnet = {"holding": "magnet", "magnet": "D6X2"}
    upper, lower = two_files(tmp_path, {**BIN, **magnet}, {**PLATE, **magnet})
    report = stackable(upper, lower, "up", "down")

    assert report.stacks, report.errors
    assert report.summary["held_by"] == "magnet (D6X2)"
    assert report.summary["stack_height_mm"] == pytest.approx(3.5 + 14.0 + 4.0)
    assert "no load rating" in report.summary["not_claimed"]


def test_a_bin_and_a_baseplate_that_hold_differently_are_named(tmp_path: Path) -> None:
    upper, lower = two_files(
        tmp_path,
        {**BIN, "holding": "magnet", "magnet": "D6X2"},
        {**PLATE, "holding": "bolt", "fastener": "M2"},
    )
    report = stackable(upper, lower, "up", "down")

    assert not report.stacks
    assert any("disagree on what holds them" in e for e in report.errors)
    assert any("magnet (D6X2)" in e and "bolt (M2)" in e for e in report.errors)


def test_a_bin_holding_by_magnet_on_a_plain_baseplate_is_refused(
    tmp_path: Path,
) -> None:
    upper, lower = two_files(
        tmp_path, {**BIN, "holding": "magnet", "magnet": "D6X2"}, PLATE
    )
    report = stackable(upper, lower, "up", "down")

    assert not report.stacks
    assert any("the lip alone" in e for e in report.errors)


def test_two_bins_stack_by_their_lips_and_a_foot_pocket_meets_nothing(
    tmp_path: Path,
) -> None:
    upper, lower = two_files(
        tmp_path,
        {**BIN, "holding": "magnet", "magnet": "D6X2"},
        {**BIN, "name": "down"},
    )
    report = stackable(upper, lower, "up", "down")

    assert report.stacks, report.errors
    assert report.summary["held_by"] == "the lip alone"
    assert any("meets nothing" in w for w in report.warnings)


@pytest.mark.parametrize(
    ("upper", "lower", "message"),
    [
        (BIN, {**BIN, "name": "down", "cells": [2, 1]}, "bin of the same cells"),
        (PLATE | {"name": "up"}, PLATE, "is a baseplate"),
        ({**BIN, "cells": [3, 1]}, PLATE, "more than the 2 x 2"),
    ],
)
def test_items_that_cannot_stack_say_why(
    tmp_path: Path, upper: dict[str, Any], lower: dict[str, Any], message: str
) -> None:
    up, down = two_files(tmp_path, upper, lower)
    report = stackable(up, down, upper["name"], lower["name"])

    assert not report.stacks
    assert any(message in e for e in report.errors), report.errors


def test_items_on_different_profiles_do_not_stack(tmp_path: Path) -> None:
    upper, _ = two_files(tmp_path, BIN, PLATE)
    other = tmp_path / "other"
    other.mkdir()
    _, lower = two_files(other, BIN, PLATE, min_nest_clearance_mm=0.2)
    report = stackable(upper, lower, "up", "down")

    assert not report.stacks
    assert any("different profiles" in e for e in report.errors)


def test_a_missing_item_is_named(tmp_path: Path) -> None:
    upper, lower = two_files(tmp_path, BIN, PLATE)

    with pytest.raises(ValueError, match="has no item 'nope'"):
        stackable(upper, lower, "nope", "down")


def test_the_check_stack_command_exits_1_when_items_do_not_stack(
    tmp_path: Path,
) -> None:
    upper, lower = two_files(
        tmp_path, {**BIN, "holding": "magnet", "magnet": "D6X2"}, PLATE
    )
    code, report = run(
        "stack", "check-stack", "--upper", f"{upper}:up", "--lower", f"{lower}:down"
    )

    assert code == 1 and report["stacks"] is False

    other = tmp_path / "fine"
    other.mkdir()
    upper, lower = two_files(other, BIN, PLATE)
    code, report = run(
        "stack", "check-stack", "--upper", f"{upper}:up", "--lower", f"{lower}:down"
    )

    assert code == 0 and report["stacks"] is True

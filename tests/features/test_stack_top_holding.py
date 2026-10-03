"""A stack top that holds what stands on it: magnets in its pockets, keepers in their walls."""

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
from zcad_core.features.enclosure_group_model import GroupDesign
from zcad_core.features.mount_stack import (
    TopHolding,
    build_stack_top,
    check_top_holding,
    magnet_points,
)
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_holding import holding_for
from zcad_core.features.stack_profile import load_profile, profile_template
from zcad_core.hardware import get_fastener

SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
M3 = get_fastener("M3")
LID_TOP = 8.0
# Screws that sit in the pocket floors of a 1 x 2 plate, clear of the magnet pockets 13 mm out.
SCREWS = [(-6.0, -31.0), (6.0, -31.0), (-6.0, 31.0), (6.0, 31.0)]


def write_profile(directory: Path) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def top_for(tmp_path: Path, holding: TopHolding | None = None, **changes: Any) -> Any:
    profile = load_profile(write_profile(tmp_path))

    return build_stack_top(
        changes.get("positions", SCREWS),
        centre=(0.0, 0.0),
        lid_size_mm=(36.0, 80.0),
        lid_top_z_mm=LID_TOP,
        lid_mm=2.0,
        fastener=M3,
        profile=profile,
        compensation=0.0,
        holding=holding,
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


# --- the options --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "magnet", "latch", "engagement", "top", "message"),
    [
        ("bolt", None, (), None, True, "a bolt would go through the lid"),
        ("magnet", None, (), None, True, "must name a catalogued magnet"),
        ("magnet", "D99X9", (), None, True, "must name a catalogued magnet"),
        ("lip", "D6X2", (), None, True, "is for holding by magnets only"),
        ("lip", None, ("top",), None, True, "different sides"),
        ("lip", None, ("front", "front"), None, True, "different sides"),
        ("lip", None, ("front",), 9.0, True, "outside 0.1 to 1.5"),
        ("lip", None, (), 0.4, True, "is for a latch"),
        ("magnet", "D6X2", (), None, False, "are options of a stack top"),
        ("lip", None, ("front",), None, False, "are options of a stack top"),
    ],
)
def test_options_that_do_not_go_together_are_refused(
    kind: str,
    magnet: str | None,
    latch: tuple[str, ...],
    engagement: float | None,
    top: bool,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        check_top_holding(kind, magnet, latch, engagement, top)


def test_the_designs_carry_the_options_and_check_them() -> None:
    design = EnclosureDesign(
        stack_top=True,
        stack_profile="p.json",
        stack_top_holding="magnet",
        stack_top_magnet="D6X2",
        stack_top_latch="front,back",
    )
    design.validate()
    GroupDesign(
        stack_top=True,
        stack_profile="p.json",
        stack_top_holding="magnet",
        stack_top_magnet="D6X2",
    ).validate()

    with pytest.raises(ValueError, match="are options of a stack top"):
        EnclosureDesign(stack_top_holding="magnet", stack_top_magnet="D6X2").validate()

    with pytest.raises(ValueError, match="a bolt"):
        GroupDesign(
            stack_top=True, stack_profile="p.json", stack_top_holding="bolt"
        ).validate()


# --- the plate ----------------------------------------------------------------------------------


def test_a_magnet_top_has_a_pocket_sunk_in_each_floor_with_floor_left_under_it(
    tmp_path: Path,
) -> None:
    top = top_for(tmp_path, TopHolding("magnet", "D6X2"))
    magnet = holding_for("magnet", "D6X2", "")
    floor_top = LID_TOP + top.floor_mm
    cx, cy = 13.0, 21.0 + 13.0

    assert top.cells == (1, 2)
    assert not inside(top.plate, cx, cy, floor_top - magnet.pocket_depth_mm / 2)
    assert inside(top.plate, cx, cy, floor_top - magnet.pocket_depth_mm - 0.5)
    assert top.stack["holding"] == "magnet" and top.stack["magnet"] == "D6X2"
    assert top.stack["pocket_depth_mm"] == pytest.approx(magnet.pocket_depth_mm)


def test_a_lip_top_has_no_magnet_pockets(tmp_path: Path) -> None:
    top = top_for(tmp_path)
    floor_top = LID_TOP + top.floor_mm

    assert inside(top.plate, 13.0, 34.0, floor_top - 1.0)
    assert top.stack["holding"] == "lip" and top.stack["magnet"] == ""
    assert top.stack["latch_sides"] == []


def test_a_magnet_pocket_is_left_out_where_a_screws_recess_would_meet_it(
    tmp_path: Path,
) -> None:
    profile = load_profile(write_profile(tmp_path))
    magnet = holding_for("magnet", "D6X2", "")

    # A screw on a holding point takes that point's pocket; one far from them takes none.
    kept, skipped = magnet_points([(13.0, 13.0)], (1, 1), profile, 3.05, magnet)

    assert (13.0, 13.0) in skipped and len(kept) == 3
    kept, skipped = magnet_points([(0.0, 0.0)], (1, 1), profile, 3.05, magnet)

    assert skipped == [] and len(kept) == 4


def test_the_tops_record_names_the_magnet_points_and_those_left_out(
    tmp_path: Path,
) -> None:
    # Screws near two corners of the far cell: its two corner points are left out.
    screws = [(-10.9, -32.9), (10.9, -32.9), (-10.9, 32.9), (10.9, 32.9)]
    top = top_for(tmp_path, TopHolding("magnet", "D6X2"), positions=screws)

    assert top.cells == (1, 2)
    assert len(top.stack["magnet_points"]) == 4
    assert len(top.stack["magnet_points_left_out"]) == 4
    assert [13.0, 34.0] in top.stack["magnet_points_left_out"] or [
        13.0,
        -34.0,
    ] in top.stack["magnet_points_left_out"]
    # A pocket is sunk at a kept point and none at a left-out one.
    floor_top = LID_TOP + top.floor_mm
    x, y = top.stack["magnet_points"][0]
    left_x, left_y = top.stack["magnet_points_left_out"][0]

    assert not inside(top.plate, x, y, floor_top - 1.0)
    # A point on the far side of a left-out point, off the screw's recess but inside where its
    # pocket would be, is solid: the pocket was not cut. (The point itself is in the recess.)
    away = (
        left_x + 2.5 * (1 if left_x > 0 else -1),
        left_y + 1.5 * (1 if left_y > 0 else -1),
    )

    assert inside(top.plate, away[0], away[1], floor_top - 1.0)


def test_a_top_with_no_room_for_a_magnet_anywhere_is_refused(tmp_path: Path) -> None:
    data = profile_template()
    data["source"] = SOURCE
    data["holding_points"] = [[13.0, 13.0]]
    path = tmp_path / "one.json"
    path.write_text(json.dumps(data))
    profile = load_profile(path)

    with pytest.raises(ValueError, match="fits nowhere"):
        build_stack_top(
            [(13.0, 13.0)],
            centre=(0.0, 0.0),
            lid_size_mm=(36.0, 36.0),
            lid_top_z_mm=LID_TOP,
            lid_mm=2.0,
            fastener=M3,
            profile=profile,
            compensation=0.0,
            holding=TopHolding("magnet", "D6X2"),
        )


def test_a_profile_with_no_holding_points_cannot_hold_by_magnets(
    tmp_path: Path,
) -> None:
    data = profile_template()
    data["source"] = SOURCE
    data["holding_points"] = []
    path = tmp_path / "bare.json"
    path.write_text(json.dumps(data))
    profile = load_profile(path)

    with pytest.raises(ValueError, match="needs holding_points"):
        build_stack_top(
            SCREWS,
            centre=(0.0, 0.0),
            lid_size_mm=(36.0, 80.0),
            lid_top_z_mm=LID_TOP,
            lid_mm=2.0,
            fastener=M3,
            profile=profile,
            compensation=0.0,
            holding=TopHolding("magnet", "D6X2"),
        )


def test_latch_keepers_are_cut_in_the_pocket_walls_and_recorded(tmp_path: Path) -> None:
    plain = top_for(tmp_path)
    latched = top_for(tmp_path, TopHolding(latch_sides=("front", "back")))

    assert latched.plate.val().Volume() < plain.plate.val().Volume()
    assert latched.stack["latch_sides"] == ["front", "back"]
    assert latched.stack["latch_engagement_mm"] == pytest.approx(0.4)
    assert latched.stack["holding"] == "lip"


def test_a_latch_the_profile_cannot_carry_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be built with a latch"):
        top_for(tmp_path, TopHolding(latch_sides=("front",), engagement_mm=0.5))


# --- the enclosure and check-stack --------------------------------------------------------------


def build_pico(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any], Path]:
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--stack-top",
        "--stack-profile",
        str(write_profile(tmp_path)),
        "--output-directory",
        str(tmp_path / "pico"),
        *extra,
    )

    return code, built, tmp_path / "pico" / "enclosure.json"


def write_stack_file(directory: Path, items: list[dict[str, Any]]) -> Path:
    data = stack_template(directory / "profile.json")
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def check(upper: str, lower: str) -> tuple[int, dict[str, Any]]:
    return run("stack", "check-stack", "--upper", upper, "--lower", lower)


def test_an_enclosure_builds_a_top_held_by_magnets_and_latches(tmp_path: Path) -> None:
    code, built, record = build_pico(
        tmp_path,
        "--stack-top-holding",
        "magnet",
        "--stack-top-magnet",
        "D6X2",
        "--stack-top-latch",
        "front,back",
    )

    assert code == 0 and built["validation_status"] == "PASS"
    stack = json.loads(record.read_text())["stack_top"]

    assert stack["holding"] == "magnet" and stack["magnet"] == "D6X2"
    assert stack["latch_sides"] == ["front", "back"]
    assert stack["latch_engagement_mm"] == pytest.approx(0.4)
    assert built["stack_top"]["stack"]["holding"] == "magnet"


def test_bins_must_agree_with_the_tops_magnets_and_latches(tmp_path: Path) -> None:
    _, _, record = build_pico(
        tmp_path,
        "--stack-top-holding",
        "magnet",
        "--stack-top-magnet",
        "D6X2",
        "--stack-top-latch",
        "front,back",
    )
    latch = {"sides": ["front", "back"]}
    stack = write_stack_file(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "held",
                "cells": [1, 2],
                "units": 2,
                "holding": "magnet",
                "magnet": "D6X2",
                "latch": latch,
            },
            {"kind": "bin", "name": "loose", "cells": [1, 2], "units": 2},
            {
                "kind": "bin",
                "name": "magnets-only",
                "cells": [1, 2],
                "units": 2,
                "holding": "magnet",
                "magnet": "D6X2",
            },
            {
                "kind": "bin",
                "name": "front-only",
                "cells": [1, 2],
                "units": 2,
                "holding": "magnet",
                "magnet": "D6X2",
                "latch": {"sides": ["left"]},
            },
        ],
    )
    code, report = check(f"{stack}:held", f"{record}:top")

    assert code == 0 and report["stacks"] is True, report
    code, report = check(f"{stack}:loose", f"{record}:top")
    assert code == 1 and any(
        "disagree on what holds them" in e for e in report["errors"]
    )
    code, report = check(f"{stack}:magnets-only", f"{record}:top")
    assert code == 0 and report["stacks"] is True
    code, report = check(f"{stack}:front-only", f"{record}:top")
    assert code == 1 and any("no keeper there" in e for e in report["errors"])


def test_a_bolt_is_not_a_choice_at_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        build_pico(tmp_path, "--stack-top-holding", "bolt")

    assert "invalid choice" in capsys.readouterr().err


def test_options_without_a_stack_top_are_refused_at_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--stack-top-latch",
        "front",
        "--output-directory",
        str(tmp_path / "plain"),
    )

    assert code == 1 and "are options of a stack top" in capsys.readouterr().err


def test_a_group_builds_a_top_held_by_magnets(tmp_path: Path) -> None:
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        "pi5",
        "--stack-top",
        "--no-vents",
        "--stack-profile",
        str(write_profile(tmp_path)),
        "--stack-top-holding",
        "magnet",
        "--stack-top-magnet",
        "D6X2",
        "--stack-top-latch",
        "front",
        "--output-directory",
        str(tmp_path / "group"),
    )

    assert code == 0, built
    stack = json.loads((tmp_path / "group" / "enclosure-group.json").read_text())[
        "stack_top"
    ]

    assert stack["holding"] == "magnet" and stack["latch_sides"] == ["front"]
    assert (
        "stack_top_holds"
        in json.loads((tmp_path / "group" / "enclosure-group.json").read_text())[
            "checks"
        ]
    )


def test_a_holding_top_asks_for_a_check_a_lip_top_does_not(tmp_path: Path) -> None:
    _, _, held = build_pico(
        tmp_path,
        "--stack-top-holding",
        "magnet",
        "--stack-top-magnet",
        "D6X2",
    )
    lip_dir = tmp_path / "lip"
    lip_dir.mkdir()
    _, _, lip = build_pico(lip_dir)

    assert "stack_top_holds" in json.loads(held.read_text())["checks"]
    assert "stack_top_holds" not in json.loads(lip.read_text())["checks"]

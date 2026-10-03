"""A drawer that clicks shut: a bump on a tongue in each side wall, a dimple in the frame's."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from zcad_core.features.stack import (
    build_item,
    build_stack,
    detent_plan_for,
    frame_plan,
    overlap_mm3,
)
from zcad_core.features.stack_detent import bump_solid, plan_detent
from zcad_core.features.stack_file import (
    check_stack_data,
    check_stack_file,
    load_stack,
    stack_template,
)
from zcad_core.features.stack_profile import load_profile, profile_template
from zcad_core.features.stack_trial import item_from_record, item_record
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"


def write_stack(directory: Path, items: list[dict[str, Any]]) -> Path:
    profile = profile_template()
    profile["source"] = SOURCE
    (directory / "profile.json").write_text(json.dumps(profile))
    data = stack_template(directory / "profile.json")
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def chest(**changes: Any) -> dict[str, Any]:
    return {
        "kind": "frame",
        "name": "chest",
        "cells": [1, 1],
        "units": 4,
        "drawers": 2,
        "wall_mm": 1.8,
        "detent": {},
        **changes,
    }


def tray(**changes: Any) -> dict[str, Any]:
    return {"kind": "drawer", "name": "tray", "frame": "chest", "detent": {}, **changes}


@pytest.fixture(scope="module")
def clicking(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("clicking")
    path = write_stack(directory, [chest(), tray()])

    return build_stack(load_stack(path), PRINTER)


# --- the plan -----------------------------------------------------------------------------------


def detent_for(
    directory: Path, items: list[dict[str, Any]], engagement: float | None = None
) -> Any:
    path = write_stack(directory, items)
    spec = load_stack(path)
    profile = load_profile(spec.profile_path)
    frame = next(item for item in spec.items if item.kind == "frame")
    drawer = next(item for item in spec.items if item.kind == "drawer")
    plan = frame_plan(frame, profile, 0.2, drawer)

    return plan_detent(plan, frame.wall_mm, engagement or 0.4, 1.2, 0.2)


def test_the_default_detent_sizes_from_the_example_profile(tmp_path: Path) -> None:
    detent, errors = detent_for(tmp_path, [chest(), tray()])

    assert detent is not None and errors == []
    assert detent.protrusion_mm == pytest.approx(0.6)
    assert detent.dimple_depth_mm == pytest.approx(0.6)
    assert detent.base_mm == pytest.approx(1.6)
    assert detent.reach_mm == pytest.approx(7.0)
    assert detent.strain <= 0.015


def test_the_bump_and_dimple_do_not_depend_on_the_drawers_own_wall(
    tmp_path: Path,
) -> None:
    thin, _ = detent_for(tmp_path, [chest(), tray()])
    thick, _ = detent_for(tmp_path, [chest(), tray(wall_mm=2.0)])

    assert thin is not None and thick is not None
    assert thick.y_bump_mm == pytest.approx(thin.y_bump_mm)
    assert thick.z_bump_mm == pytest.approx(thin.z_bump_mm)
    # A thicker wall is a stiffer tongue and needs a longer one for the same strain.
    assert thick.length_mm > thin.length_mm


@pytest.mark.parametrize(
    ("items", "engagement", "message"),
    [
        ([chest(), tray()], 0.2, "under the least the engine builds"),
        (
            [chest(wall_mm=1.2), tray()],
            None,
            "the frame's wall_mm must be at least 1.80 mm",
        ),
        (
            [chest(units=4, drawers=3), tray()],
            None,
            "needs 5.3 mm of side wall above its floor",
        ),
        ([chest(), tray(wall_mm=5.0)], None, "its back wall and margin need"),
    ],
)
def test_a_detent_the_frame_or_drawer_cannot_carry_is_refused(
    tmp_path: Path, items: list[dict[str, Any]], engagement: float | None, message: str
) -> None:
    detent, errors = detent_for(tmp_path, items, engagement)

    assert detent is None and any(message in e for e in errors), errors


# --- the file -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("detent", "message"),
    [
        (1, "detent must be an object"),
        ({"colour": 1}, "detent has unknown fields: colour"),
        ({"engagement_mm": 9.0}, "detent.engagement_mm"),
    ],
)
def test_a_bad_detent_field_is_refused(detent: Any, message: str) -> None:
    data = stack_template()
    data["items"] = [
        {
            "kind": "frame",
            "name": "f",
            "cells": [1, 1],
            "units": 4,
            "drawers": 1,
            "detent": detent,
        }
    ]
    report = check_stack_data(data)

    assert any(message in e for e in report.errors), report.errors


def test_a_bin_takes_no_detent() -> None:
    data = stack_template()
    data["items"] = [
        {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2, "detent": {}}
    ]

    assert any("unknown fields: detent" in e for e in check_stack_data(data).errors)


def test_a_drawer_with_bumps_needs_a_frame_with_dimples(tmp_path: Path) -> None:
    path = write_stack(tmp_path, [chest(detent=None), tray()])
    data = json.loads(path.read_text())
    data["items"][0].pop("detent")
    path.write_text(json.dumps(data))
    report = check_stack_file(path, PRINTER)

    assert not report.valid
    assert any("has no detent: add detent to the frame" in e for e in report.errors)


def test_a_drawer_and_frame_that_disagree_on_engagement_are_refused(
    tmp_path: Path,
) -> None:
    path = write_stack(tmp_path, [chest(), tray(detent={"engagement_mm": 0.35})])
    report = check_stack_file(path, PRINTER)

    assert not report.valid
    assert any("must agree" in e for e in report.errors), report.errors


def test_a_frame_wall_too_thin_for_a_dimple_is_refused_at_the_check(
    tmp_path: Path,
) -> None:
    report = check_stack_file(write_stack(tmp_path, [chest(wall_mm=1.2)]), PRINTER)

    assert not report.valid
    assert any(e.startswith("chest: a dimple 0.60 mm deep") for e in report.errors)


def test_an_item_with_a_detent_survives_a_record(tmp_path: Path) -> None:
    path = write_stack(tmp_path, [chest(detent={"engagement_mm": 0.35}), tray()])

    for item in load_stack(path).items:
        assert item_from_record(item_record(item)) == item


# --- the build ----------------------------------------------------------------------------------


def test_a_frame_and_drawer_with_a_detent_build_and_every_check_passes(
    clicking: Any,
) -> None:
    assert clicking.passed, [n for n, ok in clicking.checks.items() if not ok]

    for check in (
        "chest.detent_dimples_open",
        "tray.detent_tongues_freed",
        "tray.detent_clicks_in",
        "tray.detent_passes",
        "tray.slides_in_chest",
    ):
        assert clicking.checks[check]


def test_the_build_reports_the_detent_and_says_a_pulled_drawer_comes_out(
    clicking: Any,
) -> None:
    drawer = clicking.summary["items"]["tray"]

    assert drawer["held_by"] == "a detent: it clicks shut, and comes out when pulled"
    assert (
        drawer["detent"]["strain_percent"] <= drawer["detent"]["strain_limit_percent"]
    )
    assert "force" not in json.dumps(drawer["detent"])
    assert "dimple_depth_mm" in clicking.summary["items"]["chest"]["detent"]


def test_a_drawer_without_a_detent_is_held_by_nothing_as_before(tmp_path: Path) -> None:
    path = write_stack(tmp_path, [chest(), tray(detent=None)])
    data = json.loads(path.read_text())
    data["items"][1].pop("detent")
    path.write_text(json.dumps(data))
    stack = build_stack(load_stack(path), PRINTER)

    assert stack.passed
    assert stack.summary["items"]["tray"]["held_by"] == (
        "nothing: it comes out when pulled"
    )


def test_a_bump_pulled_out_of_its_dimple_really_strikes_the_wall(
    tmp_path: Path,
) -> None:
    path = write_stack(tmp_path, [chest(), tray()])
    spec = load_stack(path)
    profile = load_profile(spec.profile_path)
    siblings = {item.name: item for item in spec.items}
    plan = detent_plan_for(spec.items[1], profile, PRINTER, siblings)
    plain, _, _ = build_item(
        replace(spec.items[0], detent=False), profile, PRINTER, siblings
    )

    assert plan is not None
    bump = bump_solid(plan, 1)

    # Closed, the bump is where the wall would be, so it is in the dimple; pulled out by a
    # few millimetres and not pushed in, it is in the wall.
    assert overlap_mm3(bump, plain) > 0.05
    assert overlap_mm3(bump.translate((0.0, -5.0, 0.0)), plain) > 0.05

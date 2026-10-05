"""A printed snap latch between a foot and a lip: a hook on the foot, a keeper in the lip."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.features.stack import build_stack
from zcad_core.features.stack_check import check_stackable
from zcad_core.features.stack_file import check_stack_data, load_stack, stack_template
from zcad_core.features.stack_latch import (
    cells_on_side,
    clash_errors,
    engagement_for,
    foot_points,
    hook_centre_u,
    hook_solids,
    keeper_points,
    latch_window,
    plan_latch,
)
from zcad_core.features.stack_profile import (
    check_profile_data,
    load_profile,
    profile_template,
)
from zcad_core.features.stack_solids import cell_centres
from zcad_core.features.stack_trial import item_from_record, item_record
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
SIDES = {"sides": ["front", "back"]}


def write_profile(directory: Path, **changes: Any) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    data.update(changes)
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


def write_stack(directory: Path, items: list[dict[str, Any]], **changes: Any) -> Path:
    profile = write_profile(directory, **changes)
    data = stack_template(profile)
    data["source"] = "a stack for tests"
    data["items"] = items
    path = directory / "stack.json"
    path.write_text(json.dumps(data))

    return path


def plan_for(directory: Path, engagement: float = 0.4, **changes: Any) -> Any:
    profile = load_profile(write_profile(directory, **changes))

    return plan_latch(profile, engagement, 1.2, 0.2)


def inside(model: cq.Workplane, point: tuple[float, float, float]) -> bool:
    return any(
        solid.isInside(cq.Vector(*point))
        for solid in model.val().Solids()  # type: ignore[union-attr]
    )


@pytest.fixture(scope="module")
def latched(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("latched")
    items: list[dict[str, Any]] = [
        {"kind": "bin", "name": "box", "cells": [2, 1], "units": 3, "latch": SIDES},
        {"kind": "baseplate", "name": "plate", "cells": [2, 1], "latch": SIDES},
        {
            "kind": "frame",
            "name": "chest",
            "cells": [1, 1],
            "units": 4,
            "drawers": 1,
            "latch": SIDES,
        },
    ]

    return build_stack(load_stack(write_stack(directory, items)), PRINTER)


# --- the profile gives the faces ----------------------------------------------------------------


def test_the_example_profile_has_a_vertical_run_for_a_hook(tmp_path: Path) -> None:
    window = latch_window(load_profile(write_profile(tmp_path)))

    assert window is not None
    assert (window.z_low, window.z_high) == (pytest.approx(0.8), pytest.approx(2.5))
    assert window.run_mm == pytest.approx(1.7)
    assert window.gap_mm == pytest.approx(0.25)


def test_a_profile_with_no_vertical_run_cannot_carry_a_latch(tmp_path: Path) -> None:
    slope = write_profile(
        tmp_path,
        foot=[[2.95, 0.0], [0.0, 4.75]],
        lip=[[2.6, 0.0], [0.0, 4.4]],
        min_nest_clearance_mm=0.1,
    )
    plan, errors = plan_latch(load_profile(slope), 0.4, 1.2, 0.2)

    assert plan is None and "needs a vertical run of 1.5 mm" in errors[0]


# --- the sizes ----------------------------------------------------------------------------------


def test_the_default_latch_sizes_from_the_example_profile(tmp_path: Path) -> None:
    plan, errors = plan_for(tmp_path)

    assert plan is not None and errors == []
    assert plan.protrusion_mm == pytest.approx(0.65)
    # The keeper is cut the engagement and the printer's clearance past the lip's face.
    assert plan.keeper_depth_mm == pytest.approx(0.6)
    assert plan.window.run_mm - 2 * plan.protrusion_mm == pytest.approx(0.4)
    assert plan.strain <= 0.015
    assert plan.length_mm == pytest.approx(plan.reach_mm + 3.0)
    assert plan.relief_mm == pytest.approx(0.8)


def test_a_tight_baseplate_fit_bends_the_tongue_far_enough_to_pass_its_wall(
    tmp_path: Path,
) -> None:
    # The pocket wall stands 0.1 mm from the foot where the lip stands 0.25 mm, so the
    # hook, 0.65 mm out, must bend 0.55 mm to pass it, not just its 0.4 mm engagement.
    plan, errors = plan_for(tmp_path, min_nest_clearance_mm=0.1)

    assert plan is not None and errors == []
    assert plan.deflection_mm == pytest.approx(0.55)
    assert plan.strain <= 0.015
    stack = build_stack(
        load_stack(
            write_stack(
                tmp_path,
                [
                    {
                        "kind": "bin",
                        "name": "b",
                        "cells": [1, 1],
                        "units": 3,
                        "latch": SIDES,
                    }
                ],
                min_nest_clearance_mm=0.1,
            )
        ),
        PRINTER,
    )

    assert stack.checks["b.latch_hook_passes_baseplate"] is True
    assert stack.passed, stack.checks


@pytest.mark.parametrize(
    ("engagement", "message"),
    [
        (0.2, "under the least the engine builds"),
        (0.5, "the most engagement this profile's run allows is 0.40 mm"),
    ],
)
def test_an_engagement_the_profile_cannot_carry_is_refused(
    tmp_path: Path, engagement: float, message: str
) -> None:
    plan, errors = plan_for(tmp_path, engagement)

    assert plan is None and any(message in e for e in errors), errors


def test_a_lip_too_thin_to_back_a_keeper_is_refused(tmp_path: Path) -> None:
    plan, errors = plan_for(
        tmp_path,
        lip=[[2.2, 0.0], [1.5, 0.7], [1.5, 2.5], [0.0, 4.4]],
        min_nest_clearance_mm=0.25,
    )

    assert plan is None
    assert any("of the 1.5 mm lip behind it" in e for e in errors), errors


def test_a_tongue_that_cannot_fit_the_foots_side_is_refused(tmp_path: Path) -> None:
    plan, errors = plan_for(tmp_path, pitch_mm=20.0, holding_points=[])

    assert plan is None
    assert any("of straight foot to bend" in e for e in errors), errors


def test_a_tongue_near_a_holding_pocket_is_refused(tmp_path: Path) -> None:
    plan, _ = plan_for(tmp_path)

    assert plan is not None
    assert clash_errors(plan, ["back"], [(13.0, 13.0)], 4.0, 1.2) == []
    near = clash_errors(plan, ["back"], [(4.0, 17.0)], 2.0, 1.2)

    assert near and "under the printer's minimum wall" in near[0]


# --- the profile's own engagement ---------------------------------------------------------------


def test_a_profile_can_give_its_own_engagement_with_a_source(tmp_path: Path) -> None:
    path = write_profile(
        tmp_path, latch={"engagement_mm": 0.35, "source": "a trial, 12 snaps"}
    )
    profile = load_profile(path)

    assert profile.latch_engagement_mm == pytest.approx(0.35)
    assert engagement_for(None, profile) == pytest.approx(0.35)
    assert engagement_for(0.4, profile) == pytest.approx(0.4)
    assert engagement_for(None, load_profile(write_profile(tmp_path))) == 0.4


@pytest.mark.parametrize(
    ("latch", "message"),
    [
        ({"engagement_mm": 0.35}, "latch.source must say where"),
        ({"engagement_mm": 0.35, "source": "EXAMPLE only"}, "still an example"),
        ({"engagement_mm": 5.0, "source": "x"}, "latch.engagement_mm"),
        ({"source": "x"}, "latch.engagement_mm is missing"),
        ({"engagement_mm": 0.3, "source": "x", "colour": 1}, "unknown fields: colour"),
    ],
)
def test_a_bad_profile_latch_is_refused(latch: Any, message: str) -> None:
    data = profile_template()
    data["source"] = SOURCE
    data["latch"] = latch
    report = check_profile_data(data)

    assert any(message in e for e in report.errors), report.errors


# --- the stack file -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latch", "message"),
    [
        ({"sides": ["top"]}, "must be a list of different sides"),
        ({"sides": ["front", "front"]}, "must be a list of different sides"),
        ({"sides": []}, "must be a list of different sides"),
        ({"engagement_mm": 9.0}, "latch.engagement_mm"),
        ({"colour": 1}, "unknown fields: colour"),
    ],
)
def test_a_bad_latch_field_is_refused(latch: Any, message: str) -> None:
    data = stack_template()
    data["items"] = [
        {"kind": "bin", "name": "b", "cells": [1, 1], "units": 2, "latch": latch}
    ]
    report = check_stack_data(data)

    assert any(message in e for e in report.errors), report.errors


def test_a_latch_left_empty_takes_the_front_and_back(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [{"kind": "bin", "name": "b", "cells": [1, 1], "units": 2, "latch": {}}],
    )

    assert load_stack(path).items[0].latch_sides == ("front", "back")


def test_an_item_with_a_latch_survives_a_record(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "b",
                "cells": [1, 1],
                "units": 2,
                "latch": {"sides": ["left"], "engagement_mm": 0.35},
            }
        ],
    )
    item = load_stack(path).items[0]

    assert item_from_record(item_record(item)) == item


# --- the build ----------------------------------------------------------------------------------


def test_the_latched_items_build_and_every_check_passes(latched: Any) -> None:
    assert latched.passed, [name for name, ok in latched.checks.items() if not ok]

    for name in ("box", "chest"):
        for check in (
            "latch_tongues_freed",
            "latch_keepers_open",
            "latch_hook_engages",
            "latch_hook_passes",
        ):
            assert latched.checks[f"{name}.{check}"]

    assert latched.checks["box.sits_on_baseplate"]


def test_the_build_reports_the_latch_with_no_force(latched: Any) -> None:
    latch = latched.summary["items"]["box"]["latch"]

    assert latch["sides"] == ["front", "back"]
    assert latch["strain_percent"] <= latch["strain_limit_percent"]
    assert latch["keeper_depth_mm"] == pytest.approx(0.6)
    assert "force" not in json.dumps(latch)
    assert "latch" in latched.summary["items"]["plate"]


def test_a_two_cell_bin_has_a_tongue_on_each_cell_of_a_side(latched: Any) -> None:
    centres = cell_centres((2, 1), 42.0)

    assert len(cells_on_side("front", centres)) == 2
    assert len(cells_on_side("left", centres)) == 1


def test_the_foot_has_a_hook_and_a_freed_tongue_the_lip_a_keeper(
    tmp_path: Path, latched: Any
) -> None:
    profile = load_profile(write_profile(tmp_path))
    plan, _ = plan_latch(profile, 0.4, 1.2, 0.2)

    assert plan is not None
    box = latched.parts["box"]
    centre = cell_centres((2, 1), 42.0)[0]
    height = latched.summary["items"]["box"]["wall_height_mm"]
    feet = foot_points(plan, centre, "back")
    keepers = keeper_points(plan, centre, "back", height)
    # Skin solid, relief void; the keeper's mouth void and the lip behind it solid.
    assert inside(box, feet["skin"]) and not inside(box, feet["relief"])
    assert not inside(box, keepers["keeper_mouth"])
    assert inside(box, keepers["keeper_backing"])

    hooks = hook_solids(plan, cell_centres((2, 1), 42.0), "back")

    assert hooks is not None
    assert hooks.val().Volume() > 0  # type: ignore[union-attr]
    assert hook_centre_u(plan) < 0


# --- check-stack agrees on keepers --------------------------------------------------------------


def test_a_latched_bin_stacks_on_a_baseplate_that_has_keepers(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [
            {"kind": "bin", "name": "box", "cells": [1, 1], "units": 2, "latch": SIDES},
            {"kind": "baseplate", "name": "plate", "cells": [1, 1], "latch": SIDES},
        ],
    )
    report = check_stackable(path, "box", path, "plate", PRINTER)

    assert report.stacks, report.errors
    assert report.summary["latched_on"] == ["front", "back"]


def test_hooks_with_no_keepers_are_refused_with_the_side(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [
            {"kind": "bin", "name": "box", "cells": [1, 1], "units": 2, "latch": SIDES},
            {"kind": "baseplate", "name": "plate", "cells": [1, 1]},
            {"kind": "bin", "name": "plain", "cells": [1, 1], "units": 2},
            {
                "kind": "bin",
                "name": "front-only",
                "cells": [1, 1],
                "units": 2,
                "latch": {"sides": ["front"]},
            },
        ],
    )
    on_plate = check_stackable(path, "box", path, "plate", PRINTER)
    on_plain = check_stackable(path, "box", path, "plain", PRINTER)
    short = check_stackable(path, "box", path, "front-only", PRINTER)

    assert not on_plate.stacks and "front, back side" in on_plate.errors[0]
    assert not on_plain.stacks and "no keeper there" in on_plain.errors[0]
    assert not short.stacks and "back side" in short.errors[0]


def test_a_bin_stacks_on_a_latched_bin_and_keepers_alone_only_warn(
    tmp_path: Path,
) -> None:
    path = write_stack(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "upper",
                "cells": [1, 1],
                "units": 2,
                "latch": SIDES,
            },
            {
                "kind": "bin",
                "name": "lower",
                "cells": [1, 1],
                "units": 2,
                "latch": SIDES,
            },
            {"kind": "bin", "name": "plain", "cells": [1, 1], "units": 2},
        ],
    )
    both = check_stackable(path, "upper", path, "lower", PRINTER)
    keepers_only = check_stackable(path, "plain", path, "lower", PRINTER)

    assert both.stacks, both.errors
    assert keepers_only.stacks and "has no hooks" in keepers_only.warnings[0]


def test_hooks_and_keepers_that_disagree_on_engagement_are_refused(
    tmp_path: Path,
) -> None:
    path = write_stack(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "upper",
                "cells": [1, 1],
                "units": 2,
                "latch": SIDES,
            },
            {
                "kind": "bin",
                "name": "lower",
                "cells": [1, 1],
                "units": 2,
                "latch": {**SIDES, "engagement_mm": 0.35},
            },
        ],
    )
    report = check_stackable(path, "upper", path, "lower", PRINTER)

    assert not report.stacks
    assert any("must agree" in e for e in report.errors), report.errors


def test_a_latch_the_profile_cannot_carry_is_refused_at_the_check(
    tmp_path: Path,
) -> None:
    from zcad_core.features.stack_file import check_stack_file

    path = write_stack(
        tmp_path,
        [
            {
                "kind": "bin",
                "name": "b",
                "cells": [1, 1],
                "units": 2,
                "latch": {"engagement_mm": 0.5},
            }
        ],
    )
    report = check_stack_file(path, PRINTER)

    assert not report.valid
    assert any("the most engagement" in e for e in report.errors), report.errors


def test_without_a_keeper_a_hook_really_strikes_the_baseplate(tmp_path: Path) -> None:
    from zcad_core.features.stack import build_item, overlap_mm3
    from zcad_core.features.stack_solids import baseplate_solid

    path = write_stack(
        tmp_path,
        [{"kind": "bin", "name": "box", "cells": [1, 1], "units": 2, "latch": SIDES}],
    )
    spec = load_stack(path)
    profile = load_profile(spec.profile_path)
    box, _, _ = build_item(spec.items[0], profile, PRINTER)
    plate, floor = baseplate_solid(profile, (1, 1), 1.2, 1.2)

    # Two hooks, each 6 mm wide, standing 0.4 mm into the pocket's wall.
    assert overlap_mm3(box.translate((0, 0, floor)), plate) > 1.0


# --- phase 2: a cap that snaps on --------------------------------------------------------------


@pytest.fixture(scope="module")
def snapped(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("snapped")
    items: list[dict[str, Any]] = [
        {"kind": "cap", "name": "lid", "cells": [2, 1], "latch": SIDES},
        {"kind": "bin", "name": "tray", "cells": [2, 1], "units": 2, "latch": SIDES},
    ]

    return build_stack(load_stack(write_stack(directory, items)), PRINTER)


def test_a_latched_cap_builds_and_every_check_passes(snapped: Any) -> None:
    assert snapped.passed, [name for name, ok in snapped.checks.items() if not ok]

    for check in (
        "latch_tongues_freed",
        "latch_keepers_open",
        "latch_hook_engages",
        "latch_hook_passes",
        "sits_on_a_bin",
    ):
        assert snapped.checks[f"lid.{check}"]


def test_a_cap_reports_its_latch_and_stays_flat_on_top(snapped: Any) -> None:
    summary = snapped.summary["items"]["lid"]

    assert summary["latch"]["sides"] == ["front", "back"]
    assert (
        summary["latch"]["strain_percent"] <= summary["latch"]["strain_limit_percent"]
    )
    # The cap's overall height is the foot and its thickness, hooks or none.
    assert summary["overall_height_mm"] == pytest.approx(4.75 + 1.2)


def test_a_latched_cap_snaps_onto_a_bin_with_keepers(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [
            {"kind": "cap", "name": "lid", "cells": [1, 1], "latch": SIDES},
            {
                "kind": "bin",
                "name": "tray",
                "cells": [1, 1],
                "units": 2,
                "latch": SIDES,
            },
            {
                "kind": "frame",
                "name": "chest",
                "cells": [1, 1],
                "units": 3,
                "drawers": 1,
                "latch": SIDES,
            },
        ],
    )

    assert check_stackable(path, "lid", path, "tray", PRINTER).stacks
    assert check_stackable(path, "lid", path, "chest", PRINTER).stacks


def test_a_latched_cap_is_refused_on_a_bin_without_keepers(tmp_path: Path) -> None:
    path = write_stack(
        tmp_path,
        [
            {"kind": "cap", "name": "lid", "cells": [1, 1], "latch": SIDES},
            {"kind": "bin", "name": "plain", "cells": [1, 1], "units": 2},
            {
                "kind": "bin",
                "name": "left",
                "cells": [1, 1],
                "units": 2,
                "latch": {"sides": ["left"]},
            },
        ],
    )
    on_plain = check_stackable(path, "lid", path, "plain", PRINTER)
    on_left = check_stackable(path, "lid", path, "left", PRINTER)

    assert not on_plain.stacks and "no keeper there" in on_plain.errors[0]
    assert not on_left.stacks and "front, back side" in on_left.errors[0]


def test_a_plain_cap_still_sits_on_a_bin_with_keepers_and_a_warning(
    tmp_path: Path,
) -> None:
    path = write_stack(
        tmp_path,
        [
            {"kind": "cap", "name": "lid", "cells": [1, 1]},
            {
                "kind": "bin",
                "name": "tray",
                "cells": [1, 1],
                "units": 2,
                "latch": SIDES,
            },
        ],
    )
    report = check_stackable(path, "lid", path, "tray", PRINTER)

    assert report.stacks and "has no hooks" in report.warnings[0]


def test_a_drawer_cannot_take_a_latch(tmp_path: Path) -> None:
    data = stack_template()
    data["items"] = [
        {"kind": "frame", "name": "f", "cells": [1, 1], "units": 3, "drawers": 1},
        {"kind": "drawer", "name": "d", "frame": "f", "latch": {}},
    ]
    report = check_stack_data(data)

    assert any("items[1] has unknown fields: latch" in e for e in report.errors)

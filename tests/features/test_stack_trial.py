"""A stack's build record and its stacking trials."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import profile_template
from zcad_core.features.stack_trial import (
    BUILD_RECORD,
    TRIAL_RECORD,
    complete_stack_trial,
    item_from_record,
    start_stack_trial,
)

SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
ITEMS: list[dict[str, Any]] = [
    {
        "kind": "bin",
        "name": "tub",
        "cells": [1, 1],
        "units": 2,
        "holding": "magnet",
        "magnet": "D6X2",
    },
    {
        "kind": "baseplate",
        "name": "base",
        "cells": [1, 1],
        "floor_mm": 3.5,
        "holding": "magnet",
        "magnet": "D6X2",
    },
    {"kind": "frame", "name": "chest", "cells": [1, 2], "units": 6, "drawers": 3},
    {"kind": "drawer", "name": "drawer", "frame": "chest"},
    {"kind": "cap", "name": "lid", "cells": [1, 2]},
    {
        "kind": "bin",
        "name": "screwed",
        "cells": [1, 1],
        "units": 2,
        "holding": "bolt",
        "fastener": "M2",
    },
]


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("stack")
    profile = directory / "profile.json"
    data = profile_template()
    data["source"] = SOURCE
    profile.write_text(json.dumps(data))
    stack = stack_template(profile)
    stack["source"] = "a stack for tests"
    stack["items"] = ITEMS
    path = directory / "stack.json"
    path.write_text(json.dumps(stack))
    code, built = run(
        "stack",
        "build",
        "--stack-file",
        str(path),
        "--output-directory",
        str(directory / "out"),
    )

    assert code == 0, built

    return Path(built["build_record"])


@pytest.fixture
def copy_of(record: Path, tmp_path: Path) -> Path:
    """A fresh copy of the record and its parts, so a trial can be written."""

    import shutil

    target = tmp_path / "out"
    shutil.copytree(record.parent, target)
    data = json.loads((target / BUILD_RECORD).read_text())

    for entry in data["items"].values():
        entry["part"]["stl_path"] = str(target / Path(entry["part"]["stl_path"]).name)

    (target / BUILD_RECORD).write_text(json.dumps(data))

    return target / BUILD_RECORD


def test_a_build_writes_a_record_that_names_its_inputs_and_parts(record: Path) -> None:
    data = json.loads(record.read_text())

    assert data["record_kind"] == "stack-build"
    assert len(data["stack_file"]["sha256"]) == 64
    assert data["profile"]["identifier"] == "EXAMPLE_PROFILE"
    assert len(data["profile"]["sha256"]) == 64
    assert set(data["items"]) == {"tub", "base", "chest", "drawer", "lid", "screwed"}
    assert data["items"]["tub"]["item"]["holding"] == "magnet"
    assert data["items"]["tub"]["summary"]["holding_part"] == "D6X2"
    assert len(data["items"]["tub"]["part"]["stl_sha256"]) == 64
    assert data["fit_checks"]["chest.one_solid"] is True
    assert "no load rating" in data["not_claimed"][0]


def test_the_checks_a_trial_asks_follow_each_kind_and_its_holding(record: Path) -> None:
    checks = json.loads(record.read_text())["checks"]

    assert "tub.sits_flat" in checks and "tub.stacks_square" in checks
    assert "tub.magnets_seat" in checks
    assert "screwed.screw_reaches_insert" in checks
    assert "base.pockets_clean" in checks and "base.magnets_seat" in checks
    assert "chest.drawers_slide" in checks
    assert "drawer.slides_free" in checks
    assert "lid.sits_on_its_bin" in checks
    assert "base.stacks_square" not in checks
    nominals = json.loads(record.read_text())["nominal_measurements_mm"]
    assert nominals["tub_width_mm"] == pytest.approx(41.5, abs=0.01)
    assert nominals["tub_height_mm"] == pytest.approx(18.0, abs=0.01)


def test_an_item_is_rebuilt_from_its_record(record: Path) -> None:
    entry = json.loads(record.read_text())["items"]["chest"]["item"]
    item = item_from_record(entry)

    assert (item.kind, item.cells, item.units, item.drawers) == ("frame", (1, 2), 6, 3)


def test_a_trial_lists_only_what_these_items_have(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    stacking = json.loads((trial / "stacking.json").read_text())

    assert trial.name == "trial-001"
    assert "drawer" not in stacking["items"] and "tub" in stacking["items"]
    assert "no limit" in stacking["not_a_limit"]
    assert stacking["other_makers"][0]["part"] == ""
    observations = json.loads((trial / "observations.json").read_text())
    assert observations["tub.stacks_square"]["result"] == "pending"
    assert start_stack_trial(copy_of).name == "trial-002"


def fill(
    trial: Path, stacking: dict[str, Any] | None = None, fail: str | None = None
) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for key, entry in observations.items():
        entry["result"] = "fail" if key == fail else "pass"

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["tub_width_mm"]["value_mm"] = 41.42
    (trial / "measurements.json").write_text(json.dumps(measurements))

    if stacking:
        readings = json.loads((trial / "stacking.json").read_text())

        for key, value in stacking.items():
            if isinstance(value, dict):
                readings[key][next(iter(value))].update(next(iter(value.values())))
            else:
                readings[key] = value

        (trial / "stacking.json").write_text(json.dumps(readings))


def complete(trial: Path, disposition: str = "pass") -> dict[str, Any]:
    path = complete_stack_trial(
        trial,
        disposition=EnclosureTrialDisposition(disposition),
        material_profile_id="petg",
    )

    return cast(dict[str, Any], json.loads(path.read_text()))


def test_a_filled_in_trial_keeps_the_readings_and_draws_no_conclusion(
    copy_of: Path,
) -> None:
    trial = start_stack_trial(copy_of)
    fill(
        trial,
        {
            "items": {
                "tub": {
                    "wobble_mm": 0.15,
                    "separation_force_n": 6.5,
                    "stackings_counted": 40,
                    "anything_wore": False,
                    "notes": "a little loose",
                }
            },
            "other_makers": [
                {"part": "Brand X baseplate", "sits_on": False, "notes": "too tight"}
            ],
        },
    )
    record = complete(trial)

    assert record["passed"] is True
    reading = record["stacking"]["items"][0]
    assert reading["item"] == "tub" and reading["wobble_mm"] == 0.15
    assert reading["separation_force_n"] == 6.5 and reading["anything_wore"] is False
    assert record["stacking"]["other_makers"] == [
        {"part": "Brand X baseplate", "sits_on": False, "notes": "too tight"}
    ]
    assert record["measurements"][0]["deviation_mm"] == pytest.approx(-0.08, abs=0.001)
    assert (
        record["profile_sha256"] == json.loads(copy_of.read_text())["profile"]["sha256"]
    )
    assert (trial / TRIAL_RECORD).is_file()

    with pytest.raises(FileExistsError):
        complete(trial)


@pytest.mark.parametrize(
    ("stacking", "message"),
    [
        ({"items": {"tub": {"wobble_mm": -0.1}}}, "from zero"),
        ({"items": {"tub": {"separation_force_n": 0}}}, "above zero"),
        ({"items": {"tub": {"stackings_counted": 0}}}, "whole number"),
        ({"items": {"tub": {"anything_wore": True}}}, "needs stackings_counted"),
        ({"items": {"tub": {"stackings_counted": 5}}}, "true or false"),
        ({"other_makers": [{"part": "X", "sits_on": "yes"}]}, "true or false"),
        ({"other_makers": [{"part": "", "sits_on": True}]}, "needs the part's name"),
    ],
)
def test_a_reading_that_cannot_be_right_is_refused(
    copy_of: Path, stacking: dict[str, Any], message: str
) -> None:
    trial = start_stack_trial(copy_of)
    fill(trial, stacking)

    with pytest.raises((ValueError, TypeError), match=message):
        complete(trial)


def test_a_reading_for_an_item_that_was_not_built_is_refused(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    fill(trial)
    readings = json.loads((trial / "stacking.json").read_text())
    readings["items"]["ghost"] = {"wobble_mm": 0.1}
    (trial / "stacking.json").write_text(json.dumps(readings))

    with pytest.raises(ValueError, match="not built in this stack"):
        complete(trial)


def test_a_trial_needs_a_reading_unless_it_failed(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "fail"

    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(
        ValueError, match="at least one measurement or stacking reading"
    ):
        complete(trial, "revise")

    assert complete(trial, "fail")["passed"] is False


def test_a_passing_trial_cannot_have_a_failed_check(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    fill(trial, fail="tub.stacks_square")

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete(trial, "pass")

    assert complete(trial, "revise")["failed_checks"] == ["tub.stacks_square"]


def test_a_trial_is_refused_if_the_parts_changed(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    fill(trial)
    stl = Path(json.loads(copy_of.read_text())["items"]["tub"]["part"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"x")

    with pytest.raises(ValueError, match="no longer match"):
        complete(trial)


def test_the_commands_start_and_complete_a_trial(copy_of: Path) -> None:
    code, started = run("stack", "trial", "start", "--build-record", str(copy_of))
    trial = Path(started["trial"])

    assert code == 0 and Path(started["stacking"]).is_file()
    fill(trial)
    code, done = run(
        "stack",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0 and done["passed"] is True


def test_check_stack_reads_the_items_of_a_build_record(record: Path) -> None:
    code, report = run(
        "stack", "check-stack", "--upper", f"{record}:tub", "--lower", f"{record}:base"
    )

    assert code == 0 and report["stacks"] is True, report
    assert report["held_by"] == "magnet (D6X2)"
    code, report = run(
        "stack", "check-stack", "--upper", f"{record}:lid", "--lower", f"{record}:chest"
    )

    assert code == 0 and report["stacks"] is True, report
    code, report = run(
        "stack",
        "check-stack",
        "--upper",
        f"{record}:screwed",
        "--lower",
        f"{record}:base",
    )

    assert code == 1 and any(
        "disagree on what holds them" in e for e in report["errors"]
    )
    code, report = run(
        "stack", "check-stack", "--upper", f"{record}:nope", "--lower", f"{record}:base"
    )

    assert code == 1 and any("has no item 'nope'" in e for e in report["errors"])


def test_check_stack_does_not_trust_a_record_whose_profile_changed(
    copy_of: Path,
) -> None:
    profile = Path(json.loads(copy_of.read_text())["profile"]["path"])
    original = profile.read_text()
    changed = json.loads(original)
    changed["min_nest_clearance_mm"] = 0.2
    profile.write_text(json.dumps(changed))

    try:
        code, report = run(
            "stack",
            "check-stack",
            "--upper",
            f"{copy_of}:tub",
            "--lower",
            f"{copy_of}:base",
        )
    finally:
        profile.write_text(original)

    assert code == 1
    assert any("has changed since the build" in e for e in report["errors"])


def test_item_names_become_measurement_names_and_stay_apart() -> None:
    from zcad_core.features.stack_trial import _measure_key

    taken: dict[str, float] = {}
    first = _measure_key("Tub-1", taken)
    taken[f"{first}_width_mm"] = 1.0

    assert first == "tub_1"
    assert _measure_key("tub_1", taken) == "tub_1_2"

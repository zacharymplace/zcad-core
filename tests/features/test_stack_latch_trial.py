"""The trial readings for a stack's latches and a drawer's detent."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.stack_file import Item, stack_template
from zcad_core.features.stack_profile import profile_template
from zcad_core.features.stack_trial import (
    BUILD_RECORD,
    complete_stack_trial,
    start_stack_trial,
)

PASS = EnclosureTrialDisposition.PASS
REVISE = EnclosureTrialDisposition.REVISE
SIDES = {"sides": ["front", "back"]}
ITEMS: list[dict[str, Any]] = [
    {"kind": "bin", "name": "tub", "cells": [1, 1], "units": 2, "latch": SIDES},
    {"kind": "baseplate", "name": "base", "cells": [1, 1], "latch": SIDES},
    {"kind": "cap", "name": "lid", "cells": [1, 1], "latch": SIDES},
    {
        "kind": "frame",
        "name": "chest",
        "cells": [1, 1],
        "units": 4,
        "drawers": 2,
        "wall_mm": 1.8,
        "detent": {},
    },
    {"kind": "drawer", "name": "tray", "frame": "chest", "detent": {}},
    {"kind": "bin", "name": "plain", "cells": [1, 1], "units": 2},
]


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("snaps")
    profile = directory / "profile.json"
    data = profile_template()
    data["source"] = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"
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
    target = tmp_path / "out"
    shutil.copytree(record.parent, target)
    data = json.loads((target / BUILD_RECORD).read_text())

    for entry in data["items"].values():
        entry["part"]["stl_path"] = str(target / Path(entry["part"]["stl_path"]).name)

    (target / BUILD_RECORD).write_text(json.dumps(data))

    return target / BUILD_RECORD


def pass_all(trial: Path) -> None:
    path = trial / "observations.json"
    data = json.loads(path.read_text())

    for entry in data.values():
        entry["result"] = "pass"

    path.write_text(json.dumps(data))


def fill(trial: Path, name: str, change: Any) -> None:
    path = trial / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


# --- the build record ---------------------------------------------------------------------------


def test_the_record_asks_each_item_for_the_checks_its_snap_needs(record: Path) -> None:
    data = json.loads(record.read_text())
    checks = set(data["checks"])

    assert data["schema_version"] == "1.1.0"
    assert {"tub.latch_clicks", "tub.keepers_clean"} <= checks
    assert "lid.latch_clicks" in checks and "lid.keepers_clean" not in checks
    assert "base.keepers_clean" in checks and "base.latch_clicks" not in checks
    assert "chest.dimples_clean" in checks and "tray.detent_clicks" in checks
    assert not any(
        c.startswith("plain.") and ("latch" in c or "keepers" in c) for c in checks
    )


def test_the_record_gives_the_snap_sizes_to_measure(record: Path) -> None:
    nominals = json.loads(record.read_text())["nominal_measurements_mm"]

    assert nominals["tub_hook_stand_out_mm"] == pytest.approx(0.65)
    assert nominals["base_keeper_depth_mm"] == pytest.approx(0.6)
    assert nominals["tray_bump_stand_out_mm"] == pytest.approx(0.6)
    assert nominals["chest_dimple_depth_mm"] == pytest.approx(0.6)
    assert "plain_hook_stand_out_mm" not in nominals


def test_the_items_in_the_record_carry_their_latch_and_detent_settings(
    record: Path,
) -> None:
    items = json.loads(record.read_text())["items"]

    assert items["tub"]["item"]["latch_sides"] == ["front", "back"]
    assert items["tray"]["item"]["detent"] is True
    assert items["tub"]["summary"]["latch"]["strain_percent"] <= 1.5


# --- the trial ----------------------------------------------------------------------------------


def test_the_template_has_a_reading_for_each_hooked_item_and_each_drawer(
    copy_of: Path,
) -> None:
    trial = start_stack_trial(copy_of)
    readings = json.loads((trial / "latch.json").read_text())

    assert sorted(readings["items"]) == ["lid", "tray", "tub"]
    assert "clicked_on" in readings["items"]["tub"]
    assert "clicked_shut" in readings["items"]["tray"]
    assert readings["items"]["tub"]["designed"]["engagement_mm"] == 0.4
    assert "states no limit" in readings["not_a_limit"]


def test_a_trial_with_a_latch_reading_is_recorded_beside_what_was_designed(
    copy_of: Path,
) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)

    def readings(data: dict[str, Any]) -> None:
        data["items"]["tub"].update(
            clicked_on=True,
            clicked_off=True,
            separation_force_n=4.5,
            snaps_counted=20,
            anything_wore=False,
        )
        data["items"]["tray"].update(
            clicked_shut=True, clicked_open=False, pull_force_n=1.2
        )

    fill(trial, "latch.json", readings)
    record = json.loads(
        complete_stack_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )
    latch = record["latch"]
    by_item = {entry["item"]: entry for entry in latch["items"]}

    assert record["schema_version"] == "1.1.0" and record["passed"]
    assert sorted(by_item) == ["tray", "tub"]
    assert by_item["tub"]["separation_force_n"] == 4.5
    assert (
        by_item["tub"]["snaps_counted"] == 20
        and by_item["tub"]["anything_wore"] is False
    )
    assert by_item["tub"]["designed"]["engagement_mm"] == 0.4
    assert by_item["tray"]["clicked_open"] is False
    assert by_item["tray"]["pull_force_n"] == 1.2
    assert by_item["tray"]["designed"]["dimple_depth_mm"] == pytest.approx(0.6)
    assert "states no limit" in latch["not_a_limit"]
    assert "holding force" not in json.dumps(by_item)


def test_a_latch_reading_alone_is_enough_for_a_passing_trial(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)

    with pytest.raises(ValueError, match="at least one measurement"):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")

    fill(
        trial,
        "latch.json",
        lambda d: d["items"]["lid"].update(clicked_on=True),
    )

    assert complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_failed_snap_check_stops_a_pass_but_not_a_revise(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(
        trial,
        "observations.json",
        lambda d: d["tub.latch_clicks"].update(result="fail"),
    )
    fill(trial, "latch.json", lambda d: d["items"]["tub"].update(clicked_on=False))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")

    record = json.loads(
        complete_stack_trial(
            trial, disposition=REVISE, material_profile_id="petg"
        ).read_text()
    )

    assert record["failed_checks"] == ["tub.latch_clicks"]


@pytest.mark.parametrize(
    ("item", "entry", "error", "message"),
    [
        (
            "tub",
            {"snaps_counted": 0, "anything_wore": False},
            ValueError,
            "whole number",
        ),
        ("tub", {"snaps_counted": 3}, TypeError, "true or false"),
        ("tub", {"anything_wore": True}, ValueError, "needs snaps_counted"),
        ("tub", {"separation_force_n": 0}, ValueError, "above zero"),
        ("tub", {"clicked_on": "yes"}, TypeError, "true or false"),
        ("tray", {"pull_force_n": -1}, ValueError, "above zero"),
        ("tray", {"clicked_shut": 1}, TypeError, "true or false"),
    ],
)
def test_bad_latch_readings_are_refused(
    copy_of: Path,
    item: str,
    entry: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(trial, "latch.json", lambda d: d["items"][item].update(entry))

    with pytest.raises(error, match=message):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_reading_for_an_item_with_nothing_to_read_is_refused(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(
        trial,
        "latch.json",
        lambda d: d["items"].update({"plain": {"clicked_on": True}}),
    )

    with pytest.raises(ValueError, match=r"no latch or detent to read.*\['plain'\]"):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_stack_with_no_latches_writes_no_latch_file(tmp_path: Path) -> None:
    directory = tmp_path / "plain"
    directory.mkdir()
    profile = directory / "profile.json"
    data = profile_template()
    data["source"] = "checked for a test"
    profile.write_text(json.dumps(data))
    stack = stack_template(profile)
    stack["source"] = "a stack for tests"
    stack["items"] = [{"kind": "bin", "name": "tub", "cells": [1, 1], "units": 2}]
    (directory / "stack.json").write_text(json.dumps(stack))
    code, built = run(
        "stack",
        "build",
        "--stack-file",
        str(directory / "stack.json"),
        "--output-directory",
        str(directory / "out"),
    )

    assert code == 0, built
    code, started = run(
        "stack", "trial", "start", "--build-record", built["build_record"]
    )

    assert code == 0 and "latch" not in started


def test_the_commands_start_a_trial_with_a_latch_file(copy_of: Path) -> None:
    code, started = run("stack", "trial", "start", "--build-record", str(copy_of))

    assert code == 0 and Path(started["latch"]).name == "latch.json"


def test_an_item_is_still_an_item(record: Path) -> None:
    from zcad_core.features.stack_trial import item_from_record

    items = json.loads(record.read_text())["items"]
    item = item_from_record(items["tub"]["item"])

    assert isinstance(item, Item) and item.latch_sides == ("front", "back")

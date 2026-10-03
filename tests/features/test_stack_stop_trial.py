"""The trial readings for a drawer's stop."""

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
from zcad_core.features.stack_file import stack_template
from zcad_core.features.stack_profile import profile_template
from zcad_core.features.stack_trial import (
    BUILD_RECORD,
    complete_stack_trial,
    start_stack_trial,
)

PASS = EnclosureTrialDisposition.PASS
REVISE = EnclosureTrialDisposition.REVISE
ITEMS: list[dict[str, Any]] = [
    {
        "kind": "frame",
        "name": "vault",
        "cells": [1, 1],
        "units": 4,
        "drawers": 2,
        "wall_mm": 1.8,
        "detent": {},
        "stop": {},
    },
    {"kind": "drawer", "name": "safe", "frame": "vault", "detent": {}, "stop": {}},
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
]


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("stops")
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


def test_the_record_asks_a_stopped_drawer_and_its_frame_for_the_stops_checks(
    record: Path,
) -> None:
    checks = set(json.loads(record.read_text())["checks"])

    assert {"safe.stop_holds", "safe.stop_releases", "safe.detent_clicks"} <= checks
    assert {"vault.windows_clean", "vault.dimples_clean"} <= checks
    assert "tray.stop_holds" not in checks and "chest.windows_clean" not in checks


def test_the_record_gives_the_stops_travel_and_window_to_measure(record: Path) -> None:
    nominals = json.loads(record.read_text())["nominal_measurements_mm"]

    assert nominals["safe_stop_travel_mm"] == pytest.approx(21.5, abs=0.1)
    assert nominals["vault_window_length_mm"] == pytest.approx(5.6)
    assert nominals["vault_window_height_mm"] == pytest.approx(4.2)
    assert "tray_stop_travel_mm" not in nominals
    assert "chest_window_length_mm" not in nominals


# --- the trial ----------------------------------------------------------------------------------


def test_the_template_has_the_stops_readings_for_a_stopped_drawer_only(
    copy_of: Path,
) -> None:
    trial = start_stack_trial(copy_of)
    items = json.loads((trial / "latch.json").read_text())["items"]

    assert {"stopped", "stop_force_n", "released", "went_back"} <= set(items["safe"])
    assert "stopped" not in items["tray"]
    assert items["safe"]["designed"]["stop"]["travel_share"] == pytest.approx(
        0.54, abs=0.01
    )
    assert "squeeze" in items["safe"]["guidance"]


def test_a_trial_records_the_stop_beside_what_was_designed(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)

    def readings(data: dict[str, Any]) -> None:
        data["items"]["safe"].update(
            clicked_shut=True,
            clicked_open=True,
            pull_force_n=1.1,
            stopped=True,
            stop_force_n=6.5,
            released=True,
            went_back=True,
            snaps_counted=25,
            anything_wore=False,
        )

    fill(trial, "latch.json", readings)
    fill(
        trial,
        "measurements.json",
        lambda d: d["safe_stop_travel_mm"].update(value_mm=20.0),
    )
    record = json.loads(
        complete_stack_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )
    entry = record["latch"]["items"][0]

    assert entry["item"] == "safe"
    assert entry["stopped"] is True and entry["stop_force_n"] == 6.5
    assert entry["released"] is True and entry["went_back"] is True
    assert entry["pull_force_n"] == 1.1 and entry["snaps_counted"] == 25
    assert entry["designed"]["stop"]["travel_mm"] == pytest.approx(21.5, abs=0.1)
    travel = next(
        m for m in record["measurements"] if m["name"] == "safe_stop_travel_mm"
    )

    assert travel["deviation_mm"] == pytest.approx(20.0 - travel["nominal_mm"])
    assert "holding force" not in json.dumps(entry)


def test_a_stop_that_did_not_hold_is_a_reading_and_a_failed_check_stops_a_pass(
    copy_of: Path,
) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(
        trial,
        "observations.json",
        lambda d: d["safe.stop_holds"].update(result="fail"),
    )
    fill(trial, "latch.json", lambda d: d["items"]["safe"].update(stopped=False))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")

    record = json.loads(
        complete_stack_trial(
            trial, disposition=REVISE, material_profile_id="petg"
        ).read_text()
    )

    assert record["failed_checks"] == ["safe.stop_holds"]
    assert record["latch"]["items"][0]["stopped"] is False


@pytest.mark.parametrize(
    ("entry", "error", "message"),
    [
        ({"stopped": "yes"}, TypeError, "true or false"),
        ({"released": 1}, TypeError, "true or false"),
        ({"went_back": "no"}, TypeError, "true or false"),
        ({"stop_force_n": 0}, ValueError, "above zero"),
        ({"stop_force_n": "hard"}, ValueError, "above zero"),
    ],
)
def test_bad_stop_readings_are_refused(
    copy_of: Path, entry: dict[str, Any], error: type[Exception], message: str
) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(trial, "latch.json", lambda d: d["items"]["safe"].update(entry))

    with pytest.raises(error, match=message):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_stop_reading_alone_is_enough_for_a_passing_trial(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)

    with pytest.raises(ValueError, match="at least one measurement"):
        complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")

    fill(trial, "latch.json", lambda d: d["items"]["safe"].update(stopped=True))

    assert complete_stack_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_plain_detent_drawer_is_still_read_as_before(copy_of: Path) -> None:
    trial = start_stack_trial(copy_of)
    pass_all(trial)
    fill(
        trial,
        "latch.json",
        lambda d: d["items"]["tray"].update(
            clicked_shut=True, clicked_open=True, pull_force_n=0.9
        ),
    )
    record = json.loads(
        complete_stack_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )
    entry = record["latch"]["items"][0]

    assert entry["item"] == "tray" and entry["pull_force_n"] == 0.9
    assert "stopped" not in entry
    assert "stop" not in entry["designed"]

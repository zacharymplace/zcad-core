"""The trial readings for a stack top, on an enclosure and on a group."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group_trial import (
    complete_group_trial,
    start_group_trial,
)
from zcad_core.features.enclosure_trial import (
    EnclosureTrialDisposition,
    complete_enclosure_trial,
    start_enclosure_trial,
)
from zcad_core.features.stack_profile import profile_template

PASS = EnclosureTrialDisposition.PASS
REVISE = EnclosureTrialDisposition.REVISE
SOURCE = "Gridfinity Rebuilt OpenSCAD standard.scad, checked for a test"


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue() or "{}"))


def write_profile(directory: Path) -> Path:
    data = profile_template()
    data["source"] = SOURCE
    path = directory / "profile.json"
    path.write_text(json.dumps(data))

    return path


@pytest.fixture(scope="module")
def pico(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("pico")
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--stack-top",
        "--stack-profile",
        str(write_profile(directory)),
        "--output-directory",
        str(directory / "out"),
    )

    assert code == 0, built

    return Path(built["build_record"])


@pytest.fixture(scope="module")
def plain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("plain")
    code, built = run(
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--output-directory",
        str(directory / "out"),
    )

    assert code == 0, built

    return Path(built["build_record"])


@pytest.fixture(scope="module")
def group(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("group")
    code, built = run(
        "enclosure-group",
        "build",
        "--bays",
        "pi5",
        "--stack-top",
        "--no-vents",
        "--stack-profile",
        str(write_profile(directory)),
        "--output-directory",
        str(directory / "out"),
    )

    assert code == 0, built

    return Path(built["build_record"])


def copy_of(record: Path, tmp_path: Path) -> Path:
    """A fresh copy of a record and its parts, so a trial can be written."""

    target = tmp_path / "out"
    shutil.copytree(record.parent, target)
    path = target / record.name
    data = json.loads(path.read_text())

    for entry in data["parts"].values():
        entry["stl_path"] = str(target / Path(entry["stl_path"]).name)

    path.write_text(json.dumps(data))

    return path


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


READINGS = {
    "gap_under_plate_mm": 0.2,
    "screws_pass_all_holes": True,
    "screw_length_mm": 8,
    "bin_wobble_mm": 0.3,
    "separation_force_n": 5.5,
    "stackings_counted": 10,
    "anything_wore": False,
}


# --- the record ---------------------------------------------------------------------------------


def test_the_record_asks_the_checks_and_the_sizes_for_a_stack_top(pico: Path) -> None:
    data = json.loads(pico.read_text())
    nominals = data["nominal_measurements_mm"]

    assert data["schema_version"] == "1.1.0"
    assert {"stack_top_sits_flat", "stack_top_screws_reach"} <= set(data["checks"])
    assert nominals["stack_top_thickness_mm"] == pytest.approx(8.85, abs=0.01)
    assert nominals["stack_top_floor_mm"] == pytest.approx(4.5)
    assert nominals["stack_top_recess_depth_mm"] == pytest.approx(3.5)
    assert nominals["stack_top_recess_diameter_mm"] > 5.0
    assert nominals["stack_top_width_mm"] == pytest.approx(44.4, abs=0.01)


def test_an_enclosure_without_a_stack_top_is_asked_nothing_of_one(plain: Path) -> None:
    data = json.loads(plain.read_text())

    assert not any(check.startswith("stack_top") for check in data["checks"])
    assert not any(
        name.startswith("stack_top") for name in data["nominal_measurements_mm"]
    )


# --- an enclosure's trial -----------------------------------------------------------------------


def test_the_template_has_the_designed_plate_and_blank_readings(
    pico: Path, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(copy_of(pico, tmp_path))
    template = json.loads((trial / "stack_top.json").read_text())

    assert template["designed"]["recommended_screw_mm"] == 8
    assert template["designed"]["cells"] == [1, 2]
    assert template["gap_under_plate_mm"] is None
    assert "states no limit" in template["not_a_limit"]
    assert "feeler gauge" in template["guidance"]


def test_a_trial_records_the_readings_beside_what_was_designed(
    pico: Path, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(copy_of(pico, tmp_path))
    pass_all(trial)
    fill(trial, "stack_top.json", lambda d: d.update(READINGS))
    fill(
        trial,
        "measurements.json",
        lambda d: d["stack_top_thickness_mm"].update(value_mm=8.7),
    )
    record = json.loads(
        complete_enclosure_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )
    top = record["stack_top"]

    assert record["schema_version"] == "1.1.0" and record["passed"]
    assert top["gap_under_plate_mm"] == 0.2 and top["screws_pass_all_holes"] is True
    assert top["screw_length_mm"] == 8 and top["recommended_screw_mm"] == 8
    assert top["bin_wobble_mm"] == 0.3 and top["separation_force_n"] == 5.5
    assert top["stackings_counted"] == 10 and top["anything_wore"] is False
    assert top["designed"]["floor_mm"] == pytest.approx(4.5)
    assert "no limit" in top["not_a_limit"] and "load rating" in top["not_a_limit"]
    thickness = next(
        m for m in record["measurements"] if m["name"] == "stack_top_thickness_mm"
    )

    assert thickness["deviation_mm"] == pytest.approx(8.7 - thickness["nominal_mm"])


def test_a_reading_alone_is_enough_and_none_taken_is_left_out(
    pico: Path, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(copy_of(pico, tmp_path))
    pass_all(trial)

    with pytest.raises(ValueError, match="a stack top reading"):
        complete_enclosure_trial(trial, disposition=PASS, material_profile_id="petg")

    fill(trial, "stack_top.json", lambda d: d.update(gap_under_plate_mm=0.1))
    record = json.loads(
        complete_enclosure_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )

    assert record["stack_top"]["gap_under_plate_mm"] == 0.1
    assert record["stack_top"]["bin_wobble_mm"] is None


def test_a_failed_stack_top_check_stops_a_pass_but_not_a_revise(
    pico: Path, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(copy_of(pico, tmp_path))
    pass_all(trial)
    fill(
        trial,
        "observations.json",
        lambda d: d["stack_top_screws_reach"].update(result="fail"),
    )
    fill(trial, "stack_top.json", lambda d: d.update(screws_pass_all_holes=False))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_enclosure_trial(trial, disposition=PASS, material_profile_id="petg")

    record = json.loads(
        complete_enclosure_trial(
            trial, disposition=REVISE, material_profile_id="petg"
        ).read_text()
    )

    assert record["failed_checks"] == ["stack_top_screws_reach"]
    assert record["stack_top"]["screws_pass_all_holes"] is False


@pytest.mark.parametrize(
    ("entry", "error", "message"),
    [
        ({"gap_under_plate_mm": -0.1}, ValueError, "from zero"),
        ({"bin_wobble_mm": "loose"}, ValueError, "from zero"),
        ({"separation_force_n": 0}, ValueError, "above zero"),
        ({"screw_length_mm": -8}, ValueError, "above zero"),
        ({"screws_pass_all_holes": "yes"}, TypeError, "true or false"),
        ({"stackings_counted": 0, "anything_wore": False}, ValueError, "whole number"),
        ({"stackings_counted": 4}, TypeError, "true or false"),
        ({"anything_wore": True}, ValueError, "needs stackings_counted"),
    ],
)
def test_bad_stack_top_readings_are_refused(
    pico: Path,
    tmp_path: Path,
    entry: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    trial = start_enclosure_trial(copy_of(pico, tmp_path))
    pass_all(trial)
    fill(trial, "stack_top.json", lambda d: d.update(entry))

    with pytest.raises(error, match=message):
        complete_enclosure_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_reading_for_an_enclosure_with_no_stack_top_is_refused(
    plain: Path, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(copy_of(plain, tmp_path))

    assert not (trial / "stack_top.json").exists()
    pass_all(trial)
    fill(
        trial,
        "measurements.json",
        lambda d: d["wall_thickness_mm"].update(value_mm=2.1),
    )
    (trial / "stack_top.json").write_text(json.dumps({"gap_under_plate_mm": 0.1}))

    with pytest.raises(ValueError, match="built with no stack top"):
        complete_enclosure_trial(trial, disposition=PASS, material_profile_id="petg")


def test_the_trial_start_command_names_the_stack_top_file(
    pico: Path, plain: Path, tmp_path: Path
) -> None:
    code, started = run(
        "enclosure",
        "trial",
        "start",
        "--build-record",
        str(copy_of(pico, tmp_path)),
    )

    assert code == 0 and Path(started["stack_top"]).name == "stack_top.json"
    other = tmp_path / "other"
    other.mkdir()
    code, started = run(
        "enclosure",
        "trial",
        "start",
        "--build-record",
        str(copy_of(plain, other)),
    )

    assert code == 0 and "stack_top" not in started


# --- a group's trial ----------------------------------------------------------------------------


def test_a_groups_record_and_trial_carry_the_stack_top_too(
    group: Path, tmp_path: Path
) -> None:
    data = json.loads(group.read_text())

    assert data["schema_version"] == "1.1.0"
    assert {"stack_top_sits_flat", "stack_top_screws_reach"} <= set(data["checks"])
    assert data["nominal_measurements_mm"]["stack_top_floor_mm"] == pytest.approx(4.5)
    trial = start_group_trial(copy_of(group, tmp_path))
    template = json.loads((trial / "stack_top.json").read_text())

    assert template["designed"]["recommended_screw_mm"] == 8
    pass_all(trial)
    fill(trial, "stack_top.json", lambda d: d.update(READINGS))
    record = json.loads(
        complete_group_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )

    assert record["passed"] and record["stack_top"]["screw_length_mm"] == 8
    assert record["stack_top"]["designed"]["screw_reach_mm"] == pytest.approx(9.0)

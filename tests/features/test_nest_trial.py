"""Trials for a holding nest and an insert jig: a print, and how it did its job."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.jig_file import jig_template
from zcad_core.features.nest_file import nest_template
from zcad_core.features.nest_trial import (
    complete_jig_trial,
    complete_nest_trial,
    jig_checks,
    nest_checks,
    start_jig_trial,
    start_nest_trial,
)

PASS = EnclosureTrialDisposition.PASS
FAIL = EnclosureTrialDisposition.FAIL
REVISE = EnclosureTrialDisposition.REVISE
STRAP = {"width_mm": 20.0, "thickness_mm": 1.5, "source": "a strap, measured"}
IRON = {
    "tip_diameter_mm": 4.0,
    "shoulder_diameter_mm": 9.0,
    "tip_length_mm": 6.0,
    "source": "measured with calipers on the bench iron",
}


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


@pytest.fixture(scope="module")
def slab(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("slab") / "slab.step"
    block = cq.Workplane("XY").box(50, 30, 16, centered=(True, True, False))
    cq.exporters.export(block, str(path))

    return path


@pytest.fixture
def nest_build(slab: Path, tmp_path: Path) -> Path:
    data = nest_template(slab)
    data["source"] = "a block for tests"
    data["nest"]["flange_mm"] = 10.0
    data["features"] = {
        "finger_notches": 1,
        "lip": {"tabs": 2},
        "strap": STRAP,
        "label": "BASE",
    }
    (tmp_path / "nest.json").write_text(json.dumps(data))
    code, out = run(
        "nest",
        "build",
        "--nest-file",
        str(tmp_path / "nest.json"),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0, out

    return Path(out["build_record"])


@pytest.fixture
def jig_build(slab: Path, tmp_path: Path) -> Path:
    data = jig_template(slab)
    data["source"] = "a block for tests"
    data["iron"] = IRON
    data["inserts"] = [
        {"id": "I1", "x_mm": -10.0, "y_mm": 0.0},
        {"id": "I2", "x_mm": 10.0, "y_mm": 0.0},
    ]
    (tmp_path / "jig.json").write_text(json.dumps(data))
    code, out = run(
        "jig",
        "build",
        "--jig-file",
        str(tmp_path / "jig.json"),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0, out

    return Path(out["build_record"])


def fill(trial: Path, name: str, change: Any) -> None:
    path = trial / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def pass_all(trial: Path) -> None:
    def mark(data: dict[str, Any]) -> None:
        for entry in data.values():
            entry["result"] = "pass"

    fill(trial, "observations.json", mark)


# --- the build records carry what a trial asks --------------------------------------------------


def test_the_checks_follow_the_features() -> None:
    assert nest_checks(lip=False, strap=False, label=False) == [
        "printed_cleanly",
        "part_seats",
        "part_lifts_out",
    ]
    assert nest_checks(lip=True, strap=True, label=True)[3:] == [
        "part_stays_in",
        "strap_holds_still",
        "label_legible",
    ]
    assert "shoulder_stops" in jig_checks()


def test_a_nest_build_records_its_checks_and_sizes(nest_build: Path) -> None:
    record = json.loads(nest_build.read_text())

    assert record["schema_version"] == "1.1.0"
    assert "part_stays_in" in record["checks"] and "label_legible" in record["checks"]
    assert record["nominal_measurements_mm"]["pocket_depth_mm"] == pytest.approx(16.0)
    assert record["nominal_measurements_mm"]["strap_slot_width_mm"] == pytest.approx(
        1.9
    )


def test_a_jig_build_records_its_checks_and_sizes(jig_build: Path) -> None:
    record = json.loads(jig_build.read_text())

    assert record["checks"] == jig_checks()
    assert record["nominal_measurements_mm"]["plate_thickness_mm"] == pytest.approx(6.0)


# --- a nest trial -------------------------------------------------------------------------------


def test_a_nest_trial_records_what_was_seen_and_counted(nest_build: Path) -> None:
    trial = start_nest_trial(nest_build)

    assert trial.name == "trial-001"
    assert start_nest_trial(nest_build).name == "trial-002"
    observations = json.loads((trial / "observations.json").read_text())

    assert observations["part_seats"]["result"] == "pending"
    pass_all(trial)
    fill(
        trial,
        "measurements.json",
        lambda d: d["overall_width_mm"].update(value_mm=70.5),
    )
    fill(trial, "use.json", lambda d: d.update(uses_counted=12, anything_wore=False))
    record = json.loads(
        complete_nest_trial(
            trial, disposition=PASS, material_profile_id="petg", notes="ok"
        ).read_text()
    )

    assert record["passed"] and record["failed_checks"] == []
    assert (
        record["use"]["uses_counted"] == 12 and record["use"]["anything_wore"] is False
    )
    assert "states no limit" in record["use"]["not_a_limit"]
    assert record["measurements"][0]["name"] == "overall_width_mm"
    assert record["measurements"][0]["deviation_mm"] is not None
    assert "how well the nest holds a part" in record["not_claimed"]
    assert record["part_sha256"] and record["build_record_sha256"]

    with pytest.raises(FileExistsError):
        complete_nest_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_nest_trial_that_passes_with_a_failed_check_is_refused(
    nest_build: Path,
) -> None:
    trial = start_nest_trial(nest_build)
    pass_all(trial)
    fill(
        trial,
        "observations.json",
        lambda d: d["part_stays_in"].update(result="fail"),
    )
    fill(trial, "use.json", lambda d: d.update(uses_counted=3, anything_wore=True))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_nest_trial(trial, disposition=PASS, material_profile_id="petg")

    record = json.loads(
        complete_nest_trial(
            trial, disposition=REVISE, material_profile_id="petg"
        ).read_text()
    )

    assert record["failed_checks"] == ["part_stays_in"] and not record["passed"]


def test_a_nest_trial_needs_a_reading_unless_it_failed(nest_build: Path) -> None:
    trial = start_nest_trial(nest_build)
    pass_all(trial)

    with pytest.raises(ValueError, match="at least one measurement or reading"):
        complete_nest_trial(trial, disposition=PASS, material_profile_id="petg")

    assert complete_nest_trial(trial, disposition=FAIL, material_profile_id="petg")


@pytest.mark.parametrize(
    ("use", "error", "message"),
    [
        ({"uses_counted": 0, "anything_wore": False}, ValueError, "whole number"),
        ({"uses_counted": 2.5, "anything_wore": False}, ValueError, "whole number"),
        ({"uses_counted": 3}, TypeError, "true or false"),
        ({"anything_wore": True}, ValueError, "needs uses_counted"),
    ],
)
def test_bad_use_readings_are_refused(
    nest_build: Path, use: dict[str, Any], error: type[Exception], message: str
) -> None:
    trial = start_nest_trial(nest_build)
    pass_all(trial)
    fill(trial, "use.json", lambda d: d.update(use))

    with pytest.raises(error, match=message):
        complete_nest_trial(trial, disposition=PASS, material_profile_id="petg")


def test_a_print_that_no_longer_matches_the_record_is_refused(nest_build: Path) -> None:
    trial = start_nest_trial(nest_build)
    pass_all(trial)
    fill(trial, "use.json", lambda d: d.update(uses_counted=1, anything_wore=False))
    stl = Path(json.loads(nest_build.read_text())["parts"]["nest"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b" ")

    with pytest.raises(ValueError, match="no longer match"):
        complete_nest_trial(trial, disposition=PASS, material_profile_id="petg")


# --- a jig trial --------------------------------------------------------------------------------


def test_a_jig_trial_records_each_inserts_depth_and_offset(jig_build: Path) -> None:
    trial = start_jig_trial(jig_build)
    template = json.loads((trial / "insertion.json").read_text())

    assert sorted(template["inserts"]) == ["I1", "I2"]
    assert template["designed"]["depth_below_face_mm"] == 0.0
    pass_all(trial)

    def readings(data: dict[str, Any]) -> None:
        data["inserts"]["I1"].update(
            went_in_square=True,
            depth_below_face_mm=0.3,
            offset_from_pocket_centre_mm=0.15,
        )
        data["inserts"]["I2"].update(went_in_square=False, depth_below_face_mm=-0.2)

    fill(trial, "insertion.json", readings)
    record = json.loads(
        complete_jig_trial(
            trial, disposition=REVISE, material_profile_id="petg"
        ).read_text()
    )
    first, second = (
        record["insertion"]["inserts"]["I1"],
        record["insertion"]["inserts"]["I2"],
    )

    assert first["depth_error_mm"] == pytest.approx(0.3)
    assert first["went_in_square"] is True
    assert second["went_in_square"] is False
    assert second["depth_error_mm"] == pytest.approx(-0.2)
    assert second["offset_from_pocket_centre_mm"] is None
    assert "no temperature" in record["not_claimed"]


def test_an_insert_with_no_readings_is_left_out_and_none_taken_is_refused(
    jig_build: Path,
) -> None:
    trial = start_jig_trial(jig_build)
    pass_all(trial)

    with pytest.raises(ValueError, match="at least one measurement or reading"):
        complete_jig_trial(trial, disposition=PASS, material_profile_id="petg")

    fill(
        trial,
        "insertion.json",
        lambda d: d["inserts"]["I2"].update(went_in_square=True),
    )
    record = json.loads(
        complete_jig_trial(
            trial, disposition=PASS, material_profile_id="petg"
        ).read_text()
    )

    assert list(record["insertion"]["inserts"]) == ["I2"]


@pytest.mark.parametrize(
    ("entry", "error", "message"),
    [
        ({"went_in_square": "yes"}, TypeError, "true or false"),
        ({"depth_below_face_mm": "deep"}, TypeError, "must be a number"),
        ({"offset_from_pocket_centre_mm": -0.1}, ValueError, "from zero"),
    ],
)
def test_bad_insertion_readings_are_refused(
    jig_build: Path, entry: dict[str, Any], error: type[Exception], message: str
) -> None:
    trial = start_jig_trial(jig_build)
    pass_all(trial)
    fill(trial, "insertion.json", lambda d: d["inserts"]["I1"].update(entry))

    with pytest.raises(error, match=message):
        complete_jig_trial(trial, disposition=PASS, material_profile_id="petg")


def test_readings_for_an_insert_the_jig_does_not_have_are_refused(
    jig_build: Path,
) -> None:
    trial = start_jig_trial(jig_build)
    pass_all(trial)
    fill(
        trial,
        "insertion.json",
        lambda d: d["inserts"].update({"I9": {"went_in_square": True}}),
    )

    with pytest.raises(ValueError, match=r"readings for \['I9'\]"):
        complete_jig_trial(trial, disposition=PASS, material_profile_id="petg")


# --- the commands -------------------------------------------------------------------------------


def test_the_trial_commands_start_and_complete_a_nest_trial(nest_build: Path) -> None:
    code, started = run("nest", "trial", "start", "--build-record", str(nest_build))

    assert code == 0 and Path(started["use"]).name == "use.json"
    trial = Path(started["trial"])
    pass_all(trial)
    fill(trial, "use.json", lambda d: d.update(uses_counted=5, anything_wore=False))
    code, done = run(
        "nest",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0 and done["passed"] is True
    assert Path(done["trial_record"]).name == "nest-trial.json"


def test_the_trial_commands_start_and_complete_a_jig_trial(jig_build: Path) -> None:
    code, started = run("jig", "trial", "start", "--build-record", str(jig_build))

    assert code == 0 and Path(started["insertion"]).name == "insertion.json"
    trial = Path(started["trial"])
    pass_all(trial)
    fill(
        trial,
        "insertion.json",
        lambda d: d["inserts"]["I1"].update(went_in_square=True),
    )
    code, done = run(
        "jig",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0 and done["passed"] is True
    assert Path(done["trial_record"]).name == "jig-trial.json"

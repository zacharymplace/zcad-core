"""A housing's build record and its wear trials."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.housing_file import housing_template
from zcad_core.features.housing_trial import (
    BUILD_RECORD,
    TRIAL_RECORD,
    complete_housing_trial,
    start_housing_trial,
)
from zcad_core.hardware import board_template
from zcad_core.hardware.wearables import capture_template

STRAP = {
    "kind": "strap",
    "strap_width_mm": 20.0,
    "bar_diameter_mm": 1.8,
    "source": "my strap, measured",
}
CLIP = {"kind": "clip", "belt_thickness_mm": 4.0, "source": "my belt, measured"}
LANYARD = {"kind": "lanyard", "cord_diameter_mm": 3.0, "source": "my cord"}


def write_capture(directory: Path, **changes: Any) -> Path:
    data = capture_template("dexcom-g7")
    del data["needs_review"]
    data.update(
        measured_by="A. Tester",
        measured_on="2026-10-01",
        caliper="digital caliper, 0.01 mm",
        orientation="face up",
        source="one device",
        edge_features_checked=True,
        outline={"type": "rounded_rectangle", "radius_mm": 4.0},
    )
    data.update(changes)
    path = directory / "capture.json"
    path.write_text(json.dumps(data))

    return path


def write_housing(
    directory: Path, style: str, input_file: Path, wear: list[Any]
) -> Path:
    data = housing_template(style, input_file)
    data["source"] = "a housing for tests"
    data["wear"] = wear
    path = directory / "housing.json"
    path.write_text(json.dumps(data))

    return path


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def build(tmp_path: Path, style: str = "cradle", wear: list[Any] | None = None) -> Path:
    if style == "cradle":
        source = write_capture(tmp_path, mass={"value_g": 8.0, "source": "my scale"})
    else:
        source = tmp_path / "board.json"
        source.write_text(json.dumps(board_template()))

    housing = write_housing(tmp_path, style, source, wear or [])
    out = tmp_path / "out"
    code, output = run(
        "housing",
        "build",
        "--housing-file",
        str(housing),
        "--output-directory",
        str(out),
    )

    assert code == 0, output

    return Path(output["build_record"])


def fill(trial: Path, **wear: Any) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "pass"

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["outer_length_mm"]["value_mm"] = 30.5
    (trial / "measurements.json").write_text(json.dumps(measurements))
    readings = json.loads((trial / "wear.json").read_text())

    for key, value in wear.items():
        readings[key].update(value)

    (trial / "wear.json").write_text(json.dumps(readings))


def complete(trial: Path, disposition: str = "pass") -> dict[str, Any]:
    path = complete_housing_trial(
        trial,
        disposition=EnclosureTrialDisposition(disposition),
        material_profile_id="petg",
    )

    return cast(dict[str, Any], json.loads(path.read_text()))


def test_a_build_writes_a_record_that_names_its_inputs_and_parts(
    tmp_path: Path,
) -> None:
    record = json.loads(build(tmp_path, wear=[STRAP, CLIP]).read_text())

    assert record["style"] == "cradle"
    assert len(record["houses"]["sha256"]) == 64
    assert len(record["housing_file"]["sha256"]) == 64
    assert [w["kind"] for w in record["wear"]] == ["strap", "clip"]
    assert record["wear"][0]["source"] == "my strap, measured"
    assert record["skin_side"]["edge_radius_mm"] == 0.8
    assert record["device_mass_g"] == 8.0
    assert set(record["parts"]) == {"housing"}
    assert "strap_fits" in record["checks"] and "clip_fits" in record["checks"]
    assert record["nominal_measurements_mm"]["outer_length_mm"] == pytest.approx(
        30.4, abs=0.01
    )
    assert any("skin" in line for line in record["not_claimed"])


def test_a_case_asks_for_its_lid_and_its_board(tmp_path: Path) -> None:
    record = json.loads(build(tmp_path, "case").read_text())

    assert record["checks"][2:4] == ["board_seats", "lid_closes"]
    assert "lid_thickness_mm" in record["nominal_measurements_mm"]
    assert record["device_mass_g"] is None


def test_a_trial_lists_only_what_this_housing_has(tmp_path: Path) -> None:
    trial = start_housing_trial(build(tmp_path, wear=[STRAP, CLIP, LANYARD]))
    readings = json.loads((trial / "wear.json").read_text())

    assert trial.name == "trial-001"
    assert set(readings["pull_tests"]) == {"strap", "clip", "lanyard"}
    assert readings["retention"]["device_mass_g"] == 8.0
    assert "no limit" in readings["not_a_limit"]
    assert set(json.loads((trial / "observations.json").read_text())) >= {
        "device_seats",
        "lanyard_fits",
    }
    assert start_housing_trial(trial.parent.parent / BUILD_RECORD).name == "trial-002"


def test_a_filled_in_trial_keeps_the_readings_and_draws_no_conclusion(
    tmp_path: Path,
) -> None:
    trial = start_housing_trial(build(tmp_path, wear=[STRAP]))
    fill(
        trial,
        retention={"retention_force_n": 14.5},
        pull_tests={"strap": {"pull_n": 60.0, "what_gave": "the spring bar bent"}},
        wearing={
            "wears_counted": 30,
            "anything_wore_or_cracked": False,
            "skin_irritated": True,
            "notes": "red after a day",
        },
    )
    record = complete(trial)

    assert record["passed"] is True
    assert record["wear"]["retention_force_n"] == 14.5
    assert record["wear"]["pull_tests"][0]["what_gave"] == "the spring bar bent"
    assert record["wear"]["wearing"]["skin_irritated"] is True
    assert record["measurements"][0]["deviation_mm"] == pytest.approx(0.1, abs=0.01)
    assert (trial / TRIAL_RECORD).is_file()

    with pytest.raises(FileExistsError):
        complete(trial)


@pytest.mark.parametrize(
    ("wear", "message"),
    [
        ({"retention": {"retention_force_n": -3}}, "above zero"),
        ({"pull_tests": {"strap": {"pull_n": 20.0}}}, "what_gave"),
        ({"pull_tests": {"clip": {"pull_n": 20.0, "what_gave": "x"}}}, "not built"),
        ({"wearing": {"wears_counted": 0}}, "whole number"),
        ({"wearing": {"anything_wore_or_cracked": False}}, "need wears_counted"),
        ({"wearing": {"skin_irritated": False}}, "need wears_counted"),
        (
            {"wearing": {"wears_counted": 5, "skin_irritated": False}},
            "anything_wore_or_cracked",
        ),
        (
            {"wearing": {"wears_counted": 5, "anything_wore_or_cracked": "no"}},
            "true or false",
        ),
    ],
)
def test_a_reading_that_cannot_be_right_is_refused(
    tmp_path: Path, wear: dict[str, Any], message: str
) -> None:
    trial = start_housing_trial(build(tmp_path, wear=[STRAP]))
    fill(trial, **wear)

    with pytest.raises((ValueError, TypeError), match=message):
        complete(trial)


def test_a_trial_needs_a_reading_unless_it_failed(tmp_path: Path) -> None:
    trial = start_housing_trial(build(tmp_path))
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "fail"

    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="at least one measurement or wear reading"):
        complete(trial, "revise")

    assert complete(trial, "fail")["passed"] is False


def test_a_passing_trial_cannot_have_a_failed_check(tmp_path: Path) -> None:
    trial = start_housing_trial(build(tmp_path))
    fill(trial)
    observations = json.loads((trial / "observations.json").read_text())
    observations["nothing_rattles"]["result"] = "fail"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete(trial, "pass")

    assert complete(trial, "revise")["failed_checks"] == ["nothing_rattles"]


def test_a_trial_is_refused_if_the_parts_changed(tmp_path: Path) -> None:
    record = build(tmp_path)
    trial = start_housing_trial(record)
    fill(trial)
    stl = Path(next(iter(json.loads(record.read_text())["parts"].values()))["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"x")

    with pytest.raises(ValueError, match="no longer match"):
        complete(trial)


def test_the_commands_start_and_complete_a_trial(tmp_path: Path) -> None:
    record = build(tmp_path)
    code, started = run("housing", "trial", "start", "--build-record", str(record))
    trial = Path(started["trial"])

    assert code == 0 and Path(started["wear"]).is_file()
    fill(trial)
    code, done = run(
        "housing",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0 and done["passed"] is True

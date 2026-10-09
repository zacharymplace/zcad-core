"""Trials of Gridfinity parts: recording a print and what it fitted, and verifying it."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.gridfinity_trial import (
    complete_gridfinity_trial,
    gridfinity_checks,
    gridfinity_verification,
    start_gridfinity_trial,
)

PASS = EnclosureTrialDisposition.PASS
ENGINE_PLATE = {"kind": "baseplate", "made_by": "this engine", "name": ""}
REBUILT_PLATE = {
    "kind": "baseplate",
    "made_by": "another generator",
    "name": "Gridfinity Rebuilt 4x4 baseplate, printed from its OpenSCAD file",
}


def build(capsys: pytest.CaptureFixture[str], tmp_path: Path, *args: str) -> Path:
    output = tmp_path / "part"
    code = main(["gridfinity", *args, "--output-directory", str(output)])
    capsys.readouterr()
    assert code == 0

    return output / "gridfinity.json"


@pytest.fixture
def bin_record(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> Path:
    return build(capsys, tmp_path, "bin", "--units", "1x1", "--height", "2", "--no-lip")


def fill(trial: Path, *, result: str = "pass", **fit: Any) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations))
    readings = json.loads((trial / "fit.json").read_text())
    readings.update(fit)
    (trial / "fit.json").write_text(json.dumps(readings))


def complete(trial: Path, disposition: EnclosureTrialDisposition = PASS) -> Path:
    return complete_gridfinity_trial(
        trial, disposition=disposition, material_profile_id="petg"
    )


def test_the_checks_follow_the_part_and_its_options() -> None:
    assert gridfinity_checks("bin", {"lip": False}) == [
        "printed_cleanly",
        "seats_flat",
        "lifts_out",
    ]
    assert gridfinity_checks(
        "bin",
        {"lip": True, "divisions": [3, 1], "fitted": {"x": 1}, "magnets": True},
    )[3:] == ["stacks", "compartments_clean", "object_fits", "magnets_seat"]
    assert gridfinity_checks("baseplate", {"pieces": [[1, 2]], "screws": True}) == [
        "printed_cleanly",
        "holds_a_bin",
        "pieces_lie_flat",
        "screws_fit",
    ]


def test_a_bin_is_verified_on_two_passes_and_one_with_another_generator(
    bin_record: Path,
) -> None:
    built = json.loads(bin_record.read_text())

    assert built["design_name"] == "gridfinity-bin-1x1x2"
    assert built["checks"] == ["printed_cleanly", "seats_flat", "lifts_out"]
    assert built["nominal_measurements_mm"]["overall_width_mm"] == 41.5

    first = start_gridfinity_trial(bin_record)
    fit = json.loads((first / "fit.json").read_text())

    assert fit["mated_with"]["kind"] == "baseplate"

    fill(first, mated_with=ENGINE_PLATE, feel="right", seats_flat=True, lifts_out=True)
    written = json.loads(complete(first).read_text())

    assert written["passed"]
    assert written["fit"]["feel"] == "right"
    assert not gridfinity_verification(bin_record)["verified"]

    second = start_gridfinity_trial(bin_record)
    fill(second, mated_with=REBUILT_PLATE, feel="tight", seats_flat=True)
    complete(second)
    status = gridfinity_verification(bin_record)

    assert status["verified"]
    assert status["passing_with_another_generator"] == 1
    assert status["trials"][1]["mated_with"]["name"].startswith("Gridfinity Rebuilt")


@pytest.mark.parametrize(
    ("fit", "error", "message"),
    [
        ({}, ValueError, "names what the part was fitted with"),
        (
            {"mated_with": {**REBUILT_PLATE, "name": " "}},
            ValueError,
            "needs its name and where it came from",
        ),
        ({"mated_with": {**ENGINE_PLATE, "made_by": "me"}}, ValueError, "made_by must"),
        (
            {"mated_with": ENGINE_PLATE, "feel": "snug"},
            ValueError,
            "feel must be one of",
        ),
        ({"mated_with": ENGINE_PLATE, "stacks": "yes"}, TypeError, "true or false"),
    ],
)
def test_fit_readings_that_cannot_be_right_are_refused(
    bin_record: Path, fit: dict[str, Any], error: type[Exception], message: str
) -> None:
    trial = start_gridfinity_trial(bin_record)
    fill(trial, **fit)

    with pytest.raises(error, match=message):
        complete(trial)


def test_a_passing_trial_cannot_fail_a_check_nor_be_written_twice(
    bin_record: Path,
) -> None:
    trial = start_gridfinity_trial(bin_record)
    fill(trial, result="fail", mated_with=ENGINE_PLATE, feel="loose")

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete(trial)

    complete(trial, EnclosureTrialDisposition.REVISE)

    with pytest.raises(FileExistsError, match="already completed"):
        complete(trial, EnclosureTrialDisposition.FAIL)


def test_a_reprinted_part_is_not_the_part_the_trial_is_of(bin_record: Path) -> None:
    stl = Path(json.loads(bin_record.read_text())["parts"]["bin"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"\n")
    trial = start_gridfinity_trial(bin_record)
    fill(trial, mated_with=ENGINE_PLATE)

    with pytest.raises(ValueError, match="no longer match the build record"):
        complete(trial)


def test_a_baseplate_trial_names_the_bin_it_held(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    record = build(capsys, tmp_path, "baseplate", "--units", "1x1")
    trial = start_gridfinity_trial(record)

    assert json.loads((trial / "fit.json").read_text())["mated_with"]["kind"] == "bin"
    assert list(json.loads((trial / "observations.json").read_text())) == [
        "printed_cleanly",
        "holds_a_bin",
    ]


def test_the_trial_commands_start_complete_and_report(
    capsys: pytest.CaptureFixture[str], bin_record: Path
) -> None:
    assert (
        main(["gridfinity", "trial", "start", "--build-record", str(bin_record)]) == 0
    )
    trial = Path(json.loads(capsys.readouterr().out)["trial"])
    fill(trial, mated_with=REBUILT_PLATE, feel="right")

    code = main(
        [
            "gridfinity",
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--disposition",
            "pass",
        ]
    )
    completed = json.loads(capsys.readouterr().out)

    assert code == 0
    assert completed["verification"]["passing_with_another_generator"] == 1

    assert (
        main(["gridfinity", "trial", "status", "--build-record", str(bin_record)]) == 0
    )
    status = json.loads(capsys.readouterr().out)

    assert status == {**status, "verified": False, "passing_trials": 1}


@pytest.fixture
def sliced(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What the slicer was asked for, in place of Bambu Studio."""

    asked: dict[str, Any] = {}

    def slice_models(models: list[Path], output: Path, **options: Any) -> Any:
        asked.update(models=models, output=output, **options)
        return SimpleNamespace(
            gcode_path=output / "plate_1.gcode",
            summary={
                "estimated_print_time_seconds": 1500,
                "filament_used_g": 21.04,
                "slicer_warning": "",
            },
        )

    monkeypatch.setattr("zcad_core.cli.gridfinity.slice_models", slice_models)

    return asked


def test_a_sliced_part_is_sliced_as_exported_and_its_first_trial_opened(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, sliced: dict[str, Any]
) -> None:
    output = tmp_path / "part"
    command = ["gridfinity", "bin", "--units", "1x1", "--height", "2", "--no-lip"]

    assert main([*command, "--output-directory", str(output), "--slice"]) == 0
    printed = json.loads(capsys.readouterr().out)["print"]
    record = json.loads((output / "gridfinity.json").read_text())

    assert [str(model) for model in sliced["models"]] == [
        part["stl_path"] for part in record["parts"].values()
    ]
    assert sliced["output"] == output / "slice"
    assert sliced["summary_fields"]["design_name"] == "gridfinity-bin-1x1x2"
    assert (printed["estimated_print_minutes"], printed["filament_used_g"]) == (
        25,
        21.0,
    )
    assert Path(printed["trial"]) == output / "trials" / "trial-001"
    assert (output / "trials" / "trial-001" / "fit.json").is_file()
    assert (printed["copies"], sliced["summary_fields"]["copies"]) == (1, 1)


def test_a_pair_of_lipped_bins_goes_on_one_plate_for_the_stacking_check(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, sliced: dict[str, Any]
) -> None:
    output = tmp_path / "pair"
    command = ["gridfinity", "bin", "--units", "1x1", "--height", "2", "--slice"]

    assert main([*command, "--copies", "2", "--output-directory", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)["print"]
    (stl,) = (
        part["stl_path"]
        for part in json.loads((output / "gridfinity.json").read_text())[
            "parts"
        ].values()
    )
    observations = json.loads(
        (output / "trials" / "trial-001" / "observations.json").read_text()
    )

    assert [str(model) for model in sliced["models"]] == [stl, stl]
    assert (printed["copies"], sliced["summary_fields"]["copies"]) == (2, 2)
    assert "stacks" in observations


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--copies", "2"], "add --slice"),
        (["--copies", "0", "--slice"], "--copies must be 1 or more"),
    ],
)
def test_copies_are_only_for_a_sliced_plate(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    options: list[str],
    message: str,
) -> None:
    output = tmp_path / "part"
    command = ["gridfinity", "bin", "--units", "1x1", "--height", "2", *options]

    assert main([*command, "--output-directory", str(output)]) == 1
    assert message in capsys.readouterr().err
    assert not output.exists()


def test_a_baseplate_in_pieces_is_not_sliced_onto_one_plate(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "plate"
    command = ["gridfinity", "baseplate", "--units", "5x1", "--slice"]

    assert main([*command, "--output-directory", str(output)]) == 1
    assert "a baseplate in pieces needs a plate for each" in capsys.readouterr().err
    assert not output.exists()


def test_a_refused_rebuild_leaves_the_earlier_bin_as_it_was(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Before, the second build replaced the parts and then refused to replace
    # the record, which no longer matched them.
    output = tmp_path / "part"
    command = ["gridfinity", "bin", "--units", "1x1", "--no-lip"]

    assert main([*command, "--height", "2", "--output-directory", str(output)]) == 0
    capsys.readouterr()
    before = {path.name: path.read_bytes() for path in output.glob("*.stl")}

    assert main([*command, "--height", "3", "--output-directory", str(output)]) == 1
    assert "nothing was written" in capsys.readouterr().err
    assert {path.name: path.read_bytes() for path in output.glob("*.stl")} == before

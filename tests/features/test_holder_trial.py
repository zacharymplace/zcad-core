"""Trials of an object holder: recording a print of it, and verifying it on two that pass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.holder_file import holder_template
from zcad_core.features.holder_trial import (
    complete_holder_trial,
    holder_checks,
    holder_verification,
    start_holder_trial,
)

BRICK: dict[str, Any] = {
    "schema_version": "1.0.0",
    "units": "mm",
    "device": "custom",
    "name": "USB power brick",
    "measured_by": "Test",
    "measured_on": "2026-10-06",
    "caliper": "digital caliper, 0.01 mm",
    "orientation": "label up, cable at the south edge",
    "source": "one brick, measured three times across each face",
    "body_readings": {
        "length_mm": [80.0] * 3,
        "width_mm": [50.0] * 3,
        "thickness_mm": [30.0] * 3,
    },
    "outline": "rectangle",
    "edge_features": [
        {
            "identifier": "cable",
            "edge": "south",
            "center_offset_mm": 0.0,
            "width_mm": 8.0,
        }
    ],
    "edge_features_checked": True,
    "face_features": [],
    "mass": {"value_g": 210.0, "source": "kitchen scale"},
}


def build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    capture = tmp_path / "brick.json"
    capture.write_text(json.dumps(BRICK), encoding="utf-8")
    data = holder_template(capture)
    data.update(
        {
            "identifier": "BRICK_HOLDER",
            "name": "Power brick holder",
            "source": "the desk's power brick",
            "mount": {"type": "keyhole"},
        }
    )
    holder_file = tmp_path / "holder.json"
    holder_file.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out"
    code = main(
        [
            "holder",
            "build",
            "--holder-file",
            str(holder_file),
            "--output-directory",
            str(output),
        ]
    )
    capsys.readouterr()
    assert code == 0

    return output / "holder.json"


def fill(trial: Path, *, result: str = "pass", **use: Any) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["pocket_width_mm"]["value_mm"] = 80.3
    (trial / "measurements.json").write_text(json.dumps(measurements))
    readings = json.loads((trial / "use.json").read_text())
    readings.update(use)
    (trial / "use.json").write_text(json.dumps(readings))


def test_the_checks_follow_the_mount_the_openings_and_the_tabs() -> None:
    assert holder_checks(mount="screws", openings=False, tabs=False) == [
        "printed_cleanly",
        "object_goes_in",
        "object_lifts_out",
        "object_sits_square",
        "screws_seat_flush",
    ]
    assert holder_checks(mount="pegboard", openings=True, tabs=True)[-3:] == [
        "features_reachable",
        "tabs_hold",
        "pegs_hang",
    ]


def test_a_trial_records_the_print_and_two_passes_verify_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = build(tmp_path, capsys)
    built = json.loads(record.read_text())

    assert built["checks"][-2:] == ["features_reachable", "keyholes_hang"]
    assert built["nominal_measurements_mm"]["pocket_width_mm"] == 80.4

    trial = start_holder_trial(record)
    use = json.loads((trial / "use.json").read_text())

    assert use["carried"] == {"mass_g": 210.0, "source": "kitchen scale"}

    fill(
        trial,
        mounted_on="plasterboard, two plugs",
        days_in_use=14,
        uses_counted=30,
        stayed_put_when_knocked=True,
        anything_crept_or_cracked=False,
    )
    written = json.loads(
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        ).read_text()
    )

    assert written["passed"]
    assert written["use"]["carried_mass_g"] == 210.0
    assert written["use"]["mounted_on"] == "plasterboard, two plugs"
    assert written["measurements"][0]["deviation_mm"] == pytest.approx(-0.1)
    assert not holder_verification(record)["verified"]

    second = start_holder_trial(record)
    fill(second, uses_counted=5)
    complete_holder_trial(
        second, disposition=EnclosureTrialDisposition.PASS, material_profile_id="petg"
    )
    status = holder_verification(record)

    assert status["verified"]
    assert status["passing_trials"] == 2


def test_a_passing_trial_cannot_fail_a_check_nor_be_written_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = build(tmp_path, capsys)
    trial = start_holder_trial(record)
    fill(trial, result="fail", uses_counted=3)

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

    complete_holder_trial(
        trial, disposition=EnclosureTrialDisposition.REVISE, material_profile_id="petg"
    )

    with pytest.raises(FileExistsError, match="already completed"):
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.FAIL,
            material_profile_id="petg",
        )

    assert holder_verification(record)["passing_trials"] == 0


@pytest.mark.parametrize(
    ("use", "error", "message"),
    [
        ({"uses_counted": 0}, ValueError, "uses_counted must be a whole number from 1"),
        ({"days_in_use": -1}, ValueError, "days_in_use must be at least 0"),
        ({"stayed_put_when_knocked": "yes"}, TypeError, "must be true or false"),
        ({"mounted_on": " "}, ValueError, "mounted_on must say"),
    ],
)
def test_use_readings_that_cannot_be_right_are_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    use: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    trial = start_holder_trial(build(tmp_path, capsys))
    fill(trial, **use)

    with pytest.raises(error, match=message):
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_reprinted_part_is_not_the_part_the_trial_is_of(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = build(tmp_path, capsys)
    stl = Path(json.loads(record.read_text())["parts"]["holder"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"\n")
    trial = start_holder_trial(record)
    fill(trial, uses_counted=1)

    with pytest.raises(ValueError, match="no longer match the build record"):
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_rebuilt_holder_starts_with_no_passing_trials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = build(tmp_path, capsys)

    for _ in range(2):
        trial = start_holder_trial(record)
        fill(trial, uses_counted=1)
        complete_holder_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

    assert holder_verification(record)["verified"]

    built = json.loads(record.read_text())
    built["settings"]["front_mm"] = 30.0
    record.write_text(json.dumps(built))
    status = holder_verification(record)

    assert not status["verified"]
    assert [t["of_this_build"] for t in status["trials"]] == [False, False]


def test_the_trial_commands_start_complete_and_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = build(tmp_path, capsys)
    code = main(["holder", "trial", "start", "--build-record", str(record)])
    started = json.loads(capsys.readouterr().out)

    assert code == 0
    trial = Path(started["trial"])
    fill(trial, uses_counted=2)
    code = main(
        [
            "holder",
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
    assert completed["passed"]
    assert completed["verification"]["passing_trials"] == 1

    code = main(["holder", "trial", "status", "--build-record", str(record)])
    status = json.loads(capsys.readouterr().out)

    assert code == 0
    assert status == {**status, "verified": False, "needed": 2}


def test_a_refused_rebuild_leaves_the_earlier_holder_as_it_was(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = build(tmp_path, capsys).parent
    before = {path.name: path.read_bytes() for path in output.glob("*.stl")}
    command = [
        "holder",
        "build",
        "--holder-file",
        str(tmp_path / "holder.json"),
        "--output-directory",
        str(output),
    ]

    assert main(command) == 1
    assert "nothing was written" in capsys.readouterr().err
    assert {path.name: path.read_bytes() for path in output.glob("*.stl")} == before

"""Enclosure build records and print trials."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.assemblies import (
    Placement,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.features import Enclosure, build_enclosure
from zcad_core.features.enclosure_trial import (
    EnclosureCheck,
    EnclosureTrialDisposition,
    applicable_checks,
    complete_enclosure_trial,
    nominal_measurements,
    start_enclosure_trial,
    write_build_record,
)
from zcad_core.hardware import get_board, get_display

BOARD = get_board("RASPBERRY_PI_PICO_2")
DISPLAY = get_display("ADAFRUIT_OLED_128X64_1_3IN")


@pytest.fixture(scope="module")
def enclosure() -> Enclosure:
    assembly = build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )

    return build_enclosure(assembly, board=BOARD, display=DISPLAY)


def build_record(enclosure: Enclosure, directory: Path) -> Path:
    parts = {}

    for name in ("base", "lid"):
        parts[name] = directory / f"{name}.stl"
        parts[name].write_text(f"solid {name}\n", encoding="utf-8")

    return write_build_record(
        directory,
        enclosure=enclosure,
        design_name="pico-case",
        board_identifier=BOARD.identifier,
        display=DISPLAY,
        part_stls=parts,
        printer_profile_id="bambu-lab-a1-mini",
    )


def fill(trial: Path, *, result: str = "pass", measure: bool = True) -> None:
    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    for entry in observations.values():
        entry["result"] = result
    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")

    if measure:
        measurements = json.loads((trial / "measurements.json").read_text("utf-8"))
        measurements["wall_thickness_mm"]["value_mm"] = 2.1
        (trial / "measurements.json").write_text(json.dumps(measurements), "utf-8")


def test_build_record_lists_the_checks_and_nominals(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    record = json.loads(build_record(enclosure, tmp_path).read_text("utf-8"))

    assert record["display_support"] == "posts"
    assert EnclosureCheck.DISPLAY_ALIGNED.value in record["checks"]
    # The Pico 2 has no part reached through a wall besides its cable.
    assert EnclosureCheck.ACCESS_OPENINGS_CLEAR.value not in record["checks"]
    nominals = record["nominal_measurements_mm"]
    assert nominals["wall_thickness_mm"] == 2.0
    assert nominals["lid_hole_diameter_mm"] == 3.4
    assert nominals["display_window_width_mm"] == pytest.approx(29.42 + 0.8)
    assert set(record["parts"]) == {"base", "lid"}


def test_build_record_is_never_replaced(enclosure: Enclosure, tmp_path: Path) -> None:
    build_record(enclosure, tmp_path)

    with pytest.raises(FileExistsError, match="Refusing to overwrite build record"):
        build_record(enclosure, tmp_path)


def test_checks_follow_the_hardware() -> None:
    uno = get_board("ARDUINO_UNO_R4_WIFI")
    enclosure = build_enclosure(
        build_board_assembly(
            board=uno, board_placement=Placement(), connector_access_clearance_mm=2.0
        ),
        board=uno,
    )
    checks = applicable_checks(enclosure)

    # The barrel jack has its own opening; there is no display.
    assert EnclosureCheck.ACCESS_OPENINGS_CLEAR in checks
    assert EnclosureCheck.DISPLAY_ALIGNED not in checks
    assert "display_window_width_mm" not in nominal_measurements(enclosure, None)


def test_trials_are_numbered_and_templated(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    record = build_record(enclosure, tmp_path)

    first = start_enclosure_trial(record)
    second = start_enclosure_trial(record)

    assert (first.name, second.name) == ("trial-001", "trial-002")
    observations = json.loads((first / "observations.json").read_text("utf-8"))
    assert {entry["result"] for entry in observations.values()} == {"pending"}
    assert all(entry["guidance"] for entry in observations.values())
    measurements = json.loads((first / "measurements.json").read_text("utf-8"))
    assert measurements["wall_thickness_mm"] == {
        "nominal_mm": 2.0,
        "value_mm": None,
        "notes": "",
    }


def test_passing_trial_records_measured_deviation(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(build_record(enclosure, tmp_path))
    fill(trial)

    path = complete_enclosure_trial(
        trial, disposition=EnclosureTrialDisposition.PASS, material_profile_id="petg"
    )
    record = json.loads(path.read_text("utf-8"))

    assert record["passed"]
    assert record["failed_checks"] == []
    (measurement,) = record["measurements"]
    assert measurement["deviation_mm"] == pytest.approx(0.1)
    assert record["design_name"] == "pico-case"

    with pytest.raises(FileExistsError, match="Trial already completed"):
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_completion_rules(enclosure: Enclosure, tmp_path: Path) -> None:
    record = build_record(enclosure, tmp_path)

    pending = start_enclosure_trial(record)
    with pytest.raises(ValueError, match="must be pass or fail, not 'pending'"):
        complete_enclosure_trial(
            pending,
            disposition=EnclosureTrialDisposition.FAIL,
            material_profile_id="petg",
        )

    failed = start_enclosure_trial(record)
    fill(failed, result="fail")
    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_enclosure_trial(
            failed,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

    unmeasured = start_enclosure_trial(record)
    fill(unmeasured, measure=False)
    with pytest.raises(ValueError, match="needs at least one measurement"):
        complete_enclosure_trial(
            unmeasured,
            disposition=EnclosureTrialDisposition.REVISE,
            material_profile_id="petg",
        )
    # A failed print needs no measurements.
    complete_enclosure_trial(
        unmeasured,
        disposition=EnclosureTrialDisposition.FAIL,
        material_profile_id="petg",
    )


def test_refuses_a_trial_of_changed_parts(enclosure: Enclosure, tmp_path: Path) -> None:
    trial = start_enclosure_trial(build_record(enclosure, tmp_path))
    fill(trial)
    (tmp_path / "lid.stl").write_text("solid changed\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match=r"no longer match the build record: \['lid'\]"
    ):
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

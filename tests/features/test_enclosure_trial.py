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
from zcad_core.cli import main
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
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


# --- a hinged or sliding lid ------------------------------------------------------------------


@pytest.fixture(scope="module")
def hinged() -> Enclosure:
    assembly = build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )

    return build_enclosure(
        assembly,
        board=BOARD,
        display=DISPLAY,
        design=EnclosureDesign(lid_attachment="hinge", bottom_clearance_mm=6.0),
    )


@pytest.fixture(scope="module")
def slid() -> Enclosure:
    plain = build_board_assembly(
        board=BOARD, board_placement=Placement(), connector_access_clearance_mm=2.0
    )

    return build_enclosure(
        plain, board=BOARD, design=EnclosureDesign(lid_attachment="slide")
    )


def build_lid_record(enclosure: Enclosure, directory: Path) -> Path:
    parts = {}

    for name in ("base", "lid"):
        parts[name] = directory / f"{name}.stl"
        parts[name].write_text(f"solid {name}\n", encoding="utf-8")

    return write_build_record(
        directory,
        enclosure=enclosure,
        design_name="lid-case",
        board_identifier=BOARD.identifier,
        display=None,
        part_stls=parts,
        printer_profile_id="bambu-lab-a1-mini",
    )


def write_lid(trial: Path, **values: object) -> None:
    lid = json.loads((trial / "lid.json").read_text("utf-8"))
    lid.update(values)
    (trial / "lid.json").write_text(json.dumps(lid), "utf-8")


def test_a_hinged_lid_adds_its_checks_and_a_pin_hole_to_measure(
    hinged: Enclosure,
) -> None:
    names = {check.value for check in applicable_checks(hinged)}

    assert {"hinge_swings_free", "catch_holds_lid"} <= names
    assert not names & {"lid_slides_free", "detent_holds_lid"}
    # M3's 3.4 mm clearance hole, with no compensation in the default design.
    assert nominal_measurements(hinged, None)["hinge_pin_hole_diameter_mm"] == 3.4


def test_a_sliding_lid_adds_its_checks_and_a_clearance_to_measure(
    slid: Enclosure,
) -> None:
    names = {check.value for check in applicable_checks(slid)}

    assert {"lid_slides_free", "detent_holds_lid"} <= names
    assert not names & {"hinge_swings_free", "catch_holds_lid"}
    assert nominal_measurements(slid, None)["slide_clearance_per_side_mm"] == 0.2


def test_a_screwed_lid_has_no_lid_record(enclosure: Enclosure, tmp_path: Path) -> None:
    record = json.loads(build_record(enclosure, tmp_path).read_text("utf-8"))

    assert record["lid"] is None

    trial = start_enclosure_trial(tmp_path / "enclosure.json")

    assert not (trial / "lid.json").exists()


def test_the_build_record_says_what_the_lid_was_designed_to_do(
    hinged: Enclosure, slid: Enclosure, tmp_path: Path
) -> None:
    (tmp_path / "h").mkdir()
    (tmp_path / "s").mkdir()
    hinge = json.loads(build_lid_record(hinged, tmp_path / "h").read_text("utf-8"))
    slide = json.loads(build_lid_record(slid, tmp_path / "s").read_text("utf-8"))

    assert hinge["lid"]["kind"] == "hinge" and hinge["lid"]["swing_degrees"] == 100.0
    assert (
        slide["lid"]["kind"] == "slide" and slide["lid"]["clearance_per_side_mm"] == 0.2
    )
    assert slide["lid"]["travel_mm"] > 0


def test_a_hinge_trial_records_the_swing_against_the_design(
    hinged: Enclosure, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(build_lid_record(hinged, tmp_path))
    template = json.loads((trial / "lid.json").read_text("utf-8"))

    assert template["designed"]["swing_degrees"] == 100.0
    assert template["swing_degrees_reached"] is None
    assert "protractor" in template["guidance"]

    fill(trial)
    write_lid(
        trial,
        pin_turns_freely=True,
        swing_degrees_reached=92.0,
        catch_release_force_n=4.5,
        openings_counted=200,
        damage_observed=False,
    )
    record = json.loads(
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        ).read_text("utf-8")
    )
    lid = record["lid"]

    assert lid["kind"] == "hinge"
    assert lid["swing_shortfall_degrees"] == 8.0
    assert lid["catch_release_force_n"] == 4.5
    assert lid["openings_counted"] == 200 and lid["damage_observed"] is False
    assert lid["designed"]["swing_degrees"] == 100.0


def test_a_slide_trial_records_the_force(slid: Enclosure, tmp_path: Path) -> None:
    trial = start_enclosure_trial(build_lid_record(slid, tmp_path))
    template = json.loads((trial / "lid.json").read_text("utf-8"))

    assert template["designed"]["clearance_per_side_mm"] == 0.2
    assert template["slide_force_n"] is None

    fill(trial)
    write_lid(trial, slide_force_n=6.0, openings_counted=50, damage_observed=True)
    record = json.loads(
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.REVISE,
            material_profile_id="petg",
        ).read_text("utf-8")
    )

    assert record["lid"]["slide_force_n"] == 6.0
    assert record["lid"]["damage_observed"] is True


def test_a_blank_lid_template_is_left_out_of_the_record(
    hinged: Enclosure, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(build_lid_record(hinged, tmp_path))
    fill(trial)
    record = json.loads(
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        ).read_text("utf-8")
    )

    assert record["lid"] is None


def test_a_lid_reading_alone_is_enough_to_complete_a_trial(
    slid: Enclosure, tmp_path: Path
) -> None:
    trial = start_enclosure_trial(build_lid_record(slid, tmp_path))
    fill(trial, measure=False)
    write_lid(trial, slide_force_n=3.0)
    record = json.loads(
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        ).read_text("utf-8")
    )

    assert record["lid"]["slide_force_n"] == 3.0


@pytest.mark.parametrize(
    ("values", "error", "message"),
    [
        ({"slide_force_n": -1.0}, ValueError, "above zero"),
        ({"slide_force_n": True}, ValueError, "above zero"),
        ({"slide_force_n": 3.0, "openings_counted": 0}, ValueError, "whole number"),
        ({"slide_force_n": 3.0, "openings_counted": 5}, TypeError, "true or false"),
        ({"slide_force_n": 3.0, "damage_observed": True}, ValueError, "needs openings"),
    ],
)
def test_a_lid_reading_that_cannot_be_right_is_refused(
    slid: Enclosure,
    tmp_path: Path,
    values: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    trial = start_enclosure_trial(build_lid_record(slid, tmp_path))
    fill(trial)
    write_lid(trial, **values)

    with pytest.raises(error, match=message):
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_swing_past_180_degrees_is_refused(hinged: Enclosure, tmp_path: Path) -> None:
    trial = start_enclosure_trial(build_lid_record(hinged, tmp_path))
    fill(trial)
    write_lid(trial, swing_degrees_reached=200.0)

    with pytest.raises(ValueError, match="cannot exceed 180"):
        complete_enclosure_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_the_trial_start_command_names_the_lid_file(
    hinged: Enclosure, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    record = build_lid_record(hinged, tmp_path)
    code = main(["enclosure", "trial", "start", "--build-record", str(record)])
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["lid"].endswith("lid.json") and Path(output["lid"]).is_file()


def _sliced_build(directory: Path) -> Path:
    """A build folder with a slice beside it: a G-code and one print copy,
    each recorded in the summary."""

    import hashlib

    slice_directory = directory / "slice"
    slice_directory.mkdir(parents=True)
    (directory / "print").mkdir()
    gcode = slice_directory / "plate_1.gcode"
    gcode.write_text("; plate\n", encoding="utf-8")
    model = directory / "print" / "case-lid.stl"
    model.write_text("solid lid\n", encoding="utf-8")
    summary = {
        "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "models": [
            {
                "path": str(model),
                "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            }
        ],
    }
    (slice_directory / "slice-summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )

    return model


def test_a_trial_records_the_slice_it_was_printed_from(tmp_path: Path) -> None:
    from zcad_core.features.enclosure_trial import _printed_slice

    _sliced_build(tmp_path)
    printed = _printed_slice(tmp_path)

    assert printed is not None
    assert len(printed["gcode_sha256"]) == 64
    assert printed["models"][0]["path"].endswith("case-lid.stl")
    assert _printed_slice(tmp_path / "never-sliced") is None


def test_a_trial_refuses_a_slice_that_no_longer_matches_its_summary(
    tmp_path: Path,
) -> None:
    from zcad_core.features.enclosure_trial import _printed_slice

    model = _sliced_build(tmp_path)
    model.write_text("solid another lid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="print/case-lid.stl"):
        _printed_slice(tmp_path)

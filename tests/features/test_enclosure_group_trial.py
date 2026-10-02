"""Group enclosure build records and print trials."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group_trial import (
    complete_group_trial,
    start_group_trial,
)
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.hardware import board_template

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
FAN = "NOCTUA_NF_A4X10_5V"


def write_board(directory: Path) -> Path:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data.pop("test_points", None)
    data["components"] = []
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def build(directory: Path, *args: str) -> tuple[Path, dict[str, Any]]:
    """Build a group through the command and give back its build record and the
    command's output."""

    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(
            [
                "enclosure-group",
                "build",
                "--output-directory",
                str(directory / "out"),
                "--printer-profile",
                str(PRINTER_PROFILE),
                *args,
            ]
        )

    assert code == 0
    output = json.loads(out.getvalue())

    return Path(output["build_record"]), cast(dict[str, Any], output)


def record_of(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text()))


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory.mktemp("pair"), "--bays", "pi5,pi5")[0]


@pytest.fixture(scope="module")
def hinged(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(
        tmp_path_factory.mktemp("hinged"),
        "--bays",
        "pi5,pi5",
        "--lid",
        "hinge",
        "--headroom-mm",
        "20",
    )[0]


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    directory = tmp_path_factory.mktemp("mixed")
    board = write_board(directory)
    record, _ = build(
        directory,
        "--bays",
        f"board:file={board}:align=front,fan:fan={FAN}:direction=out:divider=notch",
    )

    return record, board


def fill(trial: Path, *, result: str = "pass", measure: bool = True) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = result

    (trial / "observations.json").write_text(json.dumps(observations))

    if measure:
        measurements = json.loads((trial / "measurements.json").read_text())
        measurements["wall_thickness_mm"]["value_mm"] = 2.1
        (trial / "measurements.json").write_text(json.dumps(measurements))


# --- the build record ------------------------------------------------------------------------


def test_the_record_names_each_bay_as_placed(pair: Path) -> None:
    record = record_of(pair)

    assert record["design_name"] == "pi5-group-2bay"
    assert [b["kind"] for b in record["bays"]] == ["pi5", "pi5"]
    assert record["bays"][0]["slot_mm"][0] == 9.0
    assert record["bays"][1]["center_mm"][1] == record["bays"][0]["center_mm"][1]
    assert record["printer_profile_id"] == "bambu-lab-a1-mini"
    assert record["joint"]["face"] == "fractions"
    assert record["lid"] is None
    assert record["thermal"]["typical_w"] > 0


def test_the_records_parts_are_named_by_hash(pair: Path) -> None:
    parts = record_of(pair)["parts"]

    assert set(parts) == {"base", "lid"}

    for part in parts.values():
        stl = Path(part["stl_path"])

        assert hashlib.sha256(stl.read_bytes()).hexdigest() == part["stl_sha256"]


def test_a_board_bay_and_a_fan_bay_are_named_with_their_files_and_fan(
    mixed: tuple[Path, Path],
) -> None:
    record_path, board = mixed
    bays = record_of(record_path)["bays"]

    assert bays[0]["board"]["sha256"] == hashlib.sha256(board.read_bytes()).hexdigest()
    assert bays[0]["board"]["align"] == "front"
    assert bays[0]["divider"] is None
    assert bays[1]["fan"] == {"identifier": FAN, "direction": "out"}
    assert bays[1]["divider"]["notch"] is True
    assert [f["fan"] for f in record_of(record_path)["fans"]] == [FAN]


def test_the_checks_follow_the_box_and_each_bay(
    pair: Path, hinged: Path, mixed: tuple[Path, Path]
) -> None:
    pair_checks = record_of(pair)["checks"]

    assert pair_checks[:3] == [
        "parts_printed_cleanly",
        "inserts_installed",
        "lid_closes_flush",
    ]
    assert "bay-1-ports_reach" in pair_checks and "hinge_swings_free" not in pair_checks
    assert "hinge_swings_free" in record_of(hinged)["checks"]

    mixed_checks = record_of(mixed[0])["checks"]

    assert "bay-0-board_seats" in mixed_checks and "bay-1-fan_fits" in mixed_checks
    assert "bay-1-divider_fits" in mixed_checks
    assert "bay-1-board_seats" not in mixed_checks


def test_the_nominals_are_the_designed_dimensions(pair: Path) -> None:
    nominals = record_of(pair)["nominal_measurements_mm"]

    assert nominals["wall_thickness_mm"] == 2.0
    assert nominals["bay_0_slot_width_mm"] == pytest.approx(56.5)
    assert nominals["bay_0_standoff_height_mm"] == 4.0
    assert nominals["joint_gap_mm"] == 0.0
    assert nominals["base_outer_width_mm"] == pytest.approx(
        record_of(pair)["outer_size_mm"][0]
    )


def test_a_record_is_never_replaced(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    build(tmp_path, "--bays", "pi5")
    capsys.readouterr()
    code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            "pi5",
            "--output-directory",
            str(tmp_path / "out"),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )

    assert code == 1
    assert "Refusing to overwrite" in capsys.readouterr().err


# --- starting a trial ---------------------------------------------------------------------------


def test_a_trial_lists_the_records_checks_and_nominals(pair: Path) -> None:
    trial = start_group_trial(pair)
    observations = json.loads((trial / "observations.json").read_text())
    measurements = json.loads((trial / "measurements.json").read_text())

    assert list(observations) == record_of(pair)["checks"]
    assert all(entry["result"] == "pending" for entry in observations.values())
    assert "plug" in observations["bay-0-ports_reach"]["guidance"]
    assert set(measurements) == set(record_of(pair)["nominal_measurements_mm"])
    assert (trial / "thermal.json").is_file()
    # A screwed lid has no lid readings.
    assert not (trial / "lid.json").exists()


def test_a_hinged_group_trial_has_a_lid_file(hinged: Path) -> None:
    trial = start_group_trial(hinged)
    lid = json.loads((trial / "lid.json").read_text())

    assert lid["designed"]["swing_degrees"] == 100.0
    assert lid["swing_degrees_reached"] is None


def test_each_trial_gets_the_next_number(pair: Path) -> None:
    first, second = start_group_trial(pair).name, start_group_trial(pair).name

    assert first != second and second > first


# --- completing it ------------------------------------------------------------------------------


def passing(directory: Path, *args: str) -> tuple[Path, Path]:
    record, _ = build(directory, *args)
    trial = start_group_trial(record)
    fill(trial)

    return record, trial


def test_a_filled_in_trial_is_recorded_with_its_deviations(tmp_path: Path) -> None:
    _, trial = passing(tmp_path, "--bays", "pi5")
    path = complete_group_trial(
        trial,
        disposition=EnclosureTrialDisposition.PASS,
        material_profile_id="petg",
        notes="first print",
    )
    record = record_of(path)

    assert record["passed"] is True and record["failed_checks"] == []
    (measurement,) = record["measurements"]

    assert measurement["name"] == "wall_thickness_mm"
    assert measurement["deviation_mm"] == pytest.approx(0.1)
    assert record["design_name"] == "pi5-group-1bay"
    assert record["build_record_sha256"]

    with pytest.raises(FileExistsError, match="already completed"):
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_completion_rules(tmp_path: Path) -> None:
    _, trial = passing(tmp_path, "--bays", "pi5")
    observations = json.loads((trial / "observations.json").read_text())
    observations["bay-0-board_seats"]["result"] = "fail"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

    observations["bay-0-board_seats"]["result"] = "pending"
    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="must be pass or fail"):
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.FAIL,
            material_profile_id="petg",
        )


def test_a_trial_needs_a_reading_unless_it_failed(tmp_path: Path) -> None:
    _, trial = passing(tmp_path, "--bays", "pi5")
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["wall_thickness_mm"]["value_mm"] = None
    (trial / "measurements.json").write_text(json.dumps(measurements))

    with pytest.raises(ValueError, match="needs at least one measurement"):
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )

    path = complete_group_trial(
        trial, disposition=EnclosureTrialDisposition.FAIL, material_profile_id="petg"
    )

    assert record_of(path)["passed"] is False


def test_parts_changed_since_the_build_are_refused(tmp_path: Path) -> None:
    record, trial = passing(tmp_path, "--bays", "pi5")
    stl = Path(record_of(record)["parts"]["lid"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="no longer match the build record"):
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )


def test_a_temperature_is_compared_with_the_estimate(tmp_path: Path) -> None:
    _, trial = passing(tmp_path, "--bays", "pi5")
    thermal = json.loads((trial / "thermal.json").read_text())
    thermal.update(
        ambient_c=22.0,
        internal_air_c=30.0,
        power_w=6.0,
        settled_minutes=15.0,
        deformation_observed=False,
    )
    (trial / "thermal.json").write_text(json.dumps(thermal))
    record = record_of(
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )
    )

    assert record["thermal"]["rise_c"] == 8.0
    assert record["thermal"]["conductance_w_k"] == pytest.approx(0.75)
    assert record["thermal"]["estimate_error_ratio"] > 0


def test_a_hinged_groups_lid_readings_are_kept(hinged: Path) -> None:
    trial = start_group_trial(hinged)
    fill(trial)
    lid = json.loads((trial / "lid.json").read_text())
    lid.update(
        pin_turns_freely=True,
        swing_degrees_reached=95.0,
        catch_release_force_n=5.0,
        openings_counted=100,
        damage_observed=False,
    )
    (trial / "lid.json").write_text(json.dumps(lid))
    record = record_of(
        complete_group_trial(
            trial,
            disposition=EnclosureTrialDisposition.PASS,
            material_profile_id="petg",
        )
    )

    assert record["lid"]["swing_shortfall_degrees"] == 5.0
    assert record["lid"]["openings_counted"] == 100


# --- the command line ------------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["enclosure-group", *args])

    return code, cast(dict[str, Any], json.loads(capsys.readouterr().out))


def test_the_commands_start_and_complete_a_trial(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    record, _ = build(tmp_path, "--bays", "pi5")
    code, started = run(capsys, "trial", "start", "--build-record", str(record))
    trial = Path(started["trial"])
    fill(trial)
    code, completed = run(
        capsys,
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0
    assert completed["passed"] is True
    assert Path(completed["trial_record"]).is_file()


# --- joining by record --------------------------------------------------------------------------


def test_two_units_are_checked_from_their_records(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path)
    (tmp_path / "left").mkdir()
    (tmp_path / "right").mkdir()
    left, _ = build(tmp_path / "left", "--bays", "pi5", "--joint", "standard")
    right, _ = build(
        tmp_path / "right",
        "--bays",
        f"board:file={board}:align=front",
        "--joint",
        "standard",
    )
    code, report = run(
        capsys, "check-join", "--left-record", str(left), "--right-record", str(right)
    )

    assert code == 0 and report["passed"] is True
    assert report["checks"] == {"same_screw": True, "bolts_line_up": True}
    assert report["details"]["from_records"] is True
    assert any("were not rebuilt" in n for n in report["notes"])

    (tmp_path / "old").mkdir()
    old, _ = build(tmp_path / "old", "--bays", "pi5")
    code, report = run(
        capsys, "check-join", "--left-record", str(old), "--right-record", str(right)
    )

    assert code == 1 and report["checks"]["bolts_line_up"] is False
    assert any("not on the standard joint face" in n for n in report["notes"])


def test_the_join_check_needs_both_units_of_one_kind(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    capsys.readouterr()

    assert main(["enclosure-group", "check-join", "--left-bays", "pi5"]) == 1
    assert "give both --left-bays and --right-bays" in capsys.readouterr().err

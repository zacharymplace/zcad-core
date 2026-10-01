"""A PCB test fixture's file: what it refuses, and what it says of the board."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.pcb_fixture_file import (
    check_fixture_data,
    check_fixture_file,
    fixture_template,
    load_fixture,
)
from zcad_core.hardware import board_template
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PRINTER_PATH)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_board(directory: Path, **changes: Any) -> Path:
    data = copy.deepcopy(board_template())
    data.update(changes)
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def write_fixture(directory: Path, board: Path, **changes: Any) -> Path:
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data.update(changes)
    path = directory / "fixture.json"
    path.write_text(json.dumps(data))

    return path


def template() -> dict[str, Any]:
    return copy.deepcopy(fixture_template())


# --- the file -------------------------------------------------------------------


def test_the_template_is_valid() -> None:
    report = check_fixture_data(template())

    assert report.valid
    assert report.warnings == ()


def test_the_template_names_a_board_by_its_real_hash(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = fixture_template(board)

    assert data["board"]["sha256"] == sha(board)
    assert data["board"]["file"] == str(board)


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.update(schema_version="9.0.0"), "schema_version"),
        (lambda d: d.update(units="inch"), "units must be 'mm'"),
        (lambda d: d.update(identifier="has space"), "identifier"),
        (lambda d: d.update(needs_review=["pin"]), "not reviewed"),
        (lambda d: d.update(bogus=1), "Unknown field"),
        (lambda d: d.pop("board"), "board is missing"),
        (lambda d: d["board"].update(sha256="abc"), "board.sha256"),
        (lambda d: d["board"].update(file=""), "board.file"),
        (lambda d: d.update(side="bottom"), "later release"),
        (lambda d: d.update(locating="glue"), "locating must be one of"),
        (lambda d: d.update(closure="tape"), "closure must be one of"),
        (lambda d: d.update(points=[]), "points must be a list"),
        (lambda d: d.update(points=["TP1", "TP1"]), "lists a test point twice"),
        (lambda d: d.pop("pin"), "pin is missing"),
        (lambda d: d["pin"].pop("source"), "pin.source"),
        (lambda d: d["pin"].pop("model"), "pin.model"),
        (lambda d: d["pin"].update(barrel_diameter_mm="thin"), "must be a number"),
        (lambda d: d["pin"].update(tip_diameter_mm=1.4), "tip cannot be wider"),
        (lambda d: d["pin"].update(travel_mm=15.0), "travel must be less"),
        (lambda d: d["pin"].pop("force_n"), "pin.force_n is missing"),
        (lambda d: d.pop("working_travel_mm"), "working_travel_mm is missing"),
        (lambda d: d.update(working_travel_mm=0.01), "working_travel_mm"),
        (lambda d: d.update(pin={"catalog": "P75-E2"}), "none yet"),
        (lambda d: d.update(screw={"size": "M9"}), "screw.size must be one of"),
        (lambda d: d.update(screw={"tensile_limit_n": 500}), "screw.source"),
        (
            lambda d: d.update(screw={"tensile_limit_n": 0, "source": "x"}),
            "screw.tensile_limit_n",
        ),
    ],
)
def test_what_cannot_be_right_is_refused(change: Any, expect: str) -> None:
    data = template()
    change(data)
    report = check_fixture_data(data)

    assert not report.valid
    assert any(expect in error for error in report.errors), report.errors


def test_a_fixture_with_no_source_is_warned_of() -> None:
    data = template()
    del data["source"]

    assert any("No source" in w for w in check_fixture_data(data).warnings)


def test_a_non_object_is_refused() -> None:
    assert not check_fixture_data([1]).valid


def test_a_loaded_fixture_says_the_pin_is_the_users(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    spec = load_fixture(write_fixture(tmp_path, board))

    assert spec.pin.source.kind == "user"
    assert "no maker's datasheet" in spec.pin.figures_from
    assert spec.board_path == board.resolve()
    assert spec.locating == "outline" and spec.closure == "screws"


# --- the board ----------------------------------------------------------------------


def test_a_good_fixture_reports_the_board_the_pin_and_each_points_slack(
    tmp_path: Path,
) -> None:
    report = check_fixture_file(write_fixture(tmp_path, write_board(tmp_path)), PROFILE)

    assert report.valid, report.errors
    assert report.summary is not None
    assert report.summary["board"]["identifier"] == "EXAMPLE_BOARD"
    assert report.summary["board"]["mounting_holes"] == 4
    assert report.summary["pin"]["figures_from"].startswith("the user's file")
    slacks = {p["identifier"]: p["slack_mm"] for p in report.summary["points"]}

    # A 3 mm pad and a 0.6 mm tip: 1.2 mm to spare.
    assert slacks == {"TP1": 1.2, "TP2": 1.2}
    assert report.summary["closest_pitch_mm"] == 16.0
    # The barrel is pressed in: the barrel, the press-fit clearance each side, and
    # the allowance for a printer that prints holes small.
    assert report.summary["bore_diameter_mm"] == pytest.approx(1.0 + 2 * 0.05 + 0.2)


def test_the_check_lays_the_fixture_out_and_reports_the_budget(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(write_fixture(tmp_path, board), PROFILE)

    assert report.summary is not None
    plan = report.summary["plan"]

    assert plan["plate"]["top_mm"] == 12.0
    assert plan["misalignment"]["total_mm"] <= 1.2
    assert plan["locating"] == "outline"
    without_a_printer = check_fixture_file(write_fixture(tmp_path, board))

    assert without_a_printer.summary is not None
    assert "plan" not in without_a_printer.summary


def test_a_pad_the_clearances_can_miss_is_refused_by_the_check(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = json.loads(board.read_text())

    for entry in data["test_points"]:
        entry["pad_diameter_mm"] = 1.5

    board.write_text(json.dumps(data))
    report = check_fixture_file(write_fixture(tmp_path, board), PROFILE)

    assert any("can move the tip" in e for e in report.errors)


def test_a_board_that_has_changed_is_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    fixture = write_fixture(tmp_path, board)
    board.write_text(board.read_text() + " ")
    report = check_fixture_file(fixture, PROFILE)

    assert any("has changed since the fixture file" in e for e in report.errors)


def test_a_missing_board_is_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    fixture = write_fixture(tmp_path, board)
    board.unlink()

    assert any(
        "board file is missing" in e
        for e in check_fixture_file(fixture, PROFILE).errors
    )


def test_a_board_that_is_not_valid_is_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path, units="inch")
    report = check_fixture_file(write_fixture(tmp_path, board), PROFILE)

    assert not report.valid
    assert any("units" in e for e in report.errors)


def test_a_board_with_no_test_points_cannot_be_probed(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = json.loads(board.read_text())
    del data["test_points"]
    board.write_text(json.dumps(data))
    report = check_fixture_file(write_fixture(tmp_path, board), PROFILE)

    assert any("has no test points on its top side" in e for e in report.errors)


def test_only_the_named_points_are_probed(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(write_fixture(tmp_path, board, points=["TP2"]), PROFILE)

    assert report.valid, report.errors
    assert report.summary is not None
    assert [p["identifier"] for p in report.summary["points"]] == ["TP2"]


def test_a_point_the_board_does_not_have_is_refused_and_the_real_ones_listed(
    tmp_path: Path,
) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(write_fixture(tmp_path, board, points=["TP9"]), PROFILE)

    assert any(
        "no top-side test point named TP9" in e and "TP1, TP2" in e
        for e in report.errors
    )


def test_a_tip_wider_than_its_pad_is_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["pin"].update(tip_diameter_mm=0.9, barrel_diameter_mm=1.2)
    data["board"]["sha256"] = sha(board)
    fixture = tmp_path / "fixture.json"
    board_data = json.loads(board.read_text())
    board_data["test_points"][0]["pad_diameter_mm"] = 0.7
    board.write_text(json.dumps(board_data))
    data["board"]["sha256"] = sha(board)
    fixture.write_text(json.dumps(data))
    report = check_fixture_file(fixture, PROFILE)

    assert any(
        "TP1: the pin's 0.9 mm tip is wider than the 0.7 mm pad" in e
        for e in report.errors
    )


def test_a_tip_over_half_its_pad_is_warned_of(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    board_data = json.loads(board.read_text())

    for entry in board_data["test_points"]:
        entry["pad_diameter_mm"] = 1.5

    board.write_text(json.dumps(board_data))
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["pin"].update(tip_diameter_mm=0.9, barrel_diameter_mm=1.2)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(data))
    report = check_fixture_file(fixture, PROFILE)

    assert any("more than half" in w for w in report.warnings)


def test_locating_by_holes_needs_the_board_to_have_them(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = json.loads(board.read_text())
    del data["mounting_holes"]
    board.write_text(json.dumps(data))
    report = check_fixture_file(
        write_fixture(tmp_path, board, locating="holes"), PROFILE
    )

    assert any(
        "Locating by the mounting holes needs at least two" in e for e in report.errors
    )


def test_a_working_travel_beyond_the_pins_is_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(
        write_fixture(tmp_path, board, working_travel_mm=5.0), PROFILE
    )

    assert any("more than the pin's 4 mm of travel" in e for e in report.errors)


def test_pins_closer_than_their_bores_can_wall_are_refused(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    board_data = json.loads(board.read_text())

    # Two small pads 2.3 mm apart, as on a header: a 1.3 mm bore leaves 1.0 mm.
    for entry in board_data["test_points"]:
        entry["pad_diameter_mm"] = 1.5

    board_data["test_points"][1]["x_mm"] = -5.7
    board.write_text(json.dumps(board_data))
    report = check_fixture_file(write_fixture(tmp_path, board), PROFILE)

    assert any(
        "TP1 and TP2 are 2.30 mm apart" in e and "least wall is 1.2 mm" in e
        for e in report.errors
    )


def test_without_a_printer_the_pitch_is_not_checked(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(write_fixture(tmp_path, board))

    assert report.valid
    assert any("pitch was not checked" in w for w in report.warnings)


# --- the command ----------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_command_writes_a_template_and_checks_it(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path)
    path = tmp_path / "fixture.json"
    exit_code, output = run(
        capsys,
        "fixture",
        "template",
        "--board-file",
        str(board),
        "--output",
        str(path),
    )

    assert exit_code == 0
    assert output == {"written": str(path)}

    exit_code, checked = run(
        capsys, "fixture", "check", str(path), "--printer-profile", str(PRINTER_PATH)
    )

    assert exit_code == 0
    assert checked["valid"] is True
    assert checked["fixture"]["pin"]["model"] == "EXAMPLE-PIN"


def test_the_template_does_not_overwrite(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "fixture.json"
    path.write_text("{}")

    assert main(["fixture", "template", "--output", str(path)]) == 1
    capsys.readouterr()


def test_the_command_exits_one_and_lists_the_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path)
    path = write_fixture(tmp_path, board, working_travel_mm=5.0)
    exit_code, output = run(
        capsys, "fixture", "check", str(path), "--printer-profile", str(PRINTER_PATH)
    )

    assert exit_code == 1
    assert output["valid"] is False
    assert any("working_travel_mm" in e for e in output["errors"])


def test_the_validation_labs_export_command_is_still_there(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["fixture", "export", "--help"])

    assert "--output" in capsys.readouterr().out


def test_the_check_reports_the_closure_and_its_unchecked_load(tmp_path: Path) -> None:
    report = check_fixture_file(write_fixture(tmp_path, write_board(tmp_path)), PROFILE)
    assert report.summary is not None
    closure = report.summary["closure_plan"]

    assert report.valid, report.errors
    # One newton per pin at the template's working travel.
    assert closure["preload_n"] == float(len(report.summary["points"]))
    assert closure["tensile_limit_checked"] is False
    assert any("not checked against a screw" in w for w in report.warnings)


def test_the_check_refuses_a_hinged_closure_it_cannot_build(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    report = check_fixture_file(
        write_fixture(tmp_path, board, closure="hinge"), PROFILE
    )

    assert any("'hinge' is not built yet" in e for e in report.errors)


def test_a_screw_limit_is_loaded_with_its_source(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    spec = load_fixture(
        write_fixture(
            tmp_path, board, screw={"tensile_limit_n": 400, "source": "my pull test"}
        )
    )

    assert spec.screw_limit_n == 400.0
    assert spec.screw_source == "my pull test"
    assert spec.screw_size == "M3"

"""A layer's build record and its fitting trials."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.layer_trial import (
    BUILD_RECORD,
    TRIAL_RECORD,
    complete_layer_trial,
    start_layer_trial,
)
from zcad_core.features.stack_layers import check_layers, layer_template
from zcad_core.hardware import board_template
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)


def write_board(directory: Path, name: str = "board.json", **changes: Any) -> Path:
    data = copy.deepcopy(board_template())
    data.update(changes)
    path = directory / name
    path.write_text(json.dumps(data))

    return path


def write_layer(directory: Path, board: Path, name: str = "layer.json") -> Path:
    data = layer_template(board)
    data["source"] = "a layer for tests"
    path = directory / name
    path.write_text(json.dumps(data))

    return path


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


def build(directory: Path, name: str = "out") -> Path:
    board = write_board(directory)
    layer = write_layer(directory, board)
    code, built = run(
        "stack",
        "layer",
        "build",
        "--layer-file",
        str(layer),
        "--output-directory",
        str(directory / name),
    )

    assert code == 0, built

    return Path(built["build_record"])


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(tmp_path_factory.mktemp("layer"))


@pytest.fixture
def copy_of(record: Path, tmp_path: Path) -> Path:
    """A fresh copy of the record and its parts, so a trial can be written."""

    target = tmp_path / "out"
    shutil.copytree(record.parent, target)
    data = json.loads((target / BUILD_RECORD).read_text())

    for part in data["parts"].values():
        part["stl_path"] = str(target / Path(part["stl_path"]).name)

    (target / BUILD_RECORD).write_text(json.dumps(data))

    return target / BUILD_RECORD


def test_a_build_writes_a_record_that_names_its_inputs_and_parts(record: Path) -> None:
    data = json.loads(record.read_text())

    assert data["record_kind"] == "layer-build"
    assert len(data["layer_file"]["sha256"]) == 64
    assert (
        len(data["board"]["sha256"]) == 64
        and data["board"]["identifier"] == "EXAMPLE_BOARD"
    )
    assert data["settings"] == {
        "fastener": "M2.5",
        "clearance_mm": 1.0,
        "spacer_mm": 7.0,
        "plate_mm": 2.0,
        "wall_mm": 1.2,
    }
    assert data["summary"]["spacers_to_print"] == 4
    assert set(data["parts"]) == {"plate", "spacer"}
    assert all(len(p["stl_sha256"]) == 64 for p in data["parts"].values())
    assert all(data["fit_checks"].values())
    assert "makes no electrical connection" in data["not_claimed"][0]
    assert data["nominal_measurements_mm"] == {
        "plate_width_mm": 30.0,
        "plate_depth_mm": 45.0,
        "plate_thickness_mm": 2.0,
        "spacer_height_mm": 7.0,
        "spacer_outer_mm": 5.3,
        "spacer_bore_mm": 2.9,
    }
    assert "openings_line_up" in data["checks"]


def test_a_trial_lists_what_was_designed_and_numbers_itself(copy_of: Path) -> None:
    trial = start_layer_trial(copy_of)
    fitting = json.loads((trial / "fitting.json").read_text())

    assert trial.name == "trial-001"
    assert fitting["designed"] == {
        "air_over_tallest_mm": 1.0,
        "tallest_part": "envelope-top",
    }
    assert "no limit" in fitting["not_a_limit"]
    observations = json.loads((trial / "observations.json").read_text())
    assert observations["plate_seats"]["result"] == "pending"
    assert start_layer_trial(copy_of).name == "trial-002"


def fill(
    trial: Path, fitting: dict[str, Any] | None = None, fail: str | None = None
) -> None:
    observations = json.loads((trial / "observations.json").read_text())

    for key, entry in observations.items():
        entry["result"] = "fail" if key == fail else "pass"

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())
    measurements["spacer_height_mm"]["value_mm"] = 6.95
    (trial / "measurements.json").write_text(json.dumps(measurements))

    if fitting:
        readings = json.loads((trial / "fitting.json").read_text())
        readings.update(fitting)
        (trial / "fitting.json").write_text(json.dumps(readings))


def complete(trial: Path, disposition: str = "pass") -> dict[str, Any]:
    path = complete_layer_trial(
        trial,
        disposition=EnclosureTrialDisposition(disposition),
        material_profile_id="petg",
    )

    return cast(dict[str, Any], json.loads(path.read_text()))


def test_a_filled_in_trial_keeps_the_readings_and_draws_no_conclusion(
    copy_of: Path,
) -> None:
    trial = start_layer_trial(copy_of)
    fill(
        trial,
        {
            "air_over_tallest_mm": 0.8,
            "bolts_pass_all_holes": True,
            "assemblies_counted": 12,
            "anything_wore": False,
            "notes": "tight at one hole",
        },
    )
    record = complete(trial)

    assert record["passed"] is True
    fitting = record["fitting"]
    assert fitting["air_over_tallest_mm"] == 0.8 and fitting["designed_air_mm"] == 1.0
    assert fitting["air_shortfall_mm"] == pytest.approx(0.2)
    assert fitting["bolts_pass_all_holes"] is True and fitting["anything_wore"] is False
    assert record["measurements"][0]["deviation_mm"] == pytest.approx(-0.05, abs=0.001)
    assert record["board_sha256"] == json.loads(copy_of.read_text())["board"]["sha256"]
    assert (trial / TRIAL_RECORD).is_file()

    with pytest.raises(FileExistsError):
        complete(trial)


@pytest.mark.parametrize(
    ("fitting", "message"),
    [
        ({"air_over_tallest_mm": -0.1}, "from zero"),
        ({"bolts_pass_all_holes": "yes"}, "true or false"),
        ({"assemblies_counted": 0}, "whole number"),
        ({"anything_wore": True}, "needs assemblies_counted"),
        ({"assemblies_counted": 5}, "true or false"),
    ],
)
def test_a_reading_that_cannot_be_right_is_refused(
    copy_of: Path, fitting: dict[str, Any], message: str
) -> None:
    trial = start_layer_trial(copy_of)
    fill(trial, fitting)

    with pytest.raises((ValueError, TypeError), match=message):
        complete(trial)


def test_a_trial_needs_a_reading_unless_it_failed(copy_of: Path) -> None:
    trial = start_layer_trial(copy_of)
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "fail"

    (trial / "observations.json").write_text(json.dumps(observations))

    with pytest.raises(ValueError, match="at least one measurement or fitting reading"):
        complete(trial, "revise")

    assert complete(trial, "fail")["passed"] is False


def test_a_passing_trial_cannot_have_a_failed_check(copy_of: Path) -> None:
    trial = start_layer_trial(copy_of)
    fill(trial, fail="plate_seats")

    with pytest.raises(ValueError, match="cannot have failed checks"):
        complete(trial, "pass")

    assert complete(trial, "revise")["failed_checks"] == ["plate_seats"]


def test_a_trial_is_refused_if_the_parts_changed(copy_of: Path) -> None:
    trial = start_layer_trial(copy_of)
    fill(trial)
    stl = Path(json.loads(copy_of.read_text())["parts"]["plate"]["stl_path"])
    stl.write_bytes(stl.read_bytes() + b"x")

    with pytest.raises(ValueError, match="no longer match"):
        complete(trial)


def test_the_commands_start_and_complete_a_trial(copy_of: Path) -> None:
    code, started = run(
        "stack", "layer", "trial", "start", "--build-record", str(copy_of)
    )
    trial = Path(started["trial"])

    assert code == 0 and Path(started["fitting"]).is_file()
    fill(trial)
    code, done = run(
        "stack",
        "layer",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0 and done["passed"] is True


def test_check_layers_reads_build_records(record: Path, tmp_path: Path) -> None:
    code, report = run(
        "stack", "check-layers", "--upper", str(record), "--lower", str(record)
    )

    assert code == 0 and report["stacks"] is True, report
    assert report["hole_offset_mm"] == 0.0
    # A record and a layer file stack too.
    layer = write_layer(tmp_path, write_board(tmp_path))
    assert check_layers(layer, record, PRINTER).stacks


def test_check_layers_does_not_trust_a_record_whose_board_changed(
    tmp_path: Path,
) -> None:
    record = build(tmp_path, "mine")
    board = Path(json.loads(record.read_text())["board"]["path"])
    write_board(tmp_path, identifier="CHANGED")

    assert board.is_file()
    code, report = run(
        "stack", "check-layers", "--upper", str(record), "--lower", str(record)
    )

    assert code == 1
    assert any("has changed since the build" in e for e in report["errors"])

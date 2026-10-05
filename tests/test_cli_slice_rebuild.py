"""zcad-validation slice check --rebuild: building a slice's design again."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.cli.slice_check import rebuild_freshness, rebuild_recipe

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)
BUILD = [
    "enclosure",
    "build",
    "--board",
    "raspberry_pi_pico_2",
    "--printer-profile",
    str(PRINTER_PROFILE),
]


def test_a_recipe_keeps_the_build_and_drops_where_it_wrote_and_the_slicing(
    tmp_path: Path,
) -> None:
    part = tmp_path / "base.stl"
    part.write_bytes(b"solid base")
    argv = [
        *BUILD,
        "--output-directory",
        "exports/case",
        "--slice",
        "--slicer-profile=profiles/slicers/a.json",
        "--review",
        "--wall-mm",
        "2.4",
    ]

    recipe = rebuild_recipe(argv, {"base": part})

    assert recipe is not None
    assert recipe["argv"] == [*BUILD, "--wall-mm", "2.4"]
    assert recipe["parts"] == {"base": hashlib.sha256(b"solid base").hexdigest()}
    assert recipe["working_directory"] == str(Path.cwd())


def test_a_command_that_cannot_rebuild_gets_no_recipe(tmp_path: Path) -> None:
    assert rebuild_recipe(["enclosure", "revise", "--trial-directory", "t"], {}) is None
    assert rebuild_recipe(None, {}) is None


@pytest.fixture(scope="module")
def sliced(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A real build, standing in for a sliced one, and its recipe."""

    output = tmp_path_factory.mktemp("built")
    argv = [*BUILD, "--output-directory", str(output)]
    assert main(argv) == 0
    parts = {
        part: output / f"raspberry-pi-pico-2-enclosure-{part}.stl"
        for part in ("base", "lid")
    }

    return {"rebuild": rebuild_recipe(argv, parts)}


def test_a_design_that_rebuilds_identically_is_current(
    sliced: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    freshness = rebuild_freshness(sliced)

    assert freshness.status == "current"
    assert "every part is identical" in freshness.reason


def test_a_part_that_rebuilds_differently_is_stale(sliced: dict[str, Any]) -> None:
    changed = json.loads(json.dumps(sliced))
    changed["rebuild"]["parts"]["lid"] = "0" * 64

    freshness = rebuild_freshness(changed)

    assert freshness.status == "stale"
    assert freshness.changes == ("lid",)


def test_a_slice_without_a_recipe_or_with_a_broken_one_is_unknown(
    sliced: dict[str, Any],
) -> None:
    broken = json.loads(json.dumps(sliced))
    broken["rebuild"]["argv"] = ["enclosure", "build", "--board", "nope"]

    assert "no way to rebuild it" in rebuild_freshness({}).reason
    failed = rebuild_freshness(broken)
    assert failed.status == "unknown"
    assert "Unsupported board: nope" in failed.reason


def test_check_rebuilds_only_what_the_commit_check_calls_stale(
    sliced: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # A commit this repository never had: the quick check cannot vouch for it.
    summary = {
        **sliced,
        "source": {"git_commit": "0" * 40, "uncommitted_changes": False},
    }
    path = tmp_path / "slice-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")

    assert main(["slice", "check", str(path)]) == 1
    quick = json.loads(capsys.readouterr().out)["slices"][0]
    assert (quick["status"], quick["checked_by"]) == ("unknown", "commit")

    assert main(["slice", "check", "--rebuild", str(path)]) == 0
    rebuilt = json.loads(capsys.readouterr().out)["slices"][0]
    assert (rebuilt["status"], rebuilt["checked_by"]) == ("current", "rebuild")


@pytest.fixture(scope="module")
def printed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A build with its print-oriented copies, as a slice records what the
    slicer was given."""

    output = tmp_path_factory.mktemp("printed")
    argv = [*BUILD, "--output-directory", str(output), "--print-copies"]
    assert main(argv) == 0
    parts = {
        part: output / f"raspberry-pi-pico-2-enclosure-{part}.stl"
        for part in ("base", "lid")
    }
    models = [
        {"path": str(model), "sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
        for model in sorted((output / "print").glob("*.stl"))
    ]
    recipe = rebuild_recipe([*BUILD, "--output-directory", str(output)], parts)

    return {"rebuild": recipe, "models": models}


def test_the_print_copies_the_slicer_was_given_are_compared_too(
    printed: dict[str, Any],
) -> None:
    # The lid is printed from a turned copy, not the build's STL; a change to
    # how it is turned leaves the build's parts the same.
    assert len(printed["models"]) == 2
    assert rebuild_freshness(printed).status == "current"

    turned = json.loads(json.dumps(printed))
    turned["models"][1]["sha256"] = "0" * 64
    freshness = rebuild_freshness(turned)

    assert freshness.status == "stale"
    assert freshness.changes == (f"print/{Path(turned['models'][1]['path']).name}",)


def test_a_slice_whose_gcode_was_replaced_is_stale(
    sliced: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    gcode = tmp_path / "plate_1.gcode"
    gcode.write_text("; the sliced plate\n", encoding="utf-8")
    summary = {
        **sliced,
        "gcode_sha256": hashlib.sha256(gcode.read_bytes()).hexdigest(),
        "source": {"git_commit": "0" * 40, "uncommitted_changes": False},
    }
    path = tmp_path / "slice-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    gcode.write_text("; another plate\n", encoding="utf-8")

    assert main(["slice", "check", "--rebuild", str(path)]) == 1
    entry = json.loads(capsys.readouterr().out)["slices"][0]

    assert (entry["status"], entry["checked_by"]) == ("stale", "files")
    assert "plate_1.gcode" in entry["reason"]


def test_a_recipe_records_the_files_its_command_line_names(tmp_path: Path) -> None:
    board = tmp_path / "board.json"
    board.write_text("{}", encoding="utf-8")
    part = tmp_path / "base.stl"
    part.write_bytes(b"solid base")

    recipe = rebuild_recipe(
        ["enclosure", "build", "--board-file", str(board)], {"base": part}
    )

    assert recipe is not None
    assert recipe["inputs"] == {str(board): hashlib.sha256(b"{}").hexdigest()}


def test_a_slice_whose_board_file_changed_is_stale_however_it_rebuilds(
    sliced: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = tmp_path / "board.json"
    board.write_text('{"width_mm": 30}', encoding="utf-8")
    summary = json.loads(json.dumps(sliced))
    summary["rebuild"]["inputs"] = {
        str(board): hashlib.sha256(board.read_bytes()).hexdigest()
    }
    path = tmp_path / "slice-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    board.write_text('{"width_mm": 50}', encoding="utf-8")

    assert main(["slice", "check", "--rebuild", str(path)]) == 1
    entry = json.loads(capsys.readouterr().out)["slices"][0]

    assert (entry["status"], entry["checked_by"]) == ("stale", "files")
    assert entry["changes"] == [str(board)]


def test_a_slicer_change_keeps_a_slice_stale_though_its_parts_match(
    sliced: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from zcad_core.cli import slice_check

    monkeypatch.setattr(
        slice_check,
        "changed_since",
        lambda summary, paths: ("profiles/slicers/a.json",),
    )
    summary = {
        **sliced,
        "source": {"git_commit": "0" * 40, "uncommitted_changes": False},
    }
    path = tmp_path / "slice-summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")

    assert main(["slice", "check", "--rebuild", str(path)]) == 1
    entry = json.loads(capsys.readouterr().out)["slices"][0]

    assert entry["status"] == "stale"
    assert "slicer profiles changed" in entry["reason"]

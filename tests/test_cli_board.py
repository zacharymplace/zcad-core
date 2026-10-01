"""zcad-validation board check and template, and enclosure build --board-file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.cli.enclosure import _revision_board_file

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def make_board(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> Path:
    path = tmp_path / "board.json"
    exit_code, output = run(capsys, "board", "template", "--output", str(path))

    assert exit_code == 0
    assert output == {"written": str(path)}

    return path


def build(
    capsys: pytest.CaptureFixture[str], output: Path, *args: str
) -> tuple[int, dict[str, Any]]:
    return run(
        capsys,
        "enclosure",
        "build",
        "--output-directory",
        str(output),
        "--printer-profile",
        str(PRINTER_PROFILE),
        *args,
    )


def test_template_prints_a_valid_file(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output = run(capsys, "board", "template")

    assert exit_code == 0
    assert output["schema_version"]


def test_template_does_not_overwrite(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path)

    assert main(["board", "template", "--output", str(path)]) == 1


def test_check_summarises_a_valid_board(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path)
    exit_code, output = run(capsys, "board", "check", str(path))

    assert exit_code == 0
    assert output["valid"] is True
    assert output["board"]["identifier"] == "EXAMPLE_BOARD"
    assert output["board"]["verified"] is False


def test_check_exits_one_and_lists_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path)
    data = json.loads(path.read_text())
    data["units"] = "inch"
    path.write_text(json.dumps(data))

    exit_code, output = run(capsys, "board", "check", str(path))

    assert exit_code == 1
    assert output["valid"] is False
    assert any("units" in error for error in output["errors"])
    assert "board" not in output


def test_build_from_a_board_file_records_where_the_board_came_from(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path / "in")
    exit_code, output = build(capsys, tmp_path / "out", "--board-file", str(path))

    assert exit_code == 0
    assert output["board"]["kind"] == "file"
    assert output["board"]["verified"] is False

    record = json.loads(Path(output["build_record"]).read_text())

    assert record["board_source"]["kind"] == "file"
    assert record["board_source"]["sha256"] == output["board"]["sha256"]


def test_a_catalogued_board_is_recorded_as_catalog(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(capsys, tmp_path, "--board", "RASPBERRY_PI_PICO_2")

    assert exit_code == 0
    assert output["board"] == {
        "kind": "catalog",
        "identifier": "RASPBERRY_PI_PICO_2",
    }


def test_exactly_one_of_board_and_board_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path / "in")

    assert main(["enclosure", "build", "--output-directory", str(tmp_path / "a")]) == 1
    assert (
        main(
            [
                "enclosure",
                "build",
                "--output-directory",
                str(tmp_path / "b"),
                "--board",
                "RASPBERRY_PI_PICO_2",
                "--board-file",
                str(path),
            ]
        )
        == 1
    )


def test_a_revision_refuses_a_changed_board_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = make_board(capsys, tmp_path)
    _, output = build(capsys, tmp_path / "out", "--board-file", str(path))
    record = json.loads(Path(output["build_record"]).read_text())

    assert _revision_board_file(record) == path

    path.write_text(path.read_text() + "\n")

    with pytest.raises(ValueError, match="changed"):
        _revision_board_file(record)


def test_a_revision_of_a_catalog_build_has_no_file() -> None:
    assert _revision_board_file({"board_source": {"kind": "catalog"}}) is None
    assert _revision_board_file({}) is None

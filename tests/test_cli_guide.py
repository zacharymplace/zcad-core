"""zcad-validation guide template, check, and build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


@pytest.fixture(scope="module")
def part(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("part") / "plate.step"
    plate = (
        cq.Workplane("XY")
        .box(50, 30, 10, centered=(True, True, False))
        .edges("|Z")
        .fillet(4)
    )
    cq.exporters.export(plate, str(path))

    return path


def make_guide(capsys: pytest.CaptureFixture[str], directory: Path, part: Path) -> Path:
    path = directory / "guide.json"
    exit_code, output = run(
        capsys, "guide", "template", "--part", str(part), "--output", str(path)
    )

    assert exit_code == 0
    assert output == {"written": str(path)}

    return path


def test_template_prints_a_valid_file(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output = run(capsys, "guide", "template")

    assert exit_code == 0
    assert output["schema_version"]
    assert output["nest"]["bearing"] == "top"


def test_template_does_not_overwrite(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)

    assert main(["guide", "template", "--output", str(path)]) == 1


def test_check_summarises_the_part(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    exit_code, output = run(capsys, "guide", "check", str(path))

    assert exit_code == 0
    assert output["valid"] is True
    assert output["part"]["height_mm"] == pytest.approx(10, abs=0.05)
    assert output["part"]["solids"] == 1


def test_check_exits_one_and_lists_errors(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    data = json.loads(path.read_text())
    data["nest"]["depth_mm"] = 40.0
    path.write_text(json.dumps(data))
    exit_code, output = run(capsys, "guide", "check", str(path))

    assert exit_code == 1
    assert output["valid"] is False
    assert any("deeper than the part" in e for e in output["errors"])


def test_check_says_when_the_part_has_changed(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    data = json.loads(path.read_text())
    data["part"]["sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    exit_code, output = run(capsys, "guide", "check", str(path))

    assert exit_code == 1
    assert any("has changed since" in e for e in output["errors"])


def test_build_exports_a_nest_and_a_record(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    out = tmp_path / "out"
    exit_code, output = run(
        capsys,
        "guide",
        "build",
        "--guide-file",
        str(path),
        "--output-directory",
        str(out),
        "--printer-profile",
        str(PRINTER_PROFILE),
    )

    assert exit_code == 0
    assert output["checks"] == {
        "one_solid": True,
        "part_fits_pocket": True,
        "part_lifts_out": True,
        "bores_open": True,
        "bit_reaches_depth": True,
    }
    assert output["verified"] is False
    assert output["tolerance_status"] == "provisional"
    assert output["validation_status"] == "PASS"
    assert Path(output["parts"]["guide"]["stl_path"]).is_file()

    record = json.loads(Path(output["build_record"]).read_text())

    assert record["part"]["sha256"] == output["part"]["sha256"]
    assert record["verified"] is False
    assert record["parts"]["guide"]["stl_sha256"]


def test_build_refuses_a_guide_that_cannot_be_built(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    data = json.loads(path.read_text())
    data["bores"] = [{"x_mm": 0, "y_mm": 0}]
    path.write_text(json.dumps(data))

    assert (
        main(
            [
                "guide",
                "build",
                "--guide-file",
                str(path),
                "--output-directory",
                str(tmp_path / "out"),
                "--printer-profile",
                str(PRINTER_PROFILE),
            ]
        )
        == 1
    )
    capsys.readouterr()


def test_check_places_the_bores_and_refuses_one_off_the_part(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    exit_code, output = run(capsys, "guide", "check", str(path))

    assert exit_code == 0
    assert output["part"]["bores"][0]["identifier"] == "B1"
    assert output["part"]["plate_thickness_mm"] == 6.0

    data = json.loads(path.read_text())
    data["bores"][0]["x_mm"] = 60.0
    path.write_text(json.dumps(data))
    exit_code, output = run(capsys, "guide", "check", str(path))

    assert exit_code == 1
    assert any("B1 stands at (60, 0)" in e for e in output["errors"])


def test_build_reports_each_bore_and_what_it_needs_of_the_bit(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    exit_code, output = run(
        capsys,
        "guide",
        "build",
        "--guide-file",
        str(path),
        "--output-directory",
        str(tmp_path / "out"),
        "--printer-profile",
        str(PRINTER_PROFILE),
    )

    assert exit_code == 0
    (placed,) = output["bores"]

    assert placed["bit_needed_beyond_chuck_mm"] == 12.0
    assert placed["worst_case_entry_play_mm"] == pytest.approx(0.4)
    assert output["plate_thickness_mm"] == 6.0
    assert output["verified"] is False


def test_build_refuses_a_bit_that_cannot_reach(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    path = make_guide(capsys, tmp_path, part)
    data = json.loads(path.read_text())
    data["drill"]["stickout_mm"] = 8.0
    path.write_text(json.dumps(data))

    assert (
        main(
            [
                "guide",
                "build",
                "--guide-file",
                str(path),
                "--output-directory",
                str(tmp_path / "out"),
                "--printer-profile",
                str(PRINTER_PROFILE),
            ]
        )
        == 1
    )
    capsys.readouterr()

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import (
    build_group_enclosure,
    print_oriented_parts,
)
from zcad_core.printing import BAMBU_STUDIO, SliceError, SliceResult

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def build(
    capsys: pytest.CaptureFixture[str], output: Path, *args: str
) -> tuple[int, dict[str, Any], str]:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *args,
        ]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_the_base_prints_on_its_floor_and_the_lid_on_its_outer_face() -> None:
    group = build_group_enclosure()
    parts = print_oriented_parts(group)
    base = parts["base"].BoundingBox()
    lid = parts["lid"].BoundingBox()

    assert base.zmin == pytest.approx(0.0)
    # The lid was modelled above the box, outer face up; turned over, that
    # face is now its lowest.
    assert lid.zmax == pytest.approx(-group.cavity_top_z_mm)
    assert lid.zmin == pytest.approx(-(group.cavity_top_z_mm + group.design.lid_mm))
    assert (lid.xlen, lid.ylen) == pytest.approx((base.xlen, base.ylen))


def test_a_build_without_slice_prints_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output, _ = build(capsys, tmp_path)

    assert exit_code == 0
    assert output["print"] is None
    assert not (tmp_path / "print").exists()
    assert not (tmp_path / "slice").exists()


def test_slice_puts_each_part_on_its_own_plate(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_slice(
        models: Sequence[Path], output_directory: Path, **kwargs: Any
    ) -> SliceResult:
        calls.append(([model.name for model in models], output_directory))
        gcode = output_directory / "plate_1.gcode"
        seconds = 3600 if "base" in models[0].name else 1800

        return SliceResult(
            gcode_path=gcode,
            summary_path=output_directory / "slice-summary.json",
            summary={
                "estimated_print_time_seconds": seconds,
                "filament_used_g": seconds / 60,
                "slicer_warning": "",
                "part": kwargs["summary_fields"]["part"],
            },
        )

    monkeypatch.setattr("zcad_core.cli.enclosure_group.slice_models", fake_slice)

    exit_code, output, _ = build(capsys, tmp_path, "--slice")

    assert exit_code == 0
    assert calls == [
        (["pi5-group-2bay-base.stl"], tmp_path / "slice" / "base"),
        (["pi5-group-2bay-lid.stl"], tmp_path / "slice" / "lid"),
    ]
    assert (tmp_path / "print" / "pi5-group-2bay-base.stl").is_file()
    assert (tmp_path / "print" / "pi5-group-2bay-lid.stl").is_file()
    plates = output["print"]["plates"]
    assert plates["base"]["estimated_print_minutes"] == 60
    assert plates["lid"]["estimated_print_minutes"] == 30
    assert output["print"]["total_print_minutes"] == 90
    assert output["print"]["total_filament_g"] == 90.0


def test_a_slicer_failure_is_an_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: Any, **__: Any) -> SliceResult:
        raise SliceError("Bambu Studio could not slice the plate")

    monkeypatch.setattr("zcad_core.cli.enclosure_group.slice_models", refuse)

    exit_code, _, err = build(capsys, tmp_path, "--slice")

    assert exit_code == 1
    assert "Bambu Studio could not slice the plate" in err


def test_a_failed_check_skips_the_slice(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*_: Any, **__: Any) -> SliceResult:
        raise AssertionError("must not slice a design that failed its checks")

    monkeypatch.setattr("zcad_core.cli.enclosure_group.slice_models", never)

    # 10 mm of headroom puts the lid through the Pi's envelope.
    exit_code, output, _ = build(capsys, tmp_path, "--slice", "--headroom-mm", "10")

    assert exit_code == 1
    assert output["print"] is None


@pytest.mark.slow
@pytest.mark.skipif(not BAMBU_STUDIO.is_dir(), reason="Bambu Studio is not installed")
def test_slice_produces_gcode_for_both_parts(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output, _ = build(capsys, tmp_path, "--slice")
    plates = output["print"]["plates"]

    assert exit_code == 0
    for part in ("base", "lid"):
        assert Path(plates[part]["gcode"]).is_file()
        assert plates[part]["estimated_print_minutes"] > 0
        assert plates[part]["filament_used_g"] > 0
        assert plates[part]["slicer_warning"] == ""


def test_a_hinged_lid_that_lies_on_its_knuckles_is_sliced_with_supports(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Turned over, its knuckles are its lowest point and the panel is in the
    # air; no turn helps, so its plate gets supports from the build plate.
    supported: dict[str, bool] = {}

    def fake_slice(
        models: Sequence[Path], output_directory: Path, **kwargs: Any
    ) -> SliceResult:
        supported[kwargs["summary_fields"]["part"]] = kwargs["supports"]

        return SliceResult(
            gcode_path=output_directory / "plate_1.gcode",
            summary_path=output_directory / "slice-summary.json",
            summary={
                "estimated_print_time_seconds": 60,
                "filament_used_g": 1.0,
                "slicer_warning": "",
            },
        )

    monkeypatch.setattr("zcad_core.cli.enclosure_group.slice_models", fake_slice)

    exit_code, output, _ = build(
        capsys, tmp_path, "--lid", "hinge", "--headroom-mm", "20", "--slice"
    )

    assert exit_code == 0
    assert supported == {"base": False, "lid": True}
    assert output["print"]["plates"]["lid"]["supported"] is True

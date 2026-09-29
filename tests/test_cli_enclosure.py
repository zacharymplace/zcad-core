"""zcad-validation enclosure hardware and enclosure build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.printing import BAMBU_STUDIO

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


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


def test_hardware_lists_the_catalogs(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code, output = run(capsys, "enclosure", "hardware")

    assert exit_code == 0
    assert "RASPBERRY_PI_PICO_2" in output["boards"]
    assert output["displays"] == [
        "ADAFRUIT_EINK_200X200_1_54IN",
        "ADAFRUIT_OLED_128X128_1_5IN",
        "ADAFRUIT_OLED_128X64_1_3IN",
        "REFERENCE_OLED_128X64",
    ]
    assert "M3" in output["fasteners"]


def test_build_exports_a_validated_base_and_lid_with_a_review(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys,
        tmp_path,
        "--board",
        "raspberry_pi_pico_2",
        "--display",
        "reference_oled_128x64",
        "--review",
    )

    assert exit_code == 0
    assert output["design_name"] == "raspberry-pi-pico-2-enclosure"
    assert output["validation_status"] == "PASS"
    assert set(output["parts"]) == {"base", "lid"}
    for part in output["parts"].values():
        assert Path(part["stl"]).is_file()
    assert output["side_clearance_mm"] == [2.0, 10.0]
    assert output["review"]["passed"]
    assert output["review"]["recommended_screw"] == "M3 x 6 mm"
    assert Path(output["review"]["glb"]).is_file()


def test_build_without_a_display_uses_a_cradle_for_a_hole_less_board(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys, tmp_path, "--board", "seeed_xiao_esp32_s3", "--name", "xiao-case"
    )

    assert exit_code == 0
    assert output["board_support"] == "cradle"
    assert output["design_name"] == "xiao-case"
    assert "review" not in output


def test_build_fails_when_the_review_fails(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys,
        tmp_path,
        "--board",
        "raspberry_pi_pico_2",
        "--bottom-clearance-mm",
        "0.5",
        "--cable-plug-height-mm",
        "9",
        "--review",
    )

    assert exit_code == 1
    assert output["review"]["failed_checks"] == ["plug_body_clears_floor"]


def test_build_refuses_an_unknown_board(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert (
        main(
            [
                "enclosure",
                "build",
                "--board",
                "nope",
                "--output-directory",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "Unsupported board: nope" in capsys.readouterr().err


def test_build_refuses_a_display_resting_on_the_board(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--display",
            "reference_oled_128x64",
            "--display-height-mm",
            "1.5",
            "--output-directory",
            str(tmp_path),
        ]
    )

    assert exit_code == 1
    assert "raise --display-height-mm" in capsys.readouterr().err


def test_build_can_leave_the_display_loose(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys,
        tmp_path,
        "--board",
        "raspberry_pi_pico_2",
        "--display",
        "reference_oled_128x64",
        "--no-display-retainer",
    )

    assert exit_code == 0
    # The lid is a plain plate, as thick as the lid setting.
    assert output["parts"]["lid"]["bounds_mm"][2] == pytest.approx(2.0)


def test_build_screws_a_display_to_lid_posts(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys,
        tmp_path,
        "--board",
        "raspberry_pi_pico_2",
        "--display",
        "adafruit_oled_128x64_1_3in",
        "--review",
    )

    assert exit_code == 0
    assert output["review"]["display_screws"] == {
        "count": 4,
        "kind": "self-tapping, into plastic",
        "recommended_screw_length_mm": 5,
        "size": "M2",
    }


def test_build_writes_a_build_record_and_trials_complete(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(capsys, tmp_path, "--board", "raspberry_pi_pico_2")
    assert exit_code == 0
    record = Path(output["build_record"])
    assert json.loads(record.read_text("utf-8"))["board"] == "RASPBERRY_PI_PICO_2"

    exit_code, started = run(
        capsys, "enclosure", "trial", "start", "--build-record", str(record)
    )
    assert exit_code == 0
    trial = Path(started["trial"])
    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    for entry in observations.values():
        entry["result"] = "pass"
    (trial / "observations.json").write_text(json.dumps(observations), "utf-8")
    measurements = json.loads((trial / "measurements.json").read_text("utf-8"))
    measurements["base_height_mm"]["value_mm"] = 20.1
    (trial / "measurements.json").write_text(json.dumps(measurements), "utf-8")

    exit_code, completed = run(
        capsys,
        "enclosure",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert exit_code == 0
    assert json.loads(Path(completed["trial_record"]).read_text("utf-8"))["passed"]


@pytest.mark.slow
@pytest.mark.skipif(not BAMBU_STUDIO.is_dir(), reason="Bambu Studio is not installed")
def test_build_slices_both_parts_ready_to_print(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = build(
        capsys, tmp_path, "--board", "seeed_xiao_esp32_s3", "--slice"
    )

    assert exit_code == 0
    assert Path(output["print"]["gcode"]).stat().st_size > 0
    assert output["print"]["estimated_print_minutes"] > 0
    assert (Path(output["print"]["trial"]) / "observations.json").is_file()
    assert sorted(path.name for path in (tmp_path / "print").iterdir()) == [
        "seeed-xiao-esp32-s3-enclosure-base.stl",
        "seeed-xiao-esp32-s3-enclosure-lid.stl",
    ]

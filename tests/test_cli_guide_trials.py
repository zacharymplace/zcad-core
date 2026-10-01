"""zcad-validation guide trial, status, and derive, and a build that reports a
measured accuracy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main

PROFILES = Path(__file__).resolve().parents[1] / "profiles/printers"
A1_MINI = PROFILES / "bambu-lab-a1-mini.json"
DEFAULT_FDM = PROFILES / "default-fdm.json"


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


@pytest.fixture(scope="module")
def part(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("part") / "plate.step"
    cq.exporters.export(
        cq.Workplane("XY").box(50, 30, 10, centered=(True, True, False)), str(path)
    )

    return path


def build(
    capsys: pytest.CaptureFixture[str],
    directory: Path,
    part: Path,
    *extra: str,
    printer: Path = A1_MINI,
) -> tuple[int, dict[str, Any]]:
    guide = directory / "guide.json"

    if not guide.exists():
        code, _ = run(
            capsys, "guide", "template", "--part", str(part), "--output", str(guide)
        )
        assert code == 0

    return run(
        capsys,
        "guide",
        "build",
        "--guide-file",
        str(guide),
        "--output-directory",
        str(directory / "out"),
        "--printer-profile",
        str(printer),
        *extra,
    )


def one_trial(
    capsys: pytest.CaptureFixture[str],
    record: str,
    offset: tuple[float, float] = (0.2, -0.1),
) -> Path:
    code, started = run(capsys, "guide", "trial", "start", "--build-record", record)
    assert code == 0
    trial = Path(started["trial"])
    observations = json.loads((trial / "observations.json").read_text())

    for entry in observations.values():
        entry["result"] = "pass"

    (trial / "observations.json").write_text(json.dumps(observations))
    measurements = json.loads((trial / "measurements.json").read_text())

    for entry in measurements["bores"].values():
        entry["measured_x_mm"] = entry["nominal_x_mm"] + offset[0]
        entry["measured_y_mm"] = entry["nominal_y_mm"] + offset[1]

    (trial / "measurements.json").write_text(json.dumps(measurements))
    code, done = run(
        capsys,
        "guide",
        "trial",
        "complete",
        "--trial-directory",
        str(trial),
        "--disposition",
        "pass",
    )

    assert code == 0
    assert done["summary"]["bores_measured"] == 1

    return trial


def test_the_build_records_the_material(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    code, output = build(capsys, tmp_path, part)

    assert code == 0
    assert output["material_profile_id"] == "petg"
    assert output["measured_accuracy"] is None
    assert json.loads(Path(output["build_record"]).read_text())["measured"] is None


def test_a_guide_is_verified_by_two_passing_trials(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    _, output = build(capsys, tmp_path, part)
    record = output["build_record"]
    code, status = run(capsys, "guide", "status", "--build-record", record)

    assert code == 1
    assert status["verified"] is False

    one_trial(capsys, record)
    code, status = run(capsys, "guide", "status", "--build-record", record)

    assert code == 1
    assert status["passing_trials"] == 1

    one_trial(capsys, record)
    code, status = run(capsys, "guide", "status", "--build-record", record)

    assert code == 0
    assert status["verified"] is True


def test_derived_figures_come_back_in_the_next_build(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    (tmp_path / "first").mkdir()
    _, first = build(capsys, tmp_path / "first", part)
    record = first["build_record"]
    one_trial(capsys, record, (0.2, -0.1))
    one_trial(capsys, record, (0.1, 0.3))
    profile = tmp_path / "profiles" / "guide.json"
    code, derived = run(
        capsys,
        "guide",
        "derive",
        "--evidence-root",
        str(tmp_path / "first"),
        "--output",
        str(profile),
    )

    assert code == 0
    assert derived["version"] == 1
    assert derived["trials"] == 2
    assert derived["figures"]["position"]["printed"]["samples"] == 2

    (tmp_path / "second").mkdir()
    code, output = build(
        capsys, tmp_path / "second", part, "--accuracy-profile", str(profile)
    )

    assert code == 0
    measured = output["measured_accuracy"]
    (bore,) = measured["bores"]

    assert bore["measured"]["samples"] == 2
    assert bore["measured"]["max"] == pytest.approx(0.316, abs=1e-3)
    assert bore["play_bound_entry_mm"] == pytest.approx(0.4)
    assert bore["measured_exceeds_bound"] is False
    assert "2 passing trials" in measured["described"]
    assert "guarantee" in measured["note"]

    recorded = json.loads(Path(output["build_record"]).read_text())

    assert recorded["measured"]["profile"]["sha256"]
    assert recorded["verified"] is False


def test_a_measured_error_beyond_the_bound_is_flagged(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    (tmp_path / "first").mkdir()
    _, first = build(capsys, tmp_path / "first", part)
    one_trial(capsys, first["build_record"], (1.5, 0.0))
    one_trial(capsys, first["build_record"], (1.2, 0.0))
    profile = tmp_path / "guide.json"
    run(
        capsys,
        "guide",
        "derive",
        "--evidence-root",
        str(tmp_path / "first"),
        "--output",
        str(profile),
    )
    (tmp_path / "second").mkdir()
    _, output = build(
        capsys, tmp_path / "second", part, "--accuracy-profile", str(profile)
    )

    assert output["measured_accuracy"]["bores"][0]["measured_exceeds_bound"] is True


def test_a_profile_for_another_printer_or_material_is_refused(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    (tmp_path / "first").mkdir()
    _, first = build(capsys, tmp_path / "first", part)
    one_trial(capsys, first["build_record"])
    one_trial(capsys, first["build_record"])
    profile = tmp_path / "guide.json"
    run(
        capsys,
        "guide",
        "derive",
        "--evidence-root",
        str(tmp_path / "first"),
        "--output",
        str(profile),
    )
    guide = tmp_path / "second" / "guide.json"
    guide.parent.mkdir()
    guide.write_text((tmp_path / "first" / "guide.json").read_text())

    assert (
        main(
            [
                "guide",
                "build",
                "--guide-file",
                str(guide),
                "--output-directory",
                str(tmp_path / "second" / "pla"),
                "--printer-profile",
                str(A1_MINI),
                "--material-profile",
                "pla",
                "--accuracy-profile",
                str(profile),
            ]
        )
        == 1
    )
    assert "is for petg" in capsys.readouterr().err

    assert (
        main(
            [
                "guide",
                "build",
                "--guide-file",
                str(guide),
                "--output-directory",
                str(tmp_path / "second" / "other"),
                "--printer-profile",
                str(DEFAULT_FDM),
                "--accuracy-profile",
                str(profile),
            ]
        )
        == 1
    )
    assert "is for printer" in capsys.readouterr().err


def test_derive_refuses_with_too_few_trials(
    capsys: pytest.CaptureFixture[str], part: Path, tmp_path: Path
) -> None:
    (tmp_path / "first").mkdir()
    _, first = build(capsys, tmp_path / "first", part)
    one_trial(capsys, first["build_record"])

    assert (
        main(
            [
                "guide",
                "derive",
                "--evidence-root",
                str(tmp_path / "first"),
                "--output",
                str(tmp_path / "p.json"),
            ]
        )
        == 1
    )
    assert "needs at least 2" in capsys.readouterr().err

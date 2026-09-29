"""Compensation profiles pooled from recorded trials, and applying them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.profiles import (
    derive_compensation_profile,
    load_compensation_profile,
    write_compensation_profile,
)
from zcad_core.retention import compensated_policy

PRINTER, MATERIAL = "bambu-lab-a1-mini", "petg"
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)


def write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def fixture_trial(
    root: Path,
    name: str,
    measurements: dict[str, tuple[float, float]],
    *,
    printer: str = PRINTER,
    pending: bool = False,
) -> Path:
    return write(
        root / name / "trials" / "trial-001" / "physical-validation.json",
        {
            "printer_profile": printer,
            "material_profile": MATERIAL,
            "disposition": "pending" if pending else "revise",
            "completed_at_utc": "" if pending else "2026-10-01T00:00:00+00:00",
            "measurements": [
                {"name": key, "nominal_mm": nominal, "value_mm": value}
                for key, (nominal, value) in measurements.items()
            ],
        },
    )


def enclosure_trial(root: Path, compensation: float, lid_hole: float) -> Path:
    build = write(
        root / "enclosures" / "case" / "enclosure.json",
        {"design": {"hole_compensation_mm": compensation}},
    )
    return write(
        root / "enclosures" / "case" / "trials" / "trial-001" / "enclosure-trial.json",
        {
            "printer_profile_id": PRINTER,
            "material_profile_id": MATERIAL,
            "build_record_path": str(build),
            "measurements": [
                {
                    "name": "lid_hole_diameter_mm",
                    "nominal_mm": 3.4,
                    "value_mm": lid_hole,
                }
            ],
        },
    )


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    fixture_trial(
        root, "a", {"board_clearance": (0.25, 0.15), "vertical_play": (0.85, 0.75)}
    )
    fixture_trial(root, "b", {"board_clearance": (0.30, 0.10)})
    # Neither of these counts: one is unprinted, one another printer's.
    fixture_trial(root, "c", {"board_clearance": (0.25, 0.0)}, pending=True)
    fixture_trial(root, "d", {"board_clearance": (0.25, 0.0)}, printer="other")
    # Modelled 0.2 mm wide, so a 3.4 mm hole printed 3.3 is 0.3 mm short.
    enclosure_trial(root, compensation=0.2, lid_hole=3.3)
    return root


def test_profile_pools_each_figure_across_trials(evidence: Path) -> None:
    profile = derive_compensation_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id=MATERIAL
    )
    figures = profile["figures"]

    assert profile["profile_id"] == "bambu-lab-a1-mini-petg"
    assert profile["version"] == 1
    assert figures["side_gap_shortfall_mm"] == {
        "mean_mm": 0.15,
        "spread_mm": 0.05,
        "samples": 2,
        "trials": 2,
    }
    assert figures["vertical_play_shortfall_mm"]["mean_mm"] == 0.1
    assert figures["hole_shortfall_mm"]["mean_mm"] == 0.3
    assert len(profile["sources"]) == 3
    assert all(len(source["sha256"]) == 64 for source in profile["sources"])


def test_profile_needs_several_trials(tmp_path: Path) -> None:
    fixture_trial(tmp_path, "a", {"board_clearance": (0.25, 0.15)})

    with pytest.raises(ValueError, match="1 recorded trial"):
        derive_compensation_profile(
            tmp_path, printer_profile_id=PRINTER, material_profile_id=MATERIAL
        )


def test_profiles_only_move_forward(evidence: Path, tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    first = derive_compensation_profile(
        evidence, printer_profile_id=PRINTER, material_profile_id=MATERIAL
    )
    write_compensation_profile(first, path)
    second = derive_compensation_profile(
        evidence,
        printer_profile_id=PRINTER,
        material_profile_id=MATERIAL,
        previous=first,
    )

    assert second["version"] == 2
    assert second["history"][0]["version"] == 1
    with pytest.raises(FileExistsError, match="at version 1"):
        write_compensation_profile(first, path)
    write_compensation_profile(second, path)
    loaded = load_compensation_profile(path)
    assert loaded.reference()["version"] == 2
    assert loaded.mean("hole_shortfall_mm") == 0.3


def candidate(directory: Path) -> Path:
    write(
        directory / "candidate.json",
        {
            "schema_version": "1.0.0",
            "candidate_id": "board-corner-capture-r001",
            "target_id": "board",
            "revision": "r001",
            "source_sha256": "a" * 64,
            "output_sha256": "b" * 64,
            "git_commit": "c" * 40,
            "generator_version": "1.4.0",
            "retention_policy": {
                "arm_width_mm": 3.0,
                "board_clearance_mm": 0.25,
                "engagement_depth_mm": 2.0,
                "minimum_wall_mm": 1.2,
                "vertical_overlap_mm": 0.6,
            },
            "derived_parameters": {"board_thickness_mm": 1.6},
            "selected_corners": ["negative_x_negative_y", "positive_x_positive_y"],
            "automated_decision": "verified_candidate",
            "automated_evidence_path": "automated-validation.json",
            "fixture_artifact_path": "fixture.stl",
            "created_at_utc": "2026-01-01T00:00:00+00:00",
        },
    )
    return directory


def test_profile_corrects_a_candidates_fit(evidence: Path, tmp_path: Path) -> None:
    path = write_compensation_profile(
        derive_compensation_profile(
            evidence, printer_profile_id=PRINTER, material_profile_id=MATERIAL
        ),
        tmp_path / "profile.json",
    )

    record = compensated_policy(
        candidate(tmp_path / "r001"), load_compensation_profile(path)
    )

    # Side gap prints 0.15 tight; play prints 0.10 tight, so the modelled
    # play grows to 0.95 and the overlap to 0.95 - 0.40.
    assert {
        change["parameter"]: change["current_value"] for change in record["changes"]
    } == {
        "board_clearance_mm": 0.4,
        "vertical_overlap_mm": 0.55,
    }
    assert record["profile"]["version"] == 1


def test_profile_is_not_applied_twice(evidence: Path, tmp_path: Path) -> None:
    path = write_compensation_profile(
        derive_compensation_profile(
            evidence, printer_profile_id=PRINTER, material_profile_id=MATERIAL
        ),
        tmp_path / "profile.json",
    )
    directory = candidate(tmp_path / "r002")
    write(directory / "compensation.json", {})

    with pytest.raises(ValueError, match="already corrected"):
        compensated_policy(directory, load_compensation_profile(path))


def test_enclosure_build_takes_hole_compensation_from_a_profile(
    evidence: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = write_compensation_profile(
        derive_compensation_profile(
            evidence, printer_profile_id=PRINTER, material_profile_id=MATERIAL
        ),
        tmp_path / "profile.json",
    )
    arguments = [
        "enclosure",
        "build",
        "--board",
        "raspberry_pi_pico_2",
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--compensation-profile",
        str(profile),
    ]

    assert main([*arguments, "--output-directory", str(tmp_path / "out")]) == 0
    record = json.loads((tmp_path / "out" / "enclosure.json").read_text("utf-8"))
    capsys.readouterr()

    assert record["design"]["hole_compensation_mm"] == 0.3
    assert record["compensation_profile"]["version"] == 1
    assert (
        main(
            [
                *arguments,
                "--hole-compensation-mm",
                "0.1",
                "--output-directory",
                str(tmp_path / "x"),
            ]
        )
        == 1
    )
    assert "not both" in capsys.readouterr().err


def test_cli_derives_the_next_version(
    evidence: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "profile.json"
    arguments = [
        "compensation",
        "derive",
        "--evidence-root",
        str(evidence),
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    assert main(arguments) == 0
    capsys.readouterr()

    assert json.loads(output.read_text("utf-8"))["version"] == 2

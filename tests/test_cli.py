from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.retention import load_export_validation_record

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[1] / "profiles/printers/bambu-lab-a1-mini.json"
)


def run(
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, dict[str, object]]:
    exit_code = main(list(args))
    output = json.loads(capsys.readouterr().out)

    return exit_code, output


def export_synthetic_board(path: Path) -> None:
    """A real, cadquery-importable single-solid board, clear of components."""

    pcb = (
        cq.Workplane("XY")
        .box(
            40.0,
            30.0,
            1.6,
        )
        .translate(
            (
                0.0,
                0.0,
                0.8,
            )
        )
    )

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )
    assembly.export(
        str(path),
        exportType="STEP",
    )


def register_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    board: cq.Workplane | None = None,
) -> Path:
    source_model = tmp_path / "board.step"

    if board is None:
        source_model.write_bytes(b"synthetic step contents")
    else:
        cq.exporters.export(board, str(source_model))

    output = tmp_path / "target.json"

    exit_code, _ = run(
        capsys,
        "target",
        "register",
        "--target-id",
        "synthetic-target",
        "--display-name",
        "Synthetic Target",
        "--manufacturer",
        "Acme",
        "--product-family",
        "Widgets",
        "--source-model-path",
        str(source_model),
        "--pcb-solid-index",
        "1",
        "--output",
        str(output),
    )

    assert exit_code == 0

    return output


def register_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target_manifest: Path,
    *,
    revision: str = "r001",
    strategy: str = "corner-capture",
    retention_part: cq.Workplane | None = None,
    embedded_board: bool = False,
) -> Path:
    evidence = tmp_path / "automated-validation.json"
    evidence.write_text(
        json.dumps(
            {
                "policy": {
                    "arm_width_mm": 3.0,
                    "board_clearance_mm": 0.25,
                    "engagement_depth_mm": 2.0,
                    "minimum_wall_mm": 1.2,
                    "vertical_overlap_mm": 0.6,
                },
                "pcb": {"z_length_mm": 1.6},
                "selected_corners": [
                    "negative_x_negative_y",
                    "positive_x_positive_y",
                ],
                "decision": "verified_candidate",
            }
        ),
        encoding="utf-8",
    )

    # Real geometry so candidates can pass 'candidate revalidate'.
    part = cq.Workplane("XY").box(20.0, 10.0, 5.0)
    retention_step = tmp_path / "retention.step"
    cq.exporters.export(
        part if retention_part is None else retention_part, str(retention_step)
    )

    fixture = tmp_path / "fixture.stl"
    cq.exporters.export(part, str(fixture))

    output = tmp_path / f"candidates/{revision}/candidate.json"

    exit_code, _ = run(
        capsys,
        "candidate",
        "register",
        "--target-manifest",
        str(target_manifest),
        "--automated-evidence",
        str(evidence),
        "--retention-step",
        str(retention_step),
        "--fixture",
        str(fixture),
        "--revision",
        revision,
        "--strategy",
        strategy,
        "--git-commit",
        "abc123",
        "--printer-profile",
        str(PRINTER_PROFILE),
        *(() if embedded_board else ("--no-embedded-board",)),
        "--output",
        str(output),
    )

    assert exit_code == 0

    return output


def revalidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    candidate_manifest: Path,
) -> Path:
    exit_code, result = run(
        capsys,
        "candidate",
        "revalidate",
        "--candidate-manifest",
        str(candidate_manifest),
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--validation-root",
        str(candidate_manifest.parent / "export-validation"),
        "--repository-root",
        str(tmp_path),
    )

    assert exit_code == 0
    assert result["evaluated_status"] == "PASS"

    return Path(str(result["export_validation_record"]))


def write_observations(tmp_path: Path, *, all_passed: bool = True) -> Path:
    path = tmp_path / "observations.json"
    checks = (
        "print_completed",
        "no_visible_defects",
        "board_inserts_without_force",
        "board_seats_fully",
        "board_retains_when_inverted",
        "connectors_remain_accessible",
        "components_remain_clear",
        "board_removes_without_damage",
    )
    path.write_text(
        json.dumps({check: {"passed": all_passed} for check in checks}),
        encoding="utf-8",
    )

    return path


def register_trial(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    candidate_manifest: Path,
    *,
    revision: str,
    passed: bool = True,
) -> Path:
    fixture = tmp_path / "fixture.stl"

    if not fixture.exists():
        fixture.write_bytes(b"synthetic fixture")

    physical_record = tmp_path / f"candidates/{revision}/trials/trial-001/physical.json"

    exit_code, _ = run(
        capsys,
        "trial",
        "complete",
        "--candidate-report",
        str(candidate_manifest),
        "--fixture-stl",
        str(fixture),
        "--printer-profile",
        "bambu-lab-a1-mini",
        "--material-profile",
        "petg",
        "--slicer-profile",
        "bambu-studio-a1-mini-petg-validation",
        "--observations",
        str(write_observations(tmp_path, all_passed=passed)),
        "--disposition",
        ("pass" if passed else "revise"),
        "--output",
        str(physical_record),
    )
    assert exit_code == 0

    trial_manifest = tmp_path / f"candidates/{revision}/trials/trial-001/trial.json"

    exit_code, _ = run(
        capsys,
        "trial",
        "register",
        "--candidate-manifest",
        str(candidate_manifest),
        "--physical-validation-record",
        str(physical_record),
        "--fixture",
        str(fixture),
        "--trial-id",
        "trial-001",
        "--output",
        str(trial_manifest),
    )
    assert exit_code == 0

    return trial_manifest


def test_target_register_writes_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = register_target(tmp_path, capsys)

    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["target_id"] == "synthetic-target"
    assert len(payload["source_model_sha256"]) == 64


def test_candidate_register_bootstraps_root_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)

    payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))

    assert payload["candidate_id"] == "synthetic-target-corner-capture-r001"
    assert payload["automated_decision"] == "verified_candidate"
    assert payload["strategy"] == "corner-capture"


def test_candidate_register_accepts_a_different_strategy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression test: the CLI used to hardcode strategy="corner-capture"
    in the candidate id regardless of which strategy produced the
    evidence, so an edge-clip candidate would get a misleading id."""

    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(
        tmp_path,
        capsys,
        target_manifest,
        strategy="edge-clip",
    )

    payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))

    assert payload["candidate_id"] == "synthetic-target-edge-clip-r001"
    assert payload["strategy"] == "edge-clip"


def test_candidate_derive_registers_child_revision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    parent_manifest = register_candidate(tmp_path, capsys, target_manifest)

    exit_code, output = run(
        capsys,
        "candidate",
        "derive",
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--parent",
        str(parent_manifest),
        "--revision",
        "r002",
        "--set",
        "board_clearance_mm=0.30",
        "--relationship",
        "supersedes",
        "--reason",
        "Increase clearance.",
        "--automated-decision",
        "synthetic_revision_candidate",
        "--output-directory",
        str(tmp_path / "candidates/r002"),
    )

    assert exit_code == 0
    assert output["candidate_id"] == "synthetic-target-corner-capture-r002"
    assert output["changed_parameters"] == ["board_clearance_mm"]


def test_candidate_derive_rejects_malformed_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    parent_manifest = register_candidate(tmp_path, capsys, target_manifest)

    exit_code = main(
        [
            "candidate",
            "derive",
            "--retention-step",
            str(tmp_path / "retention.step"),
            "--printer-profile",
            str(PRINTER_PROFILE),
            "--parent",
            str(parent_manifest),
            "--revision",
            "r002",
            "--set",
            "board_clearance_mm",
            "--relationship",
            "supersedes",
            "--reason",
            "Increase clearance.",
            "--automated-decision",
            "synthetic_revision_candidate",
            "--output-directory",
            str(tmp_path / "candidates/r002"),
        ]
    )

    assert exit_code == 1


def test_candidate_inspect_prints_manifest_contents(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)

    exit_code = main(["candidate", "inspect", "--manifest", str(target_manifest)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["target_id"] == "synthetic-target"


def test_candidate_inspect_fails_closed_on_missing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        ["candidate", "inspect", "--manifest", str(tmp_path / "missing.json")]
    )
    stderr = capsys.readouterr().err

    assert exit_code == 1
    assert "error:" in stderr


def test_trial_start_creates_pending_record(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate_report = tmp_path / "candidate.json"
    candidate_report.write_text("{}", encoding="utf-8")
    fixture = tmp_path / "fixture.stl"
    fixture.write_bytes(b"synthetic fixture")
    output = tmp_path / "physical-validation.json"

    exit_code, result = run(
        capsys,
        "trial",
        "start",
        "--candidate-report",
        str(candidate_report),
        "--fixture-stl",
        str(fixture),
        "--printer-profile",
        "bambu-lab-a1-mini",
        "--material-profile",
        "petg",
        "--slicer-profile",
        "bambu-studio-a1-mini-petg-validation",
        "--output",
        str(output),
    )

    assert exit_code == 0
    assert result["disposition"] == "revise"

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is False


def test_trial_complete_and_register_produce_passing_trial(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)

    trial_manifest = register_trial(
        tmp_path,
        capsys,
        candidate_manifest,
        revision="r001",
        passed=True,
    )

    payload = json.loads(trial_manifest.read_text(encoding="utf-8"))

    assert payload["passed"] is True
    assert payload["complete"] is True


def test_revision_compare_flags_missing_trial_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    source_manifest = register_candidate(tmp_path, capsys, target_manifest)

    exit_code, source_source_trial = run(
        capsys,
        "candidate",
        "derive",
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--parent",
        str(source_manifest),
        "--revision",
        "r002",
        "--set",
        "board_clearance_mm=0.30",
        "--relationship",
        "supersedes",
        "--reason",
        "Increase clearance.",
        "--automated-decision",
        "synthetic_revision_candidate",
        "--output-directory",
        str(tmp_path / "candidates/r002"),
    )
    assert exit_code == 0
    target_manifest_path = Path(source_source_trial["candidate_manifest"])

    exit_code, comparison = run(
        capsys,
        "revision",
        "compare",
        "--source-candidate",
        str(source_manifest),
        "--target-candidate",
        str(target_manifest_path),
        "--report-output",
        str(tmp_path / "comparison.json"),
        "--recommendation-output",
        str(tmp_path / "recommendation.json"),
    )

    assert exit_code == 0
    assert comparison["decision"] == "insufficient_evidence"


def test_candidate_promote_and_status_report_preferred_revision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)

    exit_code, derive_result = run(
        capsys,
        "candidate",
        "derive",
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--parent",
        str(candidate_manifest),
        "--revision",
        "r002",
        "--set",
        "board_clearance_mm=0.30",
        "--relationship",
        "supersedes",
        "--reason",
        "Increase clearance.",
        "--automated-decision",
        "verified_candidate",
        "--output-directory",
        str(tmp_path / "candidates/r002"),
    )
    assert exit_code == 0

    child_manifest = Path(derive_result["candidate_manifest"])
    relationship_manifest = Path(derive_result["relationship_manifest"])
    parameter_delta_manifest = Path(derive_result["parameter_delta_report"])

    trial_manifest = register_trial(
        tmp_path,
        capsys,
        child_manifest,
        revision="r002",
        passed=True,
    )
    child_export = Path(str(derive_result["export_validation_record"]))

    exit_code, promotion = run(
        capsys,
        "candidate",
        "promote",
        "--candidate-manifest",
        str(child_manifest),
        "--relationship-path",
        str(relationship_manifest),
        "--parameter-delta-path",
        str(parameter_delta_manifest),
        "--physical-trial-path",
        str(trial_manifest),
        "--target-root",
        str(tmp_path),
        "--reviewer",
        "operator",
        "--reason",
        "Passed automated and physical validation.",
        "--export-validation",
        str(child_export),
        "--physical-validation-passed",
        "--output",
        str(tmp_path / "candidates/r002/promotion.json"),
    )

    assert exit_code == 0
    assert promotion["decision"] == "promoted"

    exit_code, status = run(
        capsys,
        "status",
        "--target-root",
        str(tmp_path),
    )

    assert exit_code == 0
    assert status["preferred_candidate_id"] == "synthetic-target-corner-capture-r002"
    assert status["publication_eligible"] is True


def test_candidate_promote_records_rejected_decision_without_passing_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)

    trial_manifest = register_trial(
        tmp_path,
        capsys,
        candidate_manifest,
        revision="r001",
        passed=False,
    )

    promotion_path = tmp_path / "candidates/r001/promotion.json"

    exit_code, promotion = run(
        capsys,
        "candidate",
        "promote",
        "--candidate-manifest",
        str(candidate_manifest),
        "--physical-trial-path",
        str(trial_manifest),
        "--target-root",
        str(tmp_path),
        "--reviewer",
        "operator",
        "--reason",
        "Physical trial failed fit check.",
        "--decision",
        "rejected",
        "--output",
        str(promotion_path),
    )

    assert exit_code == 0
    assert promotion["decision"] == "rejected"

    payload = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert payload["decision"] == "rejected"
    assert payload["physical_validation_passed"] is False

    exit_code, status = run(
        capsys,
        "status",
        "--target-root",
        str(tmp_path),
    )

    assert exit_code == 0
    assert status["preferred_candidate_id"] is None


def test_candidate_promote_requires_supersession_for_new_preferred(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    r001 = register_candidate(tmp_path, capsys, target_manifest)

    exit_code, derive_result = run(
        capsys,
        "candidate",
        "derive",
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--parent",
        str(r001),
        "--revision",
        "r002",
        "--set",
        "board_clearance_mm=0.30",
        "--relationship",
        "supersedes",
        "--reason",
        "Increase clearance.",
        "--automated-decision",
        "verified_candidate",
        "--output-directory",
        str(tmp_path / "candidates/r002"),
    )
    assert exit_code == 0
    r002 = Path(derive_result["candidate_manifest"])
    r002_relationship = Path(derive_result["relationship_manifest"])
    r002_delta = Path(derive_result["parameter_delta_report"])

    exit_code, derive_result_2 = run(
        capsys,
        "candidate",
        "derive",
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--parent",
        str(r002),
        "--revision",
        "r003",
        "--set",
        "board_clearance_mm=0.35",
        "--relationship",
        "supersedes",
        "--reason",
        "Increase clearance further.",
        "--automated-decision",
        "verified_candidate",
        "--output-directory",
        str(tmp_path / "candidates/r003"),
    )
    assert exit_code == 0
    r003 = Path(derive_result_2["candidate_manifest"])
    r003_relationship = Path(derive_result_2["relationship_manifest"])
    r003_delta = Path(derive_result_2["parameter_delta_report"])

    r002_trial = register_trial(
        tmp_path,
        capsys,
        r002,
        revision="r002",
        passed=True,
    )
    r003_trial = register_trial(
        tmp_path,
        capsys,
        r003,
        revision="r003",
        passed=True,
    )
    r002_export = Path(str(derive_result["export_validation_record"]))
    r003_export = Path(str(derive_result_2["export_validation_record"]))

    exit_code, _ = run(
        capsys,
        "candidate",
        "promote",
        "--candidate-manifest",
        str(r002),
        "--relationship-path",
        str(r002_relationship),
        "--parameter-delta-path",
        str(r002_delta),
        "--physical-trial-path",
        str(r002_trial),
        "--target-root",
        str(tmp_path),
        "--reviewer",
        "operator",
        "--reason",
        "First preferred revision.",
        "--export-validation",
        str(r002_export),
        "--physical-validation-passed",
        "--output",
        str(tmp_path / "candidates/r002/promotion.json"),
    )
    assert exit_code == 0

    exit_code = main(
        [
            "candidate",
            "promote",
            "--candidate-manifest",
            str(r003),
            "--relationship-path",
            str(r003_relationship),
            "--parameter-delta-path",
            str(r003_delta),
            "--physical-trial-path",
            str(r003_trial),
            "--target-root",
            str(tmp_path),
            "--reviewer",
            "operator",
            "--reason",
            "Further improvement.",
            "--export-validation",
            str(r003_export),
            "--physical-validation-passed",
            "--output",
            str(tmp_path / "candidates/r003/promotion.json"),
        ]
    )
    stderr = capsys.readouterr().err

    assert exit_code == 1
    assert "requires supersedes_candidate_id" in stderr

    exit_code, promotion = run(
        capsys,
        "candidate",
        "promote",
        "--candidate-manifest",
        str(r003),
        "--relationship-path",
        str(r003_relationship),
        "--parameter-delta-path",
        str(r003_delta),
        "--physical-trial-path",
        str(r003_trial),
        "--target-root",
        str(tmp_path),
        "--reviewer",
        "operator",
        "--reason",
        "Further improvement.",
        "--export-validation",
        str(r003_export),
        "--physical-validation-passed",
        "--supersedes-candidate-id",
        "synthetic-target-corner-capture-r002",
        "--output",
        str(tmp_path / "candidates/r003/promotion.json"),
    )

    assert exit_code == 0
    assert promotion["decision"] == "promoted"
    assert promotion["superseded"] == "synthetic-target-corner-capture-r002"

    exit_code, status = run(
        capsys,
        "status",
        "--target-root",
        str(tmp_path),
    )

    assert status["preferred_candidate_id"] == "synthetic-target-corner-capture-r003"


def test_candidate_create_corner_capture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_step = tmp_path / "board.step"
    export_synthetic_board(source_step)

    exit_code, result = run(
        capsys,
        "candidate",
        "create",
        "--strategy",
        "corner-capture",
        "--source-step",
        str(source_step),
        "--pcb-solid-index",
        "1",
        "--output-step",
        str(tmp_path / "capture.step"),
        "--report-output",
        str(tmp_path / "capture.json"),
    )

    assert exit_code == 0
    assert result["passed"] is True
    assert result["strategy"] == "corner-capture"
    assert len(result["selected"]) == 2
    assert Path(result["step"]).is_file()

    report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
    assert report["decision"] == "verified_candidate"


def test_candidate_create_edge_clip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_step = tmp_path / "board.step"
    export_synthetic_board(source_step)

    exit_code, result = run(
        capsys,
        "candidate",
        "create",
        "--strategy",
        "edge-clip",
        "--source-step",
        str(source_step),
        "--pcb-solid-index",
        "1",
        "--output-step",
        str(tmp_path / "capture.step"),
        "--report-output",
        str(tmp_path / "capture.json"),
    )

    assert exit_code == 0
    assert result["passed"] is True
    assert result["strategy"] == "edge-clip"
    assert result["selected"][0] in {
        "negative_x",
        "positive_x",
        "negative_y",
        "positive_y",
    }
    assert Path(result["step"]).is_file()


def test_candidate_create_rejects_unsupported_strategy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_step = tmp_path / "board.step"
    export_synthetic_board(source_step)

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "candidate",
                "create",
                "--strategy",
                "not-a-real-strategy",
                "--source-step",
                str(source_step),
                "--pcb-solid-index",
                "1",
                "--output-step",
                str(tmp_path / "capture.step"),
                "--report-output",
                str(tmp_path / "capture.json"),
            ]
        )

    assert excinfo.value.code == 2


def test_fixture_export_corner_capture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_step = tmp_path / "board.step"
    export_synthetic_board(source_step)

    exit_code, result = run(
        capsys,
        "fixture",
        "export",
        "--strategy",
        "corner-capture",
        "--source-step",
        str(source_step),
        "--pcb-solid-index",
        "1",
        "--output-step",
        str(tmp_path / "capture.step"),
        "--output",
        str(tmp_path / "fixture.stl"),
    )

    assert exit_code == 0
    assert result["strategy"] == "corner-capture"

    fixture_path = Path(result["fixture"])
    assert fixture_path.is_file()
    assert fixture_path.stat().st_size > 0


def test_fixture_export_edge_clip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_step = tmp_path / "board.step"
    export_synthetic_board(source_step)

    exit_code, result = run(
        capsys,
        "fixture",
        "export",
        "--strategy",
        "edge-clip",
        "--source-step",
        str(source_step),
        "--pcb-solid-index",
        "1",
        "--output-step",
        str(tmp_path / "capture.step"),
        "--output",
        str(tmp_path / "fixture.stl"),
    )

    assert exit_code == 0
    assert result["strategy"] == "edge-clip"

    fixture_path = Path(result["fixture"])
    assert fixture_path.is_file()
    assert fixture_path.stat().st_size > 0


def test_report_aggregates_candidates_trials_and_promotion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)

    trial_manifest = register_trial(
        tmp_path,
        capsys,
        candidate_manifest,
        revision="r001",
        passed=True,
    )
    r001_export = revalidate(tmp_path, capsys, candidate_manifest)

    exit_code, promotion = run(
        capsys,
        "candidate",
        "promote",
        "--candidate-manifest",
        str(candidate_manifest),
        "--physical-trial-path",
        str(trial_manifest),
        "--target-root",
        str(tmp_path),
        "--reviewer",
        "operator",
        "--reason",
        "First verified candidate with a passing physical trial.",
        "--export-validation",
        str(r001_export),
        "--physical-validation-passed",
        "--output",
        str(tmp_path / "candidates/r001/promotion.json"),
    )
    assert exit_code == 0
    assert promotion["decision"] == "promoted"

    exit_code, report = run(
        capsys,
        "report",
        "--target-root",
        str(tmp_path),
    )

    assert exit_code == 0
    assert report["target_id"] == "synthetic-target"
    assert report["candidate_count"] == 1
    assert report["preferred_candidate_id"] == "synthetic-target-corner-capture-r001"
    assert report["publication_eligible"] is True

    candidate_report = report["candidates"][0]
    assert candidate_report["strategy"] == "corner-capture"
    assert candidate_report["trial_count"] == 1
    assert candidate_report["trials_passed"] == 1
    assert candidate_report["promotion"]["decision"] == "promoted"
    assert candidate_report["promotion"]["reviewer"] == "operator"


def test_candidate_promote_requires_export_validation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)
    trial_manifest = register_trial(
        tmp_path,
        capsys,
        candidate_manifest,
        revision="r001",
        passed=True,
    )

    exit_code = main(
        [
            "candidate",
            "promote",
            "--candidate-manifest",
            str(candidate_manifest),
            "--physical-trial-path",
            str(trial_manifest),
            "--target-root",
            str(tmp_path),
            "--reviewer",
            "operator",
            "--reason",
            "Missing export validation.",
            "--physical-validation-passed",
            "--output",
            str(tmp_path / "candidates/r001/promotion.json"),
        ]
    )

    assert exit_code == 1
    assert "export_validation_missing" in capsys.readouterr().err
    assert not (tmp_path / "candidates/r001/promotion.json").exists()


def test_candidate_revalidate_rejects_unregistered_retention_step(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    candidate_manifest = register_candidate(tmp_path, capsys, target_manifest)
    other_step = tmp_path / "other.step"
    cq.exporters.export(cq.Workplane("XY").box(5.0, 5.0, 5.0), str(other_step))

    exit_code = main(
        [
            "candidate",
            "revalidate",
            "--candidate-manifest",
            str(candidate_manifest),
            "--retention-step",
            str(other_step),
            "--printer-profile",
            str(PRINTER_PROFILE),
            "--validation-root",
            str(tmp_path / "export-validation"),
        ]
    )

    assert exit_code == 1
    assert "does not match candidate output_sha256" in capsys.readouterr().err


def test_candidate_revalidate_reports_embedded_board_as_non_gating(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    board = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    arm = cq.Workplane("XY").box(2.0, 5.0, 3.0).translate((25.0, 0.0, 1.5))
    target_manifest = register_target(tmp_path, capsys, board=board)
    candidate_manifest = register_candidate(
        tmp_path,
        capsys,
        target_manifest,
        retention_part=cq.Workplane("XY").newObject([board.val(), arm.val()]),
        embedded_board=True,
    )

    registered = load_export_validation_record(
        candidate_manifest.parent / "export-validation/v001/export-validation.json"
    )
    assert registered.evaluated_status == "PASS"
    assert registered.artifact("reference_board").gating is False

    exit_code, result = run(
        capsys,
        "candidate",
        "revalidate",
        "--candidate-manifest",
        str(candidate_manifest),
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--target-manifest",
        str(target_manifest),
        "--validation-root",
        str(tmp_path / "export-validation"),
    )

    assert exit_code == 0
    assert result["evaluated_status"] == "PASS"
    assert result["artifacts"] == {
        "retention": "PASS",
        "reference_board": "PASS",
        "fixture": "PASS",
    }
    assert result["non_gating_roles"] == ["reference_board"]


def test_candidate_register_records_failing_export_validation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Oversized geometry still registers, but its failing run blocks promotion."""

    target_manifest = register_target(tmp_path, capsys)
    oversized = cq.Workplane("XY").box(300.0, 10.0, 5.0)
    cq.exporters.export(oversized, str(tmp_path / "retention.step"))
    cq.exporters.export(oversized, str(tmp_path / "fixture.stl"))
    evidence = tmp_path / "automated-validation.json"
    evidence.write_text(
        json.dumps(
            {
                "policy": {"board_clearance_mm": 0.25},
                "pcb": {"z_length_mm": 1.6},
                "selected_corners": ["negative_x_negative_y"],
                "decision": "verified_candidate",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "candidates/r001/candidate.json"

    exit_code, result = run(
        capsys,
        "candidate",
        "register",
        "--target-manifest",
        str(target_manifest),
        "--automated-evidence",
        str(evidence),
        "--retention-step",
        str(tmp_path / "retention.step"),
        "--fixture",
        str(tmp_path / "fixture.stl"),
        "--revision",
        "r001",
        "--git-commit",
        "abc123",
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--no-embedded-board",
        "--output",
        str(output),
    )

    assert exit_code == 1
    assert output.is_file()
    assert result["export_validation_status"] == "FAIL"
    assert Path(str(result["export_validation_record"])).is_file()


def test_candidate_derive_rejects_step_other_than_parents(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target_manifest = register_target(tmp_path, capsys)
    parent = register_candidate(tmp_path, capsys, target_manifest)
    other_step = tmp_path / "other.step"
    cq.exporters.export(cq.Workplane("XY").box(5.0, 5.0, 5.0), str(other_step))

    exit_code = main(
        [
            "candidate",
            "derive",
            "--parent",
            str(parent),
            "--revision",
            "r002",
            "--set",
            "board_clearance_mm=0.30",
            "--relationship",
            "supersedes",
            "--reason",
            "Increase clearance.",
            "--automated-decision",
            "verified_candidate",
            "--output-directory",
            str(tmp_path / "candidates/r002"),
            "--retention-step",
            str(other_step),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )

    assert exit_code == 1
    assert "does not match candidate output_sha256" in capsys.readouterr().err
    assert not (tmp_path / "candidates/r002").exists()

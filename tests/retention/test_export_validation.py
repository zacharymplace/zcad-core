"""Export validation binds candidates to the export pipeline without rewriting
earlier evidence."""

from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CandidateRevision,
    ExportValidationArtifact,
    ExportValidationRecord,
    ReferenceBoard,
    ValidationTarget,
    export_validation,
    load_export_validation_record,
    run_candidate_export_validation,
    verify_export_validation,
)
from zcad_core.retention.validation_lab import sha256_file
from zcad_core.validation.design_report import DesignValidationError

PRINTER_PROFILE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
    ).read_text(encoding="utf-8")
)


BOARD = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8)).val()
ARM = cq.Workplane("XY").box(2.0, 5.0, 3.0).translate((25.0, 0.0, 1.5)).val()
COMPONENT = cq.Workplane("XY").box(4.0, 4.0, 2.0).translate((0.0, 0.0, 2.6)).val()


def make_candidate(
    tmp_path: Path,
    *,
    fixture_suffix: str = ".stl",
    fixture_bytes: bytes | None = None,
    retention: cq.Workplane | None = None,
    source_sha256: str = "0" * 64,
) -> tuple[CandidateRevision, Path]:
    part = cq.Workplane("XY").box(20.0, 10.0, 5.0)
    retention_step = tmp_path / "retention.step"
    cq.exporters.export(part if retention is None else retention, str(retention_step))

    fixture = tmp_path / f"fixture{fixture_suffix}"

    if fixture_bytes is None:
        cq.exporters.export(part, str(fixture))
    else:
        fixture.write_bytes(fixture_bytes)

    candidate = CandidateRevision(
        schema_version="1.0.0",
        candidate_id="synthetic-target-corner-capture-r001",
        target_id="synthetic-target",
        revision="r001",
        source_sha256=source_sha256,
        output_sha256=sha256_file(retention_step),
        git_commit="abc123",
        generator_version="1.0.0",
        retention_policy={"board_clearance_mm": 0.25},
        derived_parameters={"board_clearance_mm": 0.25},
        selected_corners=("negative_x_negative_y",),
        automated_decision="verified_candidate",
        automated_evidence_path="automated-validation.json",
        fixture_artifact_path=str(fixture),
        created_at_utc="2026-01-01T00:00:00+00:00",
    )

    return candidate, retention_step


def run(
    tmp_path: Path,
    candidate: CandidateRevision,
    retention_step: Path,
    target: ValidationTarget | None = None,
) -> tuple[ExportValidationRecord, Path]:
    return run_candidate_export_validation(
        candidate=candidate,
        retention_step=retention_step,
        validation_root=tmp_path / "export-validation",
        printer_profile=PRINTER_PROFILE,
        repository_root=tmp_path,
        validated_at_utc="2026-01-01T00:00:00+00:00",
        reference_board=(
            None if target is None else ReferenceBoard.from_target(target)
        ),
    )


def make_board_candidate(
    tmp_path: Path,
) -> tuple[CandidateRevision, Path, ValidationTarget]:
    """A source model with the PCB second, and a retention STEP embedding it."""

    source = tmp_path / "board.step"
    cq.exporters.export(cq.Workplane("XY").newObject([COMPONENT, BOARD]), str(source))
    target = ValidationTarget(
        schema_version="1.0.0",
        target_id="synthetic-target",
        display_name="Synthetic Target",
        manufacturer="Acme",
        product_family="Widgets",
        source_model_path=str(source),
        source_model_sha256=sha256_file(source),
        pcb_solid_index=2,
        created_at_utc="2026-01-01T00:00:00+00:00",
    )
    candidate, retention_step = make_candidate(
        tmp_path,
        retention=cq.Workplane("XY").newObject([BOARD, ARM]),
        source_sha256=target.source_model_sha256,
    )

    return candidate, retention_step, target


def test_passing_run_writes_verifiable_record(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(tmp_path)

    record, record_path = run(tmp_path, candidate, retention_step)

    assert record.run_id == "v001"
    assert record.evaluated_status == "PASS"
    assert record_path == tmp_path / "export-validation/v001/export-validation.json"
    assert load_export_validation_record(record_path) == record
    assert verify_export_validation(record, candidate=candidate) == ()

    retention = record.artifact("retention")
    assert retention.report["stl_round_trip"]["status"] == "PASS"
    assert {Path(path).name for path in retention.outputs} == {
        "retention.step",
        "retention.stl",
        "retention.metadata.json",
    }
    assert record.artifact("fixture").report["checks"][0]["code"] == "stl_topology"


def test_runs_are_append_only(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(tmp_path)
    _, first_path = run(tmp_path, candidate, retention_step)
    first_bytes = first_path.read_bytes()

    second, second_path = run(tmp_path, candidate, retention_step)

    assert second.run_id == "v002"
    assert second_path.parent.name == "v002"
    assert first_path.read_bytes() == first_bytes


def test_rejects_retention_step_not_registered_with_candidate(
    tmp_path: Path,
) -> None:
    candidate, _ = make_candidate(tmp_path)
    other = tmp_path / "other.step"
    cq.exporters.export(cq.Workplane("XY").box(5.0, 5.0, 5.0), str(other))

    with pytest.raises(ValueError, match="does not match candidate output_sha256"):
        run(tmp_path, candidate, other)

    assert not (tmp_path / "export-validation").exists()


def test_invalid_fixture_records_failure(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(tmp_path, fixture_bytes=b"not an stl")

    record, record_path = run(tmp_path, candidate, retention_step)

    assert record_path.is_file()
    assert record.evaluated_status == "FAIL"
    assert record.artifact("retention").evaluated_status == "PASS"
    assert record.artifact("fixture").evaluated_status == "FAIL"
    assert "export_validation_failed" in verify_export_validation(
        record, candidate=candidate
    )


def test_step_fixture_is_exported_through_pipeline(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(tmp_path, fixture_suffix=".step")

    record, _ = run(tmp_path, candidate, retention_step)

    fixture = record.artifact("fixture")
    assert fixture.evaluated_status == "PASS"
    assert {Path(path).name for path in fixture.outputs} == {
        "fixture.step",
        "fixture.stl",
        "fixture.metadata.json",
    }


def test_unsupported_fixture_format_fails_closed(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(
        tmp_path, fixture_suffix=".3mf", fixture_bytes=b"archive"
    )

    record, _ = run(tmp_path, candidate, retention_step)

    assert record.artifact("fixture").evaluated_status == "FAIL"
    assert record.evaluated_status == "FAIL"


def test_verification_detects_later_edits(tmp_path: Path) -> None:
    candidate, retention_step = make_candidate(tmp_path)
    record, _ = run(tmp_path, candidate, retention_step)

    Path(candidate.fixture_artifact_path).write_bytes(b"replaced fixture")
    stl_output = next(
        Path(path)
        for path in record.artifact("retention").outputs
        if path.endswith(".stl")
    )
    stl_output.write_bytes(b"replaced mesh")

    assert verify_export_validation(record, candidate=candidate) == (
        "export_validation_output_changed:retention",
        "export_validation_source_changed:fixture",
    )


def test_record_status_must_summarize_artifacts() -> None:
    artifact = ExportValidationArtifact(
        role="retention",
        source_path="retention.step",
        source_sha256="0" * 64,
        evaluated_status="FAIL",
        report={},
        outputs={},
    )

    with pytest.raises(ValueError, match="summarize artifact statuses"):
        ExportValidationRecord(
            schema_version="1.0.0",
            candidate_id="synthetic-target-corner-capture-r001",
            run_id="v001",
            printer_profile_id="bambu-lab-a1-mini",
            validated_at_utc="2026-01-01T00:00:00+00:00",
            evaluated_status="PASS",
            artifacts=(artifact,),
        )


def test_record_requires_retention_artifact() -> None:
    fixture = ExportValidationArtifact(
        role="fixture",
        source_path="fixture.stl",
        source_sha256="0" * 64,
        evaluated_status="PASS",
        report={},
        outputs={},
    )

    with pytest.raises(ValueError, match="requires a retention artifact"):
        ExportValidationRecord(
            schema_version="1.0.0",
            candidate_id="synthetic-target-corner-capture-r001",
            run_id="v001",
            printer_profile_id="bambu-lab-a1-mini",
            validated_at_utc="2026-01-01T00:00:00+00:00",
            evaluated_status="PASS",
            artifacts=(fixture,),
        )


def test_failed_artifact_cannot_carry_outputs() -> None:
    with pytest.raises(ValueError, match="cannot publish outputs"):
        ExportValidationArtifact(
            role="retention",
            source_path="retention.step",
            source_sha256="0" * 64,
            evaluated_status="FAIL",
            report={},
            outputs={"retention.stl": "0" * 64},
        )


def test_target_separates_embedded_board_from_generated_geometry(
    tmp_path: Path,
) -> None:
    candidate, retention_step, target = make_board_candidate(tmp_path)

    record, record_path = run(tmp_path, candidate, retention_step, target)

    assert record.evaluated_status == "PASS"
    board = record.artifact("reference_board")
    assert board.gating is False
    assert board.evaluated_status == "PASS"
    assert board.source_sha256 == target.source_model_sha256

    retention_output = next(
        Path(path)
        for path in record.artifact("retention").outputs
        if path.endswith(".step")
    )
    exported = cq.importers.importStep(str(retention_output)).val()
    assert exported.Volume() == pytest.approx(ARM.Volume())

    assert load_export_validation_record(record_path) == record
    assert verify_export_validation(record, candidate=candidate) == ()


def test_failing_reference_board_does_not_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, retention_step, target = make_board_candidate(tmp_path)
    real_export_parts = export_validation.export_parts

    def reject_board(request):  # type: ignore[no-untyped-def]
        if request.design_name == "reference_board":
            raise DesignValidationError(
                {
                    "evaluated_status": "FAIL",
                    "checks": [
                        {"code": "stl_topology", "status": "FAIL", "message": "x"}
                    ],
                }
            )
        return real_export_parts(request)

    monkeypatch.setattr(export_validation, "export_parts", reject_board)

    record, _ = run(tmp_path, candidate, retention_step, target)

    assert record.artifact("reference_board").evaluated_status == "FAIL"
    assert record.evaluated_status == "PASS"
    assert verify_export_validation(record, candidate=candidate) == ()


def test_target_requires_exactly_one_embedded_board(tmp_path: Path) -> None:
    (tmp_path / "board").mkdir()
    _, _, target = make_board_candidate(tmp_path / "board")
    candidate, retention_step = make_candidate(
        tmp_path, source_sha256=target.source_model_sha256
    )

    with pytest.raises(ValueError, match="found 0"):
        run(tmp_path, candidate, retention_step, target)

    assert not (tmp_path / "export-validation").exists()


def test_reference_board_must_match_candidate_source(tmp_path: Path) -> None:
    candidate, retention_step, target = make_board_candidate(tmp_path)
    other = CandidateRevision(**{**candidate.__dict__, "source_sha256": "1" * 64})

    with pytest.raises(ValueError, match="source does not match candidate"):
        run(tmp_path, other, retention_step, target)

    assert not (tmp_path / "export-validation").exists()


def test_loads_records_written_before_reference_boards(tmp_path: Path) -> None:
    path = tmp_path / "export-validation.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "candidate_id": "synthetic-target-corner-capture-r001",
                "run_id": "v001",
                "printer_profile_id": "bambu-lab-a1-mini",
                "validated_at_utc": "2026-01-01T00:00:00+00:00",
                "evaluated_status": "PASS",
                "artifacts": [
                    {
                        "role": "retention",
                        "source_path": "retention.step",
                        "source_sha256": "0" * 64,
                        "evaluated_status": "PASS",
                        "report": {},
                        "outputs": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = load_export_validation_record(path)

    assert record.artifact("retention").gating is True


@pytest.mark.parametrize(
    ("role", "gating", "message"),
    [
        ("reference_board", True, "cannot gate"),
        ("retention", False, "must gate"),
    ],
)
def test_roles_fix_gating(role: str, gating: bool, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ExportValidationArtifact(
            role=role,
            source_path="model.step",
            source_sha256="0" * 64,
            evaluated_status="PASS",
            report={},
            outputs={},
            gating=gating,
        )

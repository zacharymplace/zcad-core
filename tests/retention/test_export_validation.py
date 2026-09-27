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
    load_export_validation_record,
    run_candidate_export_validation,
    verify_export_validation,
)
from zcad_core.retention.validation_lab import sha256_file

PRINTER_PROFILE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
    ).read_text(encoding="utf-8")
)


def make_candidate(
    tmp_path: Path,
    *,
    fixture_suffix: str = ".stl",
    fixture_bytes: bytes | None = None,
) -> tuple[CandidateRevision, Path]:
    part = cq.Workplane("XY").box(20.0, 10.0, 5.0)
    retention_step = tmp_path / "retention.step"
    cq.exporters.export(part, str(retention_step))

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
        source_sha256="0" * 64,
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
) -> tuple[ExportValidationRecord, Path]:
    return run_candidate_export_validation(
        candidate=candidate,
        retention_step=retention_step,
        validation_root=tmp_path / "export-validation",
        printer_profile=PRINTER_PROFILE,
        repository_root=tmp_path,
        validated_at_utc="2026-01-01T00:00:00+00:00",
    )


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

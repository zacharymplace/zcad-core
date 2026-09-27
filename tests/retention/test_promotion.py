from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from zcad_core.retention import (
    CandidateRevision,
    ExportValidationArtifact,
    ExportValidationRecord,
    PromotionDecision,
    PromotionRecord,
    PublicationEligibility,
    build_publication_record,
    evaluate_publication_eligibility,
    promote_preferred_revision,
    select_preferred_revision,
    write_promotion_record,
)
from zcad_core.retention.validation_lab import sha256_file, write_immutable_manifest


def valid_promotion_record(
    *,
    revision: str = "r002",
) -> PromotionRecord:
    return PromotionRecord(
        schema_version="1.0.0",
        target_id="synthetic-target",
        candidate_id=(f"synthetic-target-corner-capture-{revision}"),
        decision=PromotionDecision.PROMOTED,
        reason=("Automated and physical validation passed."),
        reviewer="operator",
        automated_validation_passed=True,
        physical_validation_passed=True,
        candidate_manifest_path=(f"candidates/{revision}/candidate.json"),
        relationship_path=(f"candidates/{revision}/relationship.json"),
        parameter_delta_path=(f"candidates/{revision}/parameter-delta.json"),
        physical_trial_path=(f"candidates/{revision}/trials/trial-001/trial.json"),
        created_at_utc=("2026-01-01T00:00:00+00:00"),
    )


def write_verified_candidate(
    directory: Path,
    *,
    revision: str,
) -> tuple[Path, Path]:
    """Write a candidate manifest and a passing export-validation record."""

    directory.mkdir(parents=True, exist_ok=True)
    retention_step = directory / "retention.step"
    retention_step.write_bytes(f"retention {revision}".encode())
    digest = sha256_file(retention_step)

    candidate_path = directory / "candidate.json"
    write_immutable_manifest(
        CandidateRevision(
            schema_version="1.0.0",
            candidate_id=f"synthetic-target-corner-capture-{revision}",
            target_id="synthetic-target",
            revision=revision,
            source_sha256="0" * 64,
            output_sha256=digest,
            git_commit="abc123",
            generator_version="1.0.0",
            retention_policy={"board_clearance_mm": 0.25},
            derived_parameters={"board_clearance_mm": 0.25},
            selected_corners=("negative_x_negative_y",),
            automated_decision="verified_candidate",
            automated_evidence_path="automated-validation.json",
            fixture_artifact_path="fixture.stl",
            created_at_utc="2026-01-01T00:00:00+00:00",
        ),
        output_path=candidate_path,
    )

    record = ExportValidationRecord(
        schema_version="1.0.0",
        candidate_id=f"synthetic-target-corner-capture-{revision}",
        run_id="v001",
        printer_profile_id="bambu-lab-a1-mini",
        validated_at_utc="2026-01-01T00:00:00+00:00",
        evaluated_status="PASS",
        artifacts=(
            ExportValidationArtifact(
                role="retention",
                source_path=str(retention_step),
                source_sha256=digest,
                evaluated_status="PASS",
                report={"evaluated_status": "PASS", "checks": []},
                outputs={},
            ),
        ),
    )
    record_path = directory / "export-validation.json"
    record_path.write_text(json.dumps(asdict(record)), encoding="utf-8")

    return candidate_path, record_path


def test_publication_eligibility_passes() -> None:
    result = evaluate_publication_eligibility(
        automated_validation_passed=True,
        export_validation_failures=(),
        physical_validation_passed=True,
        candidate_manifest_exists=True,
        relationship_exists=True,
        parameter_delta_exists=True,
        physical_trial_exists=True,
    )

    assert result == PublicationEligibility(
        eligible=True,
        failures=(),
    )


def test_publication_eligibility_reports_failures() -> None:
    result = evaluate_publication_eligibility(
        automated_validation_passed=False,
        export_validation_failures=("export_validation_missing",),
        physical_validation_passed=False,
        candidate_manifest_exists=True,
        relationship_exists=False,
        parameter_delta_exists=True,
        physical_trial_exists=False,
    )

    assert result.eligible is False
    assert result.failures == (
        "automated_validation_not_passed",
        "export_validation_missing",
        "physical_validation_not_passed",
        "relationship_record_missing",
        "physical_trial_missing",
    )


def test_eligible_result_rejects_failures() -> None:
    with pytest.raises(
        ValueError,
        match=("Eligible publication cannot contain failures"),
    ):
        PublicationEligibility(
            eligible=True,
            failures=("unexpected",),
        )


def test_ineligible_result_requires_failures() -> None:
    with pytest.raises(
        ValueError,
        match=("Ineligible publication must contain failures"),
    ):
        PublicationEligibility(
            eligible=False,
            failures=(),
        )


def test_promoted_record_requires_automated_validation() -> None:
    record = valid_promotion_record()

    with pytest.raises(
        ValueError,
        match=("Promoted candidate requires automated validation"),
    ):
        PromotionRecord(
            **{
                **record.__dict__,
                "automated_validation_passed": False,
            }
        )


def test_promoted_record_requires_physical_validation() -> None:
    record = valid_promotion_record()

    with pytest.raises(
        ValueError,
        match=("Promoted candidate requires physical validation"),
    ):
        PromotionRecord(
            **{
                **record.__dict__,
                "physical_validation_passed": False,
            }
        )


def test_write_promotion_record_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "promotion.json"
    record = valid_promotion_record()

    write_promotion_record(
        record,
        output_path=path,
    )
    write_promotion_record(
        record,
        output_path=path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["decision"] == "promoted"
    assert payload["candidate_id"] == ("synthetic-target-corner-capture-r002")


def test_write_promotion_record_rejects_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "promotion.json"
    record = valid_promotion_record()

    write_promotion_record(
        record,
        output_path=path,
    )

    changed = PromotionRecord(
        **{
            **record.__dict__,
            "reason": "Changed promotion reason.",
        }
    )

    with pytest.raises(
        FileExistsError,
        match=("Refusing to overwrite immutable promotion record"),
    ):
        write_promotion_record(
            changed,
            output_path=path,
        )


def test_register_candidate_promotion_is_idempotent(
    tmp_path: Path,
) -> None:
    from zcad_core.retention import (
        register_candidate_promotion,
    )

    candidate, export_validation = write_verified_candidate(tmp_path, revision="r002")
    relationship = tmp_path / "relationship.json"
    delta = tmp_path / "parameter-delta.json"
    trial = tmp_path / "trial.json"

    for path in (
        relationship,
        delta,
        trial,
    ):
        path.write_text(
            "{}\n",
            encoding="utf-8",
        )

    promotion_path = tmp_path / "promotion.json"

    record = PromotionRecord(
        **{
            **valid_promotion_record().__dict__,
            "candidate_manifest_path": str(candidate),
            "relationship_path": str(relationship),
            "parameter_delta_path": str(delta),
            "physical_trial_path": str(trial),
            "export_validation_path": str(export_validation),
        }
    )

    first = register_candidate_promotion(
        record=record,
        output_path=promotion_path,
    )

    second = register_candidate_promotion(
        record=record,
        output_path=promotion_path,
    )

    assert first == second
    assert promotion_path.is_file()


def test_register_candidate_promotion_accepts_root_candidate_without_lineage(
    tmp_path: Path,
) -> None:
    """A root candidate has no parent, so it has no relationship or delta
    report. Eligibility must not demand evidence that cannot exist."""

    from zcad_core.retention import (
        register_candidate_promotion,
    )

    candidate, export_validation = write_verified_candidate(tmp_path, revision="r001")
    trial = tmp_path / "trial.json"
    trial.write_text("{}\n", encoding="utf-8")

    promotion_path = tmp_path / "promotion.json"

    record = PromotionRecord(
        **{
            **valid_promotion_record(revision="r001").__dict__,
            "candidate_manifest_path": str(candidate),
            "relationship_path": None,
            "parameter_delta_path": None,
            "physical_trial_path": str(trial),
            "export_validation_path": str(export_validation),
        }
    )

    result = register_candidate_promotion(
        record=record,
        output_path=promotion_path,
    )

    assert result.decision is PromotionDecision.PROMOTED
    assert promotion_path.is_file()

    payload = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert payload["relationship_path"] is None
    assert payload["parameter_delta_path"] is None


def test_register_candidate_promotion_rejects_missing_artifacts(
    tmp_path: Path,
) -> None:
    from zcad_core.retention import (
        register_candidate_promotion,
    )

    record = valid_promotion_record()
    promotion_path = tmp_path / "promotion.json"

    with pytest.raises(
        ValueError,
        match="candidate_manifest_missing",
    ):
        register_candidate_promotion(
            record=record,
            output_path=promotion_path,
        )

    assert not promotion_path.exists()


@pytest.mark.parametrize(
    "decision",
    [PromotionDecision.REJECTED, PromotionDecision.REQUIRES_REVISION],
)
def test_register_candidate_promotion_records_non_promoted_without_passing_evidence(
    tmp_path: Path,
    decision: PromotionDecision,
) -> None:
    """Failed and rejected trials remain visible: a non-promoted decision
    must be recordable even when validation did not pass."""

    from zcad_core.retention import (
        register_candidate_promotion,
    )

    candidate = tmp_path / "candidate.json"
    trial = tmp_path / "trial.json"

    for path in (candidate, trial):
        path.write_text("{}\n", encoding="utf-8")

    promotion_path = tmp_path / "promotion.json"

    record = PromotionRecord(
        **{
            **valid_promotion_record().__dict__,
            "decision": decision,
            "reason": "Physical trial failed fit check.",
            "automated_validation_passed": False,
            "physical_validation_passed": False,
            "candidate_manifest_path": str(candidate),
            "relationship_path": None,
            "parameter_delta_path": None,
            "physical_trial_path": str(trial),
        }
    )

    result = register_candidate_promotion(
        record=record,
        output_path=promotion_path,
    )

    assert result == record

    payload = json.loads(promotion_path.read_text(encoding="utf-8"))
    assert payload["decision"] == decision.value
    assert payload["automated_validation_passed"] is False
    assert payload["physical_validation_passed"] is False


@pytest.mark.parametrize(
    ("missing_name", "failure"),
    [
        ("candidate.json", "candidate_manifest_missing"),
        ("trial.json", "physical_trial_missing"),
    ],
)
def test_register_candidate_promotion_rejected_requires_cited_artifacts(
    tmp_path: Path,
    missing_name: str,
    failure: str,
) -> None:
    from zcad_core.retention import (
        register_candidate_promotion,
    )

    candidate = tmp_path / "candidate.json"
    trial = tmp_path / "trial.json"

    for path in (candidate, trial):
        if path.name != missing_name:
            path.write_text("{}\n", encoding="utf-8")

    promotion_path = tmp_path / "promotion.json"

    record = PromotionRecord(
        **{
            **valid_promotion_record().__dict__,
            "decision": PromotionDecision.REJECTED,
            "automated_validation_passed": False,
            "physical_validation_passed": False,
            "candidate_manifest_path": str(candidate),
            "relationship_path": None,
            "parameter_delta_path": None,
            "physical_trial_path": str(trial),
        }
    )

    with pytest.raises(ValueError, match=failure):
        register_candidate_promotion(
            record=record,
            output_path=promotion_path,
        )

    assert not promotion_path.exists()


def test_rejected_record_does_not_become_preferred(
    tmp_path: Path,
) -> None:
    record = PromotionRecord(
        **{
            **_write_promotion_artifacts(tmp_path, "r001").__dict__,
            "decision": PromotionDecision.REJECTED,
            "automated_validation_passed": False,
            "physical_validation_passed": False,
        }
    )

    promote_preferred_revision(
        record=record,
        output_path=tmp_path / "candidates" / "r001" / "promotion.json",
    )

    assert (
        select_preferred_revision(
            target_id=record.target_id,
            promotion_records=(record,),
        )
        is None
    )


def test_promote_preferred_revision_records_rejection_without_supersession(
    tmp_path: Path,
) -> None:
    preferred = _write_promotion_artifacts(tmp_path, "r001")
    rejected = PromotionRecord(
        **{
            **_write_promotion_artifacts(tmp_path, "r002").__dict__,
            "decision": PromotionDecision.REJECTED,
            "physical_validation_passed": False,
        }
    )
    rejection_path = tmp_path / "candidates" / "r002" / "promotion.json"

    result = promote_preferred_revision(
        record=rejected,
        output_path=rejection_path,
        existing_promotion_records=(preferred,),
    )

    assert result == rejected
    assert rejection_path.is_file()
    assert (
        select_preferred_revision(
            target_id=preferred.target_id,
            promotion_records=(preferred, rejected),
        )
        == preferred
    )


def test_select_preferred_revision_returns_none_without_promotions() -> None:
    result = select_preferred_revision(
        target_id="synthetic-target",
        promotion_records=(),
    )

    assert result is None


def test_select_preferred_revision_returns_sole_promoted_candidate() -> None:
    record = valid_promotion_record(revision="r001")

    result = select_preferred_revision(
        target_id="synthetic-target",
        promotion_records=(record,),
    )

    assert result == record


def test_select_preferred_revision_ignores_other_targets() -> None:
    record = PromotionRecord(
        **{
            **valid_promotion_record(revision="r001").__dict__,
            "target_id": "other-target",
        }
    )

    result = select_preferred_revision(
        target_id="synthetic-target",
        promotion_records=(record,),
    )

    assert result is None


def test_select_preferred_revision_excludes_superseded_candidate() -> None:
    superseded = valid_promotion_record(revision="r001")
    preferred = PromotionRecord(
        **{
            **valid_promotion_record(revision="r002").__dict__,
            "supersedes_candidate_id": superseded.candidate_id,
        }
    )

    result = select_preferred_revision(
        target_id="synthetic-target",
        promotion_records=(superseded, preferred),
    )

    assert result == preferred


def test_select_preferred_revision_rejects_ambiguous_promotions() -> None:
    first = valid_promotion_record(revision="r001")
    second = valid_promotion_record(revision="r002")

    with pytest.raises(
        ValueError,
        match="Ambiguous preferred revision",
    ):
        select_preferred_revision(
            target_id="synthetic-target",
            promotion_records=(first, second),
        )


def _write_promotion_artifacts(
    tmp_path: Path,
    revision: str,
) -> PromotionRecord:
    directory = tmp_path / "candidates" / revision
    directory.mkdir(parents=True)

    _, export_validation = write_verified_candidate(directory, revision=revision)

    for name in (
        "relationship.json",
        "parameter-delta.json",
    ):
        (directory / name).write_text("{}\n", encoding="utf-8")

    trial_directory = directory / "trials" / "trial-001"
    trial_directory.mkdir(parents=True)
    (trial_directory / "trial.json").write_text("{}\n", encoding="utf-8")

    return PromotionRecord(
        **{
            **valid_promotion_record(revision=revision).__dict__,
            "candidate_manifest_path": str(directory / "candidate.json"),
            "relationship_path": str(directory / "relationship.json"),
            "parameter_delta_path": str(directory / "parameter-delta.json"),
            "physical_trial_path": str(trial_directory / "trial.json"),
            "export_validation_path": str(export_validation),
        }
    )


def test_promote_preferred_revision_registers_first_promotion(
    tmp_path: Path,
) -> None:
    record = _write_promotion_artifacts(tmp_path, "r001")
    promotion_path = tmp_path / "candidates" / "r001" / "promotion.json"

    result = promote_preferred_revision(
        record=record,
        output_path=promotion_path,
    )

    assert result == record
    assert promotion_path.is_file()


def test_promote_preferred_revision_requires_supersession_for_new_preferred(
    tmp_path: Path,
) -> None:
    existing = _write_promotion_artifacts(tmp_path, "r001")
    existing_path = tmp_path / "candidates" / "r001" / "promotion.json"
    promote_preferred_revision(
        record=existing,
        output_path=existing_path,
    )

    incoming = _write_promotion_artifacts(tmp_path, "r002")
    incoming_path = tmp_path / "candidates" / "r002" / "promotion.json"

    with pytest.raises(
        ValueError,
        match="requires supersedes_candidate_id",
    ):
        promote_preferred_revision(
            record=incoming,
            output_path=incoming_path,
            existing_promotion_records=(existing,),
        )

    assert not incoming_path.exists()


def test_promote_preferred_revision_rejects_mismatched_supersession(
    tmp_path: Path,
) -> None:
    existing = _write_promotion_artifacts(tmp_path, "r001")
    existing_path = tmp_path / "candidates" / "r001" / "promotion.json"
    promote_preferred_revision(
        record=existing,
        output_path=existing_path,
    )

    incoming = PromotionRecord(
        **{
            **_write_promotion_artifacts(tmp_path, "r002").__dict__,
            "supersedes_candidate_id": "some-other-candidate",
        }
    )
    incoming_path = tmp_path / "candidates" / "r002" / "promotion.json"

    with pytest.raises(
        ValueError,
        match="requires supersedes_candidate_id",
    ):
        promote_preferred_revision(
            record=incoming,
            output_path=incoming_path,
            existing_promotion_records=(existing,),
        )

    assert not incoming_path.exists()


def test_promote_preferred_revision_supersedes_prior_preferred_candidate(
    tmp_path: Path,
) -> None:
    existing = _write_promotion_artifacts(tmp_path, "r001")
    existing_path = tmp_path / "candidates" / "r001" / "promotion.json"
    promote_preferred_revision(
        record=existing,
        output_path=existing_path,
    )

    incoming = PromotionRecord(
        **{
            **_write_promotion_artifacts(tmp_path, "r002").__dict__,
            "supersedes_candidate_id": existing.candidate_id,
        }
    )
    incoming_path = tmp_path / "candidates" / "r002" / "promotion.json"

    result = promote_preferred_revision(
        record=incoming,
        output_path=incoming_path,
        existing_promotion_records=(existing,),
    )

    assert result == incoming
    assert incoming_path.is_file()

    preferred = select_preferred_revision(
        target_id="synthetic-target",
        promotion_records=(existing, incoming),
    )

    assert preferred == incoming

    # The prior promotion decision remains intact and unmodified.
    original_payload = json.loads(existing_path.read_text(encoding="utf-8"))
    assert original_payload["decision"] == "promoted"
    assert original_payload["candidate_id"] == existing.candidate_id


def test_promote_preferred_revision_rejects_three_generation_relationship_confusion(
    tmp_path: Path,
) -> None:
    """Regression test: derive-time lineage must not imply promotion supersession.

    r001 -> r002 -> r003 are all linked by derive-time ``supersedes``
    relationships regardless of promotion. If r002 is the preferred
    candidate, promoting r003 without an explicit
    ``supersedes_candidate_id=r002`` must still fail closed even though a
    RevisionRelationship already says "r003 supersedes r002" for lineage.
    """

    r001 = _write_promotion_artifacts(tmp_path, "r001")
    r002 = PromotionRecord(
        **{
            **_write_promotion_artifacts(tmp_path, "r002").__dict__,
            "supersedes_candidate_id": r001.candidate_id,
        }
    )
    promote_preferred_revision(
        record=r002,
        output_path=(tmp_path / "candidates" / "r002" / "promotion.json"),
        existing_promotion_records=(r001,),
    )

    r003 = _write_promotion_artifacts(tmp_path, "r003")
    r003_path = tmp_path / "candidates" / "r003" / "promotion.json"

    with pytest.raises(
        ValueError,
        match="requires supersedes_candidate_id",
    ):
        promote_preferred_revision(
            record=r003,
            output_path=r003_path,
            existing_promotion_records=(r001, r002),
        )

    assert not r003_path.exists()


def test_build_publication_record_approves_eligible_promoted_candidate() -> None:
    record = valid_promotion_record(revision="r002")
    eligibility = PublicationEligibility(
        eligible=True,
        failures=(),
    )

    result = build_publication_record(
        part_record={"design": {"name": "feather-rp2040"}},
        promotion_record=record,
        eligibility=eligibility,
    )

    assert result["design"] == {"name": "feather-rp2040"}
    assert result["publication"]["approved"] is True
    assert result["publication"]["candidate_id"] == record.candidate_id


def test_build_publication_record_rejects_non_promoted_decision() -> None:
    record = PromotionRecord(
        **{
            **valid_promotion_record(revision="r002").__dict__,
            "decision": PromotionDecision.REJECTED,
            "automated_validation_passed": False,
            "physical_validation_passed": False,
        }
    )
    eligibility = PublicationEligibility(
        eligible=False,
        failures=("automated_validation_not_passed",),
    )

    with pytest.raises(
        ValueError,
        match="requires an explicit PROMOTED decision",
    ):
        build_publication_record(
            part_record={},
            promotion_record=record,
            eligibility=eligibility,
        )


def test_build_publication_record_rejects_incomplete_evidence() -> None:
    record = valid_promotion_record(revision="r002")
    eligibility = PublicationEligibility(
        eligible=False,
        failures=("physical_trial_missing",),
    )

    with pytest.raises(
        ValueError,
        match="blocked by evidence gaps",
    ):
        build_publication_record(
            part_record={},
            promotion_record=record,
            eligibility=eligibility,
        )


def test_register_candidate_promotion_requires_export_validation(
    tmp_path: Path,
) -> None:
    record = _write_promotion_artifacts(tmp_path, "r001")
    record = PromotionRecord(**{**record.__dict__, "export_validation_path": None})

    with pytest.raises(ValueError, match="export_validation_missing"):
        promote_preferred_revision(
            record=record,
            output_path=tmp_path / "promotion.json",
        )

    assert not (tmp_path / "promotion.json").exists()


def test_register_candidate_promotion_rejects_changed_retention_step(
    tmp_path: Path,
) -> None:
    record = _write_promotion_artifacts(tmp_path, "r001")
    (tmp_path / "candidates/r001/retention.step").write_bytes(b"edited later")

    with pytest.raises(
        ValueError,
        match="export_validation_source_changed:retention",
    ):
        promote_preferred_revision(
            record=record,
            output_path=tmp_path / "promotion.json",
        )


def test_register_candidate_promotion_rejects_other_candidates_evidence(
    tmp_path: Path,
) -> None:
    record = _write_promotion_artifacts(tmp_path, "r001")
    _, other_export = write_verified_candidate(tmp_path / "other", revision="r002")
    record = PromotionRecord(
        **{**record.__dict__, "export_validation_path": str(other_export)}
    )

    with pytest.raises(ValueError, match="export_validation_candidate_mismatch"):
        promote_preferred_revision(
            record=record,
            output_path=tmp_path / "promotion.json",
        )


def test_register_candidate_promotion_rejects_unverifiable_evidence(
    tmp_path: Path,
) -> None:
    record = _write_promotion_artifacts(tmp_path, "r001")
    Path(record.candidate_manifest_path).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="export_validation_unverifiable"):
        promote_preferred_revision(
            record=record,
            output_path=tmp_path / "promotion.json",
        )

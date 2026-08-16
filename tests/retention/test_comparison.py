from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.retention import (
    CandidateRevision,
    PhysicalTrialManifest,
    RecommendationDecision,
    compare_automated_gates,
    compare_candidate_revisions,
    compare_trial_outcomes,
    recommend_revision,
    write_revision_comparison_report,
    write_revision_recommendation,
)

SHA256_A = "a" * 64
SHA256_B = "b" * 64


def candidate(
    *,
    revision: str,
    automated_decision: str = "verified_candidate",
    vertical_overlap_mm: float = 0.6,
) -> CandidateRevision:
    return CandidateRevision(
        schema_version="1.0.0",
        candidate_id=(f"adafruit-feather-rp2040-corner-capture-{revision}"),
        target_id="adafruit-feather-rp2040",
        revision=revision,
        source_sha256=SHA256_A,
        output_sha256=SHA256_B,
        git_commit="abc123",
        generator_version="1.0.0",
        retention_policy={
            "arm_width_mm": 3.0,
            "board_clearance_mm": 0.25,
        },
        derived_parameters={
            "board_thickness_mm": 1.6,
            "vertical_overlap_mm": vertical_overlap_mm,
        },
        selected_corners=(
            "negative_x_negative_y",
            "positive_x_positive_y",
        ),
        automated_decision=automated_decision,
        automated_evidence_path="automated-validation.json",
        fixture_artifact_path="fixture.stl",
        created_at_utc="2026-07-27T00:00:00+00:00",
    )


def trial(
    *,
    candidate_id: str,
    complete: bool = True,
    passed: bool = True,
) -> PhysicalTrialManifest:
    return PhysicalTrialManifest(
        schema_version="1.0.0",
        trial_id="trial-001",
        candidate_id=candidate_id,
        physical_validation_path="physical-validation.json",
        fixture_artifact_path="fixture.stl",
        printer_profile="bambu-lab-a1-mini",
        material_profile="petg",
        slicer_profile="bambu-studio-a1-mini-petg-validation",
        disposition=("pass" if passed else "revise"),
        complete=complete,
        passed=passed,
        created_at_utc="2026-07-27T00:00:00+00:00",
    )


def test_compare_automated_gates_reports_verification_state() -> None:
    result = compare_automated_gates(
        source=candidate(revision="r001", automated_decision="rejected"),
        target=candidate(revision="r002", automated_decision="verified_candidate"),
    )

    assert result.source_verified is False
    assert result.target_verified is True
    assert result.agreement is False


def test_compare_trial_outcomes_rejects_mismatched_candidate() -> None:
    with pytest.raises(
        ValueError,
        match="does not reference source_candidate_id",
    ):
        compare_trial_outcomes(
            source_candidate_id="adafruit-feather-rp2040-corner-capture-r001",
            target_candidate_id="adafruit-feather-rp2040-corner-capture-r002",
            source_trial=trial(
                candidate_id="adafruit-feather-rp2040-corner-capture-r099"
            ),
            target_trial=None,
        )


def test_compare_candidate_revisions_rejects_self_comparison() -> None:
    source = candidate(revision="r001")

    with pytest.raises(
        ValueError,
        match="Cannot compare a candidate revision against itself",
    ):
        compare_candidate_revisions(
            source=source,
            target=source,
        )


def test_compare_candidate_revisions_rejects_different_targets() -> None:
    source = candidate(revision="r001")
    target = CandidateRevision(
        **{
            **candidate(revision="r002").__dict__,
            "target_id": "raspberry-pi-pico-2",
            "candidate_id": "raspberry-pi-pico-2-corner-capture-r002",
        }
    )

    with pytest.raises(
        ValueError,
        match="must reference the same validation target",
    ):
        compare_candidate_revisions(
            source=source,
            target=target,
        )


def test_compare_candidate_revisions_reports_parameter_deltas() -> None:
    source = candidate(revision="r001", vertical_overlap_mm=0.4)
    target = candidate(revision="r002", vertical_overlap_mm=0.6)

    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(candidate_id=source.candidate_id),
        target_trial=trial(candidate_id=target.candidate_id),
    )

    assert report.target_id == "adafruit-feather-rp2040"
    assert report.parameters.changed is True
    assert tuple(change.parameter for change in report.parameters.changes) == (
        "vertical_overlap_mm",
    )
    assert report.trials.evidence_complete is True


def test_recommend_revision_flags_missing_physical_trial() -> None:
    source = candidate(revision="r001")
    target = candidate(revision="r002")

    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=None,
        target_trial=trial(candidate_id=target.candidate_id),
    )

    recommendation = recommend_revision(report)

    assert recommendation.decision is RecommendationDecision.INSUFFICIENT_EVIDENCE
    assert recommendation.missing_evidence == (
        f"{source.candidate_id} has no complete physical trial",
    )
    assert recommendation.measured_facts == ()


def test_recommend_revision_prefers_the_only_fully_passing_candidate() -> None:
    source = candidate(revision="r001", automated_decision="rejected")
    target = candidate(revision="r002", automated_decision="verified_candidate")

    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(
            candidate_id=source.candidate_id,
            passed=False,
        ),
        target_trial=trial(
            candidate_id=target.candidate_id,
            passed=True,
        ),
    )

    recommendation = recommend_revision(report)

    assert recommendation.decision is RecommendationDecision.PREFER_TARGET
    assert target.candidate_id in recommendation.rationale
    assert len(recommendation.measured_facts) == 4


def test_recommend_revision_defers_policy_when_both_candidates_pass() -> None:
    source = candidate(revision="r001")
    target = candidate(revision="r002")

    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(candidate_id=source.candidate_id),
        target_trial=trial(candidate_id=target.candidate_id),
    )

    recommendation = recommend_revision(report)

    assert recommendation.decision is RecommendationDecision.NO_PREFERENCE
    assert "policy judgment" in recommendation.rationale


def test_recommendation_requires_missing_evidence_only_when_insufficient() -> None:
    with pytest.raises(
        ValueError,
        match="Only an insufficient-evidence recommendation",
    ):
        from zcad_core.retention import RevisionRecommendation

        RevisionRecommendation(
            schema_version="1.0.0",
            source_candidate_id="a",
            target_candidate_id="b",
            decision=RecommendationDecision.PREFER_SOURCE,
            rationale="a passed; b did not.",
            measured_facts=(),
            missing_evidence=("unexpected",),
        )


def test_write_revision_comparison_report_is_idempotent(
    tmp_path: Path,
) -> None:
    source = candidate(revision="r001", vertical_overlap_mm=0.4)
    target = candidate(revision="r002", vertical_overlap_mm=0.6)
    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(candidate_id=source.candidate_id),
        target_trial=trial(candidate_id=target.candidate_id),
    )
    output_path = tmp_path / "comparison.json"

    write_revision_comparison_report(
        report,
        output_path=output_path,
    )
    write_revision_comparison_report(
        report,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["parameters"]["changed"] is True
    assert payload["trials"]["evidence_complete"] is True


def test_write_revision_comparison_report_rejects_conflict(
    tmp_path: Path,
) -> None:
    source = candidate(revision="r001")
    target = candidate(revision="r002")
    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(candidate_id=source.candidate_id),
        target_trial=trial(candidate_id=target.candidate_id),
    )
    output_path = tmp_path / "comparison.json"

    write_revision_comparison_report(
        report,
        output_path=output_path,
    )

    changed = replace(
        report,
        target_id="different-target",
    )

    with pytest.raises(
        FileExistsError,
        match="immutable comparison report",
    ):
        write_revision_comparison_report(
            changed,
            output_path=output_path,
        )


def test_write_revision_recommendation_is_idempotent(
    tmp_path: Path,
) -> None:
    source = candidate(revision="r001", automated_decision="rejected")
    target = candidate(revision="r002")
    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=trial(candidate_id=source.candidate_id, passed=False),
        target_trial=trial(candidate_id=target.candidate_id),
    )
    recommendation = recommend_revision(report)
    output_path = tmp_path / "recommendation.json"

    write_revision_recommendation(
        recommendation,
        output_path=output_path,
    )
    write_revision_recommendation(
        recommendation,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["decision"] == "prefer_target"

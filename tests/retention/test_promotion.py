from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.retention import (
    PromotionDecision,
    PromotionRecord,
    PublicationEligibility,
    evaluate_publication_eligibility,
    write_promotion_record,
)


def valid_promotion_record() -> PromotionRecord:
    return PromotionRecord(
        schema_version="1.0.0",
        target_id="synthetic-target",
        candidate_id=("synthetic-target-corner-capture-r002"),
        decision=PromotionDecision.PROMOTED,
        reason=("Automated and physical validation passed."),
        reviewer="operator",
        automated_validation_passed=True,
        physical_validation_passed=True,
        candidate_manifest_path=("candidates/r002/candidate.json"),
        relationship_path=("candidates/r002/relationship.json"),
        parameter_delta_path=("candidates/r002/parameter-delta.json"),
        physical_trial_path=("candidates/r002/trials/trial-001/trial.json"),
        created_at_utc=("2026-01-01T00:00:00+00:00"),
    )


def test_publication_eligibility_passes() -> None:
    result = evaluate_publication_eligibility(
        automated_validation_passed=True,
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
        physical_validation_passed=False,
        candidate_manifest_exists=True,
        relationship_exists=False,
        parameter_delta_exists=True,
        physical_trial_exists=False,
    )

    assert result.eligible is False
    assert result.failures == (
        "automated_validation_not_passed",
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

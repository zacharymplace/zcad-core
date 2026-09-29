from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.retention import (
    VisualReviewCheck,
    VisualReviewDisposition,
    VisualReviewObservation,
    VisualReviewRecord,
    complete_visual_review_record,
    load_visual_review_record,
    write_visual_review_record,
)

FEATHER_R003_REVIEW = Path(
    "evidence/adafruit-feather-rp2040/validation-lab/candidates/r003/visual-review.json"
)


def observations(
    *,
    passed: bool = True,
):
    return tuple(
        VisualReviewObservation(
            check=check,
            passed=passed,
            notes="Reviewed.",
        )
        for check in VisualReviewCheck
    )


def test_conditional_visual_review_passes() -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=observations(),
        disposition=(VisualReviewDisposition.PASS_WITH_RESERVATIONS),
        reviewer_notes=("Physical validation remains required."),
    )

    assert record.complete is True
    assert record.passed is True
    assert record.conditional is True


def test_pass_refuses_a_skipped_check() -> None:
    skipped = tuple(
        observation
        for observation in observations()
        if observation.check is not VisualReviewCheck.RETENTION_FEATURES_FUSED
    )

    with pytest.raises(ValueError, match="missing: \\['retention_features_fused'\\]"):
        complete_visual_review_record(
            candidate_id="candidate-r001",
            design_review_path=Path("design-review.json"),
            installation_path_report_path=Path("installation-path.json"),
            reviewer="reviewer",
            observations=skipped,
            disposition=VisualReviewDisposition.PASS,
            reviewer_notes="Incomplete.",
        )


def test_incomplete_visual_review_fails() -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=observations()[:-1],
        disposition=VisualReviewDisposition.REVISE,
        reviewer_notes="Incomplete.",
    )

    assert record.schema_version == "1.1.0"
    assert record.complete is False
    assert record.passed is False


def floating_ledge_observations() -> tuple[VisualReviewObservation, ...]:
    return tuple(
        VisualReviewObservation(
            check=check,
            passed=(check is not VisualReviewCheck.RETENTION_FEATURES_FUSED),
            notes="Ledges float clear of the base.",
        )
        for check in VisualReviewCheck
    )


@pytest.mark.parametrize(
    "disposition",
    [
        VisualReviewDisposition.PASS,
        VisualReviewDisposition.PASS_WITH_RESERVATIONS,
    ],
)
def test_failed_observation_refuses_passing_disposition(
    disposition: VisualReviewDisposition,
) -> None:
    with pytest.raises(ValueError, match="failed: \\['retention_features_fused'\\]"):
        complete_visual_review_record(
            candidate_id="candidate-r001",
            design_review_path=Path("design-review.json"),
            installation_path_report_path=Path("installation-path.json"),
            reviewer="reviewer",
            observations=floating_ledge_observations(),
            disposition=disposition,
            reviewer_notes="Floating ledges.",
        )


def test_failed_observation_records_a_revise() -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=floating_ledge_observations(),
        disposition=VisualReviewDisposition.REVISE,
        reviewer_notes="Fuse the ledges to the base.",
    )

    assert record.complete is True
    assert record.passed is False


def test_record_constructed_directly_still_judges_its_observations() -> None:
    """Records loaded from disk bypass the completion guard, so the derived
    properties must reject a pass their observations deny."""

    record = VisualReviewRecord(
        schema_version="1.1.0",
        candidate_id="candidate-r001",
        design_review_path="design-review.json",
        installation_path_report_path="installation-path.json",
        reviewer="reviewer",
        observations=floating_ledge_observations(),
        disposition=VisualReviewDisposition.PASS,
        reviewer_notes="Edited by hand.",
        completed_at_utc="2026-01-01T00:00:00+00:00",
    )

    assert record.passed is False


def test_legacy_schema_is_judged_by_its_own_checklist() -> None:
    legacy = tuple(
        observation
        for observation in observations()
        if observation.check is not VisualReviewCheck.RETENTION_FEATURES_FUSED
    )

    record = VisualReviewRecord(
        schema_version="1.0.0",
        candidate_id="candidate-r001",
        design_review_path="design-review.json",
        installation_path_report_path="installation-path.json",
        reviewer="reviewer",
        observations=legacy,
        disposition=VisualReviewDisposition.PASS,
        reviewer_notes="Legacy.",
        completed_at_utc="2026-01-01T00:00:00+00:00",
    )

    assert record.complete is True
    assert record.passed is True


def test_unsupported_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported visual review schema"):
        VisualReviewRecord(
            schema_version="2.0.0",
            candidate_id="candidate-r001",
            design_review_path="design-review.json",
            installation_path_report_path="installation-path.json",
            reviewer="reviewer",
            observations=observations(),
            disposition=VisualReviewDisposition.PASS,
            reviewer_notes="Future.",
            completed_at_utc="2026-01-01T00:00:00+00:00",
        )


def test_load_round_trips_a_written_record(tmp_path: Path) -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=observations(),
        disposition=VisualReviewDisposition.PASS_WITH_RESERVATIONS,
        reviewer_notes="Conditional pass.",
    )
    path = tmp_path / "visual-review.json"
    write_visual_review_record(record, output_path=path)

    assert load_visual_review_record(path) == record


@pytest.mark.skipif(
    not FEATHER_R003_REVIEW.is_file(),
    reason="Feather RP2040 r003 visual review is not available locally",
)
def test_loads_the_legacy_feather_r003_review() -> None:
    before = FEATHER_R003_REVIEW.read_bytes()
    record = load_visual_review_record(FEATHER_R003_REVIEW)

    assert record.schema_version == "1.0.0"
    assert record.complete is True
    assert record.passed is True
    # Loading reinterprets; it never rewrites evidence on disk.
    assert FEATHER_R003_REVIEW.read_bytes() == before


def test_writes_immutable_visual_record(
    tmp_path: Path,
) -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=observations(),
        disposition=(VisualReviewDisposition.PASS_WITH_RESERVATIONS),
        reviewer_notes="Conditional pass.",
    )
    output_path = tmp_path / "visual-review.json"

    write_visual_review_record(
        record,
        output_path=output_path,
    )
    write_visual_review_record(
        record,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["passed"] is True
    assert payload["conditional"] is True
    assert payload["physical_validation_satisfied"] is False

    output_path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        write_visual_review_record(
            record,
            output_path=output_path,
        )

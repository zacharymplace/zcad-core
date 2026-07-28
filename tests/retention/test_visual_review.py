from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.retention import (
    VisualReviewCheck,
    VisualReviewDisposition,
    VisualReviewObservation,
    complete_visual_review_record,
    write_visual_review_record,
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


def test_incomplete_visual_review_fails() -> None:
    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=observations()[:-1],
        disposition=VisualReviewDisposition.PASS,
        reviewer_notes="Incomplete.",
    )

    assert record.complete is False
    assert record.passed is False


def test_failed_observation_blocks_pass() -> None:
    values = tuple(
        VisualReviewObservation(
            check=check,
            passed=(check is not (VisualReviewCheck.CONNECTORS_ACCESSIBLE)),
            notes="Reviewed.",
        )
        for check in VisualReviewCheck
    )

    record = complete_visual_review_record(
        candidate_id="candidate-r001",
        design_review_path=Path("design-review.json"),
        installation_path_report_path=Path("installation-path.json"),
        reviewer="reviewer",
        observations=values,
        disposition=VisualReviewDisposition.PASS,
        reviewer_notes="Connector blocked.",
    )

    assert record.passed is False


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

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class VisualReviewCheck(str, Enum):
    """Required design-review observations."""

    REVIEW_ARTIFACTS_OPEN = "review_artifacts_open"
    COLOR_SEPARATION_CLEAR = "color_separation_clear"
    BOARD_ALIGNMENT_PLAUSIBLE = "board_alignment_plausible"
    CAPTURES_COMPONENT_CLEAR = "captures_component_clear"
    CONNECTORS_ACCESSIBLE = "connectors_accessible"
    INSTALLATION_LIMITATIONS_RECORDED = "installation_limitations_recorded"
    UNDERSIDE_ASSUMPTIONS_RECORDED = "underside_assumptions_recorded"


class VisualReviewDisposition(str, Enum):
    """Human visual-review disposition."""

    PASS = "pass"
    PASS_WITH_RESERVATIONS = "pass_with_reservations"
    REVISE = "revise"
    REJECT = "reject"


@dataclass(frozen=True)
class VisualReviewObservation:
    """One structured visual observation."""

    check: VisualReviewCheck
    passed: bool
    notes: str = ""


@dataclass(frozen=True)
class VisualReviewRecord:
    """Human review of generated design evidence."""

    schema_version: str
    candidate_id: str
    design_review_path: str
    installation_path_report_path: str
    reviewer: str
    observations: tuple[
        VisualReviewObservation,
        ...,
    ]
    disposition: VisualReviewDisposition
    reviewer_notes: str
    completed_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported visual review schema")

        for name, value in (
            ("candidate_id", self.candidate_id),
            (
                "design_review_path",
                self.design_review_path,
            ),
            (
                "installation_path_report_path",
                self.installation_path_report_path,
            ),
            ("reviewer", self.reviewer),
            (
                "completed_at_utc",
                self.completed_at_utc,
            ),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")

    @property
    def complete(self) -> bool:
        """Whether every required check appears once."""

        observed = {observation.check for observation in self.observations}

        return observed == set(VisualReviewCheck) and len(observed) == len(
            self.observations
        )

    @property
    def passed(self) -> bool:
        """Whether the review accepts visual evidence."""

        return (
            self.complete
            and all(observation.passed for observation in self.observations)
            and self.disposition
            in {
                VisualReviewDisposition.PASS,
                (VisualReviewDisposition.PASS_WITH_RESERVATIONS),
            }
        )

    @property
    def conditional(self) -> bool:
        """Whether acceptance contains reservations."""

        return self.disposition is (VisualReviewDisposition.PASS_WITH_RESERVATIONS)


def complete_visual_review_record(
    *,
    candidate_id: str,
    design_review_path: Path,
    installation_path_report_path: Path,
    reviewer: str,
    observations: tuple[
        VisualReviewObservation,
        ...,
    ],
    disposition: VisualReviewDisposition,
    reviewer_notes: str,
) -> VisualReviewRecord:
    """Create a completed visual-review record."""

    return VisualReviewRecord(
        schema_version="1.0.0",
        candidate_id=candidate_id,
        design_review_path=str(design_review_path),
        installation_path_report_path=str(installation_path_report_path),
        reviewer=reviewer.strip(),
        observations=observations,
        disposition=disposition,
        reviewer_notes=reviewer_notes.strip(),
        completed_at_utc=(datetime.now(UTC).isoformat()),
    )


def write_visual_review_record(
    record: VisualReviewRecord,
    *,
    output_path: Path,
) -> None:
    """Write an immutable visual-review record."""

    payload = asdict(record)
    payload["complete"] = record.complete
    payload["passed"] = record.passed
    payload["conditional"] = record.conditional
    payload["physical_validation_satisfied"] = False
    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")

        if existing == serialized:
            return

        raise FileExistsError(
            f"Refusing to overwrite immutable visual-review record: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )

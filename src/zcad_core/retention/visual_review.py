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
    RETENTION_FEATURES_FUSED = "retention_features_fused"


VISUAL_REVIEW_SCHEMA_VERSION = "1.1.0"

# Schema 1.0.0 predates the fused-feature check: the review of Feather r003
# passed ledges that floated clear of the base. Legacy records still load and
# are judged against the checks that existed when they were written, but only
# current-schema reviews can support a promotion.
REQUIRED_VISUAL_REVIEW_CHECKS: dict[str, frozenset[VisualReviewCheck]] = {
    "1.0.0": frozenset(VisualReviewCheck)
    - {VisualReviewCheck.RETENTION_FEATURES_FUSED},
    VISUAL_REVIEW_SCHEMA_VERSION: frozenset(VisualReviewCheck),
}


class VisualReviewDisposition(str, Enum):
    """Human visual-review disposition."""

    PASS = "pass"
    PASS_WITH_RESERVATIONS = "pass_with_reservations"
    REVISE = "revise"
    REJECT = "reject"


_PASSING_DISPOSITIONS = frozenset(
    {
        VisualReviewDisposition.PASS,
        VisualReviewDisposition.PASS_WITH_RESERVATIONS,
    }
)


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
        if self.schema_version not in REQUIRED_VISUAL_REVIEW_CHECKS:
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
        """Whether every check required by the record's schema appears once."""

        observed = {observation.check for observation in self.observations}

        return observed == REQUIRED_VISUAL_REVIEW_CHECKS[self.schema_version] and len(
            observed
        ) == len(self.observations)

    @property
    def passed(self) -> bool:
        """Whether the review accepts visual evidence."""

        return (
            self.complete
            and all(observation.passed for observation in self.observations)
            and self.disposition in _PASSING_DISPOSITIONS
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
    """Create a completed visual-review record.

    A passing disposition is refused unless every required check is observed
    once and passed, so a record cannot claim a pass its observations deny.
    """

    if disposition in _PASSING_DISPOSITIONS:
        observed = [observation.check for observation in observations]
        missing = sorted(
            check.value for check in VisualReviewCheck if check not in observed
        )
        failed = [
            observation.check.value
            for observation in observations
            if not observation.passed
        ]

        if missing or failed or len(observed) != len(set(observed)):
            raise ValueError(
                f"A {disposition.value} disposition requires every check to pass "
                f"once; missing: {missing or 'none'}, failed: {failed or 'none'}"
            )

    return VisualReviewRecord(
        schema_version=VISUAL_REVIEW_SCHEMA_VERSION,
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


def load_visual_review_record(path: Path) -> VisualReviewRecord:
    """Load a visual-review record written by :func:`write_visual_review_record`.

    Derived fields (``complete``, ``passed``, ``conditional``) are recomputed
    from the observations rather than trusted from the file.
    """

    if not path.is_file():
        raise FileNotFoundError(path)

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError("Visual review record root must be an object")

    return VisualReviewRecord(
        schema_version=str(payload["schema_version"]),
        candidate_id=str(payload["candidate_id"]),
        design_review_path=str(payload["design_review_path"]),
        installation_path_report_path=str(payload["installation_path_report_path"]),
        reviewer=str(payload["reviewer"]),
        observations=tuple(
            VisualReviewObservation(
                check=VisualReviewCheck(observation["check"]),
                passed=bool(observation["passed"]),
                notes=str(observation.get("notes", "")),
            )
            for observation in payload["observations"]
        ),
        disposition=VisualReviewDisposition(payload["disposition"]),
        reviewer_notes=str(payload["reviewer_notes"]),
        completed_at_utc=str(payload["completed_at_utc"]),
    )

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .revision_history import RevisionDeltaReport, compare_candidate_parameters
from .validation_lab import CandidateRevision, PhysicalTrialManifest

_VERIFIED_DECISION = "verified_candidate"


@dataclass(frozen=True)
class AutomatedGateComparison:
    """Automated-decision comparison between two candidate revisions."""

    source_candidate_id: str
    target_candidate_id: str
    source_verified: bool
    target_verified: bool

    @property
    def agreement(self) -> bool:
        """Whether both candidates reached the same automated decision."""

        return self.source_verified == self.target_verified


@dataclass(frozen=True)
class TrialOutcomeComparison:
    """Physical-trial outcome comparison between two candidate revisions."""

    source_candidate_id: str
    target_candidate_id: str
    source_trial: PhysicalTrialManifest | None
    target_trial: PhysicalTrialManifest | None

    @property
    def source_passed(self) -> bool:
        return self.source_trial is not None and self.source_trial.passed

    @property
    def target_passed(self) -> bool:
        return self.target_trial is not None and self.target_trial.passed

    @property
    def source_pending(self) -> bool:
        return self.source_trial is not None and self.source_trial.pending

    @property
    def target_pending(self) -> bool:
        return self.target_trial is not None and self.target_trial.pending

    @property
    def evidence_complete(self) -> bool:
        """Whether both candidates have a complete physical trial record."""

        return (
            self.source_trial is not None
            and self.source_trial.complete
            and self.target_trial is not None
            and self.target_trial.complete
        )


@dataclass(frozen=True)
class RevisionComparisonReport:
    """Deterministic evidence comparison between two candidate revisions."""

    schema_version: str
    target_id: str
    source_candidate_id: str
    target_candidate_id: str
    automated: AutomatedGateComparison
    trials: TrialOutcomeComparison
    parameters: RevisionDeltaReport


def compare_automated_gates(
    *,
    source: CandidateRevision,
    target: CandidateRevision,
) -> AutomatedGateComparison:
    """Compare the automated verification decision of two candidates."""

    return AutomatedGateComparison(
        source_candidate_id=source.candidate_id,
        target_candidate_id=target.candidate_id,
        source_verified=(source.automated_decision == _VERIFIED_DECISION),
        target_verified=(target.automated_decision == _VERIFIED_DECISION),
    )


def compare_trial_outcomes(
    *,
    source_candidate_id: str,
    target_candidate_id: str,
    source_trial: PhysicalTrialManifest | None,
    target_trial: PhysicalTrialManifest | None,
) -> TrialOutcomeComparison:
    """Compare the physical-trial outcome backing two candidates.

    Each candidate may accumulate multiple physical trials; callers select
    the trial considered authoritative for comparison rather than this
    function scanning trial history itself.
    """

    if source_trial is not None and source_trial.candidate_id != source_candidate_id:
        raise ValueError("source_trial does not reference source_candidate_id")

    if target_trial is not None and target_trial.candidate_id != target_candidate_id:
        raise ValueError("target_trial does not reference target_candidate_id")

    return TrialOutcomeComparison(
        source_candidate_id=source_candidate_id,
        target_candidate_id=target_candidate_id,
        source_trial=source_trial,
        target_trial=target_trial,
    )


def compare_candidate_revisions(
    *,
    source: CandidateRevision,
    target: CandidateRevision,
    source_trial: PhysicalTrialManifest | None = None,
    target_trial: PhysicalTrialManifest | None = None,
) -> RevisionComparisonReport:
    """Build a deterministic, evidence-backed comparison of two revisions.

    Dimensional comparison reuses the derived-parameter deltas established
    in :func:`compare_candidate_parameters`; ``derived_parameters`` already
    carries the CAD-derived dimensions (arm width, clearance, overlap, and
    similar) that distinguish one candidate revision from another.
    """

    if source.candidate_id == target.candidate_id:
        raise ValueError("Cannot compare a candidate revision against itself")

    if source.target_id != target.target_id:
        raise ValueError(
            "Candidate revisions must reference the same validation target"
        )

    return RevisionComparisonReport(
        schema_version="1.0.0",
        target_id=source.target_id,
        source_candidate_id=source.candidate_id,
        target_candidate_id=target.candidate_id,
        automated=compare_automated_gates(
            source=source,
            target=target,
        ),
        trials=compare_trial_outcomes(
            source_candidate_id=source.candidate_id,
            target_candidate_id=target.candidate_id,
            source_trial=source_trial,
            target_trial=target_trial,
        ),
        parameters=compare_candidate_parameters(
            source_candidate_id=source.candidate_id,
            target_candidate_id=target.candidate_id,
            source_parameters={
                key: float(value) for key, value in source.derived_parameters.items()
            },
            target_parameters={
                key: float(value) for key, value in target.derived_parameters.items()
            },
        ),
    )


class RecommendationDecision(str, Enum):
    """Explicit outcome of a revision recommendation."""

    PREFER_SOURCE = "prefer_source"
    PREFER_TARGET = "prefer_target"
    NO_PREFERENCE = "no_preference"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class RevisionRecommendation:
    """An explicit, evidence-derived preference between two revisions."""

    schema_version: str
    source_candidate_id: str
    target_candidate_id: str
    decision: RecommendationDecision
    rationale: str
    measured_facts: tuple[str, ...]
    missing_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported revision recommendation schema")

        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")

        if (
            self.decision is RecommendationDecision.INSUFFICIENT_EVIDENCE
            and not self.missing_evidence
        ):
            raise ValueError(
                "Insufficient-evidence recommendation must list missing evidence"
            )

        if (
            self.decision is not RecommendationDecision.INSUFFICIENT_EVIDENCE
            and self.missing_evidence
        ):
            raise ValueError(
                "Only an insufficient-evidence recommendation may list missing evidence"
            )


def recommend_revision(
    comparison: RevisionComparisonReport,
) -> RevisionRecommendation:
    """Derive a fail-closed recommendation from a deterministic comparison.

    A recommendation names a preferred candidate only when the measured
    evidence supports it: both candidates require a complete physical trial,
    and only a candidate that passed both the automated gates and its
    physical trial can be preferred over one that did not. When both
    candidates reach the same measured outcome, choosing between them is a
    policy judgment this function does not make.
    """

    missing_evidence = [
        message
        for message in (
            _missing_trial_evidence(
                comparison.source_candidate_id,
                comparison.trials.source_trial,
            ),
            _missing_trial_evidence(
                comparison.target_candidate_id,
                comparison.trials.target_trial,
            ),
        )
        if message is not None
    ]

    if missing_evidence:
        return RevisionRecommendation(
            schema_version="1.0.0",
            source_candidate_id=comparison.source_candidate_id,
            target_candidate_id=comparison.target_candidate_id,
            decision=RecommendationDecision.INSUFFICIENT_EVIDENCE,
            rationale=(
                "A recommendation requires a complete physical trial "
                "for both candidates."
            ),
            measured_facts=(),
            missing_evidence=tuple(missing_evidence),
        )

    source_verified_and_passed = (
        comparison.automated.source_verified and comparison.trials.source_passed
    )
    target_verified_and_passed = (
        comparison.automated.target_verified and comparison.trials.target_passed
    )

    measured_facts = (
        (
            f"{comparison.source_candidate_id} automated_verified="
            f"{comparison.automated.source_verified}"
        ),
        (
            f"{comparison.source_candidate_id} physical_trial_passed="
            f"{comparison.trials.source_passed}"
        ),
        (
            f"{comparison.target_candidate_id} automated_verified="
            f"{comparison.automated.target_verified}"
        ),
        (
            f"{comparison.target_candidate_id} physical_trial_passed="
            f"{comparison.trials.target_passed}"
        ),
    )

    if source_verified_and_passed and not target_verified_and_passed:
        return RevisionRecommendation(
            schema_version="1.0.0",
            source_candidate_id=comparison.source_candidate_id,
            target_candidate_id=comparison.target_candidate_id,
            decision=RecommendationDecision.PREFER_SOURCE,
            rationale=(
                f"{comparison.source_candidate_id} passed automated and "
                f"physical validation; {comparison.target_candidate_id} did not."
            ),
            measured_facts=measured_facts,
            missing_evidence=(),
        )

    if target_verified_and_passed and not source_verified_and_passed:
        return RevisionRecommendation(
            schema_version="1.0.0",
            source_candidate_id=comparison.source_candidate_id,
            target_candidate_id=comparison.target_candidate_id,
            decision=RecommendationDecision.PREFER_TARGET,
            rationale=(
                f"{comparison.target_candidate_id} passed automated and "
                f"physical validation; {comparison.source_candidate_id} did not."
            ),
            measured_facts=measured_facts,
            missing_evidence=(),
        )

    if source_verified_and_passed and target_verified_and_passed:
        rationale = (
            "Both candidates passed automated and physical validation; "
            "preferring one requires policy judgment beyond measured evidence."
        )
    else:
        rationale = (
            "Neither candidate passed both automated and physical "
            "validation; no measured basis prefers one over the other."
        )

    return RevisionRecommendation(
        schema_version="1.0.0",
        source_candidate_id=comparison.source_candidate_id,
        target_candidate_id=comparison.target_candidate_id,
        decision=RecommendationDecision.NO_PREFERENCE,
        rationale=rationale,
        measured_facts=measured_facts,
        missing_evidence=(),
    )


def _missing_trial_evidence(
    candidate_id: str,
    trial: PhysicalTrialManifest | None,
) -> str | None:
    """Describe why a candidate's trial cannot back a recommendation.

    A pending trial has not been printed, so it is missing evidence rather
    than a revise outcome.
    """

    if trial is not None and trial.pending:
        return f"{candidate_id} physical trial {trial.trial_id} is still pending"

    if trial is None or not trial.complete:
        return f"{candidate_id} has no complete physical trial"

    return None


def write_revision_comparison_report(
    report: RevisionComparisonReport,
    *,
    output_path: Path,
) -> None:
    """Write an immutable candidate-revision comparison report."""

    payload = {
        "schema_version": report.schema_version,
        "target_id": report.target_id,
        "source_candidate_id": report.source_candidate_id,
        "target_candidate_id": report.target_candidate_id,
        "automated": {
            "source_verified": report.automated.source_verified,
            "target_verified": report.automated.target_verified,
            "agreement": report.automated.agreement,
        },
        "trials": {
            "source_passed": report.trials.source_passed,
            "target_passed": report.trials.target_passed,
            "source_pending": report.trials.source_pending,
            "target_pending": report.trials.target_pending,
            "evidence_complete": report.trials.evidence_complete,
        },
        "parameters": {
            "changed": report.parameters.changed,
            "changes": [
                {
                    "parameter": change.parameter,
                    "previous_value": change.previous_value,
                    "current_value": change.current_value,
                    "change": change.change,
                }
                for change in report.parameters.changes
            ],
        },
    }

    _write_immutable_json(
        payload,
        output_path=output_path,
        error_context="comparison report",
    )


def write_revision_recommendation(
    recommendation: RevisionRecommendation,
    *,
    output_path: Path,
) -> None:
    """Write an immutable candidate-revision recommendation."""

    payload = {
        "schema_version": recommendation.schema_version,
        "source_candidate_id": recommendation.source_candidate_id,
        "target_candidate_id": recommendation.target_candidate_id,
        "decision": recommendation.decision.value,
        "rationale": recommendation.rationale,
        "measured_facts": list(recommendation.measured_facts),
        "missing_evidence": list(recommendation.missing_evidence),
    }

    _write_immutable_json(
        payload,
        output_path=output_path,
        error_context="recommendation",
    )


def _write_immutable_json(
    payload: Mapping[str, object],
    *,
    output_path: Path,
    error_context: str,
) -> None:
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
            f"Refusing to overwrite immutable {error_context}: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )

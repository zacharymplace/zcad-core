#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from zcad_core.retention import (
    CandidateRevision,
    RevisionRelationship,
    RevisionRelationshipType,
    compare_candidate_parameters,
    load_candidate_revision,
    write_immutable_manifest,
    write_revision_delta_report,
    write_revision_relationship,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "adafruit-feather-rp2040"

R001_ROOT = ROOT / "evidence" / TARGET_ID / "validation-lab" / "candidates" / "r001"

R002_ROOT = ROOT / "evidence" / TARGET_ID / "validation-lab" / "candidates" / "r002"

R001_MANIFEST = R001_ROOT / "candidate.json"
R002_MANIFEST = R002_ROOT / "candidate.json"

RELATIONSHIP_PATH = R002_ROOT / "relationship.json"

DELTA_PATH = R002_ROOT / "parameter-delta.json"


def build_r002(
    r001: CandidateRevision,
) -> CandidateRevision:
    policy = dict(r001.retention_policy)
    policy["board_clearance_mm"] = 0.30

    derived = dict(r001.derived_parameters)
    derived["board_clearance_mm"] = 0.30

    return replace(
        r001,
        candidate_id=("adafruit-feather-rp2040-corner-capture-r002"),
        revision="r002",
        retention_policy=policy,
        derived_parameters=derived,
        automated_decision=("synthetic_revision_candidate"),
        created_at_utc=r001.created_at_utc,
    )


def main() -> None:
    r001 = load_candidate_revision(R001_MANIFEST)

    r002 = build_r002(r001)

    write_immutable_manifest(
        r002,
        output_path=R002_MANIFEST,
    )

    relationship = RevisionRelationship(
        schema_version="1.0.0",
        target_id=TARGET_ID,
        source_candidate_id=r002.candidate_id,
        target_candidate_id=r001.candidate_id,
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason=(
            "Synthetic revision increases board clearance from 0.25 mm to 0.30 mm."
        ),
        created_at_utc=r002.created_at_utc,
    )

    delta = compare_candidate_parameters(
        source_candidate_id=(r001.candidate_id),
        target_candidate_id=(r002.candidate_id),
        source_parameters=(r001.derived_parameters),
        target_parameters=(r002.derived_parameters),
    )

    write_revision_relationship(
        relationship,
        output_path=RELATIONSHIP_PATH,
    )

    write_revision_delta_report(
        delta,
        output_path=DELTA_PATH,
    )

    print("=== SYNTHETIC FEATHER R002 ===")
    print(f"Candidate: {r002.candidate_id}")
    print(f"Relationship: {relationship.relationship.value}")
    print(f"Changed parameters: {len(delta.changes)}")
    print(f"Candidate manifest: {R002_MANIFEST}")
    print(f"Relationship record: {RELATIONSHIP_PATH}")
    print(f"Delta report: {DELTA_PATH}")


if __name__ == "__main__":
    main()

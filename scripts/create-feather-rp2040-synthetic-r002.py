#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from zcad_core.retention import (
    RevisionRelationshipType,
    load_candidate_revision,
    register_candidate_revision,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "adafruit-feather-rp2040"

R001_ROOT = ROOT / "evidence" / TARGET_ID / "validation-lab" / "candidates" / "r001"

R002_ROOT = ROOT / "evidence" / TARGET_ID / "validation-lab" / "candidates" / "r002"

R001_MANIFEST = R001_ROOT / "candidate.json"
R002_MANIFEST = R002_ROOT / "candidate.json"

RELATIONSHIP_PATH = R002_ROOT / "relationship.json"

DELTA_PATH = R002_ROOT / "parameter-delta.json"


def main() -> None:
    parent = load_candidate_revision(R001_MANIFEST)

    result = register_candidate_revision(
        parent_candidate=parent,
        revision="r002",
        parameter_updates={
            "board_clearance_mm": 0.30,
        },
        relationship=(RevisionRelationshipType.SUPERSEDES),
        reason=(
            "Synthetic revision increases board clearance from 0.25 mm to 0.30 mm."
        ),
        output_directory=R002_ROOT,
        automated_decision=("synthetic_revision_candidate"),
    )

    print("=== SYNTHETIC FEATHER R002 ===")
    print(f"Candidate: {result.candidate.candidate_id}")
    print(f"Relationship: {result.relationship.relationship.value}")
    print(f"Changed parameters: {len(result.delta_report.changes)}")
    print(f"Candidate manifest: {result.candidate_path}")
    print(f"Relationship record: {result.relationship_path}")
    print(f"Delta report: {result.delta_report_path}")


if __name__ == "__main__":
    main()

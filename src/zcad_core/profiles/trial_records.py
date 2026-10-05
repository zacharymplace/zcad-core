"""Trial records found under an evidence root, each counted once.

The profile derivers search an evidence root for trial records with
``rglob``, so a record copied into a second folder would otherwise be found,
and counted, twice: one print would then meet a profile's minimum number of
trials and carry double weight. Two real trials always differ, at the least
in when they were completed, so a record whose contents match one already
found is a copy and is skipped.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def distinct_trial_records(
    evidence_root: Path, pattern: str
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Each record matching ``pattern`` under ``evidence_root``, in path order,
    with any record whose contents repeat an earlier one left out."""

    seen: set[str] = set()

    for path in sorted(evidence_root.rglob(pattern)):
        record = _read(path)
        identity = json.dumps(record, sort_keys=True)

        if identity in seen:
            continue

        seen.add(identity)
        yield path, record

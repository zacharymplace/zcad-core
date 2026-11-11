"""Build the z-cadalog: every design the engine has built, from the build records under evidence/.

Each build record becomes one entry: what it is, its parts (their STL files beside the catalog
for its 3D viewer, as base64 in JSON, since a published page serves only web file types), its
checks, warnings, slice and nominal sizes, its lineage, how to build it again where the record
says, and its status. The status is read from the files beside the record, never typed in; the
first of these that holds:

0. ``example``: the build is under ``evidence/examples/``, built from a template's example
   readings to show what the product makes: never a real object, and never trialled;
1. ``superseded``: a later revision names this one (a candidate's ``relationship.json``, or a
   build's ``revision_of``);
2. ``promoted``: a candidate's ``promotion.json``;
3. ``verified``: the kind's own verification rule holds (a Gridfinity part's, called);
4. ``trial recorded``: a completed trial, with its disposition;
5. ``on print day``: a trial opened and pending;
6. ``reviewed``: a candidate with a visual review and no trial yet;
7. ``built``: a build record and nothing after it.

Each status names the file that settled it. A record of a kind the catalog does not know (any JSON
file whose ``parts`` give STL paths) is catalogued by its path, so a new product shows up before
the catalog learns its fields.

Writes ``<output>/catalog.json``, the models under ``<output>/models/``, and the page,
``<output>/index.html``, a copy of ``scripts/catalog/page.html``, which reads ``catalog.json``.
The output is generated: it is replaced on every run, and refused if it holds anything else.

After publishing the catalogue, ``--mark-published <url>`` notes which evidence went up, in an
ignored file beside it; every build then says whether the published page shows the evidence it
was built from, and ``--summary`` says it in one line, which ``backup-evidence.sh`` prints after
each backup.

Usage:
    python scripts/build-catalog.py [--evidence-root evidence] [--output catalog] [--summary]
    python scripts/build-catalog.py --mark-published <url> [--output catalog]
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.build_records import (
    KINDS,
    commit_of,
    find_records,
    head_commit,
    is_example,
    lineage,
    name_of,
    relative,
    status_of,
    stl_files,
    subject,
)
from zcad_core.build_records import checks as read_checks
from zcad_core.build_records import read as _read
from zcad_core.build_records import slices as read_slices

REPOSITORY = Path(__file__).resolve().parents[1]
TEMPLATE = REPOSITORY / "scripts" / "catalog" / "page.html"
CATALOG_SCHEMA_VERSION = "1.1.0"
# What the catalogue shows of each plate; the rest of the slice reading is the print day's.
PLATE_FIELDS = ("plate", "minutes", "grams", "warning", "commit")


def _rebuild(
    record_path: Path, record: dict[str, Any], plates: list[dict[str, Any]]
) -> str | None:
    recipe = next((plate["rebuild"] for plate in plates if plate.get("rebuild")), None)

    if isinstance(recipe, dict) and recipe.get("argv"):
        return "zcad-validation " + " ".join(recipe["argv"])

    relationship = record_path.parent / "relationship.json"

    if record_path.name == "candidate.json" and relationship.is_file():
        parent = _read(relationship)["target_candidate_id"].rsplit("-", 1)[-1]
        return (
            "python scripts/regenerate-candidate.py "
            f"{relative(record_path.parent.parent / parent, record_path.parents[4])} "
            f'--revision {record["revision"]} --reason "<why>"'
        )

    return None


def entry(
    record_path: Path,
    record: dict[str, Any],
    records: dict[Path, dict[str, Any]],
    evidence: Path,
    models: Path,
) -> dict[str, Any]:
    folder = record_path.parent
    design_id = folder.relative_to(evidence).as_posix()
    product, _ = KINDS.get(record_path.name, (None, None))
    built, asked = read_checks(record)
    plates = read_slices(folder)
    replaced, replaced_by = lineage(record_path, record, records)
    status: dict[str, Any] = (
        {"status": "example", "evidence": record_path}
        if is_example(record_path, evidence)
        else status_of(record_path, record, records)
    )
    model_files = []

    for part, stl in stl_files(record_path, record, evidence).items():
        # A published page serves only web file types, so each STL goes as base64 in JSON.
        target = models / design_id / f"{part}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "part": part,
                    "format": "stl",
                    "base64": base64.b64encode(stl.read_bytes()).decode("ascii"),
                }
            ),
            encoding="utf-8",
        )
        model_files.append(
            {"part": part, "file": target.relative_to(models.parent).as_posix()}
        )

    return {
        "id": design_id,
        "record": record_path.name,
        "kind": product or f"Other ({record_path.name})",
        "known_kind": product is not None,
        "name": name_of(record_path, record),
        "for": subject(record),
        "built_at_utc": record.get("built_at_utc") or record.get("created_at_utc"),
        "commit": commit_of(record, plates),
        "generator_version": record.get("generator_version"),
        "printer_profile_id": record.get("printer_profile_id"),
        "size_mm": record.get("size_mm") or record.get("outer_size_mm"),
        "settings": record.get("settings"),
        "checks": built,
        "trial_asks": asked,
        "warnings": list(record.get("warnings") or []),
        "nominal_measurements_mm": record.get("nominal_measurements_mm") or {},
        "slices": [{k: plate[k] for k in PLATE_FIELDS} for plate in plates],
        "models": model_files,
        "replaces": replaced,
        "replaced_by": replaced_by,
        "status": status["status"],
        "status_detail": status.get("disposition") or status.get("by"),
        "status_evidence": relative(status.get("evidence"), evidence),
        "rebuild": _rebuild(record_path, record, plates),
        "folder": "evidence/" + design_id,
    }


def build_catalog(evidence: Path, output: Path) -> dict[str, Any]:
    """Write the catalog for ``evidence`` into ``output``, replacing a catalog there."""

    if output.exists():
        if not (output / "catalog.json").is_file():
            raise FileExistsError(
                f"{output} exists and is not a catalog: refusing to replace it"
            )
        shutil.rmtree(output)

    models = output / "models"
    models.mkdir(parents=True)
    paths = find_records(evidence)
    records = {path: _read(path) for path in paths}
    entries = [
        entry(path, record, records, evidence, models)
        for path, record in records.items()
    ]
    catalog = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "repository_commit": head_commit(REPOSITORY),
        "evidence_commit": head_commit(evidence),
        "designs": entries,
    }
    (output / "catalog.json").write_text(
        json.dumps(catalog, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copyfile(TEMPLATE, output / "index.html")

    return catalog


def published_record(output: Path) -> Path:
    """Where this checkout notes what it last published: beside the catalogue, which is
    replaced on every build, and ignored by git as the catalogue is."""

    return output.parent / f".{output.name}-published.json"


def mark_published(output: Path, url: str) -> dict[str, Any]:
    """Note that the catalogue in ``output`` was published at ``url``."""

    catalog = _read(output / "catalog.json")
    record = {
        "url": url,
        "evidence_commit": catalog.get("evidence_commit"),
        "repository_commit": catalog.get("repository_commit"),
        "designs": len(catalog.get("designs", [])),
        "published_at_utc": datetime.now(UTC).isoformat(),
    }
    published_record(output).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )

    return record


def summary(output: Path, catalog: dict[str, Any]) -> str:
    """One line: the catalogue's evidence, and whether the published page shows it."""

    here = catalog.get("evidence_commit")
    line = f"catalog: {len(catalog['designs'])} designs at evidence {here or '?'}"
    record_path = published_record(output)

    if here is None:
        return f"{line}; the evidence is not in git, so whether a published page is current cannot be told"

    if not record_path.is_file():
        return (
            f"{line}; not published from this checkout: publish {output}/ and run "
            "scripts/build-catalog.py --mark-published <url>"
        )

    published = _read(record_path)

    if published.get("evidence_commit") == here:
        return f"{line}; the published page ({published['url']}) is current"

    return (
        f"{line}; the published page ({published['url']}) shows evidence "
        f"{published.get('evidence_commit') or '?'}: republish it, then mark it published"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    parser.add_argument("--output", type=Path, default=Path("catalog"))
    parser.add_argument(
        "--mark-published",
        metavar="URL",
        help="note that the catalogue now in --output was published at URL; builds nothing",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print one line: the catalogue's evidence and whether the published page shows it",
    )
    args = parser.parse_args()

    if args.mark_published:
        print(json.dumps(mark_published(args.output, args.mark_published), indent=2))
        return 0

    catalog = build_catalog(args.evidence_root.resolve(), args.output)

    if args.summary:
        print(summary(args.output, catalog))
        return 0

    counts: dict[str, int] = {}

    for design in catalog["designs"]:
        counts[design["status"]] = counts.get(design["status"], 0) + 1

    print(
        json.dumps(
            {
                "catalog": str(args.output),
                "designs": len(catalog["designs"]),
                "status": counts,
                "published": summary(args.output, catalog).split("; ", 1)[1],
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
TEMPLATE = REPOSITORY / "scripts" / "catalog" / "page.html"
CATALOG_SCHEMA_VERSION = "1.1.0"
# Builds from a template's example readings, one of each product not yet built for real.
EXAMPLES = "examples"

# Known build records: the product they are, and the file a completed trial writes.
KINDS = {
    "candidate.json": ("Validation Lab fixture", "trial.json"),
    "enclosure.json": ("Enclosure", "enclosure-trial.json"),
    "enclosure-group.json": ("Group enclosure", "enclosure-group-trial.json"),
    "coupon.json": ("Calibration coupon", "calibration-coupon-trial.json"),
    "gridfinity.json": ("Gridfinity", "gridfinity-trial.json"),
    "holder.json": ("Object holder", "holder-trial.json"),
    "nest.json": ("Holding nest", "nest-trial.json"),
    "jig.json": ("Insert jig", "jig-trial.json"),
    "stack-build.json": ("Stackable items", "stack-trial.json"),
    "layer-build.json": ("Stack layer", "layer-trial.json"),
    "housing-build.json": ("Wearable housing", "housing-trial.json"),
    "guide.json": ("Drill guide", "guide-trial.json"),
    "fixture.json": ("PCB test fixture", "fixture-trial.json"),
}
# Folders a build writes inside its own, which hold no build records.
INNER = {
    "trials",
    "slice",
    "print",
    "export-validation",
    "review",
    "design-review-superseded",
}


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"{path} is not a JSON object")

    return payload


def _parts_with_stl(record: dict[str, Any]) -> bool:
    parts = record.get("parts")

    return isinstance(parts, dict) and any(
        isinstance(part, dict) and "stl_path" in part for part in parts.values()
    )


def find_records(evidence: Path) -> list[Path]:
    """Every build record under ``evidence``: the known kinds by name, and any other JSON
    object whose ``parts`` give STL paths."""

    found = []

    for path in sorted(evidence.rglob("*.json")):
        relative = path.relative_to(evidence)

        if relative.parts[0].startswith(".") or INNER & set(relative.parts[:-1]):
            continue

        if path.name in KINDS:
            found.append(path)
            continue

        if path.name.endswith(".metadata.json"):
            continue

        try:
            record = _read(path)
        except (TypeError, ValueError):
            continue

        if _parts_with_stl(record):
            found.append(path)

    return found


def _locate(named: str, record_path: Path, evidence: Path) -> Path:
    """A path as a record writes it: absolute, from the repository (``evidence/...``), or
    beside the record. A record written in another checkout is found by name beside it."""

    path = Path(named)

    if not path.is_absolute():
        path = (
            evidence.parent / path
            if path.parts[:1] == ("evidence",)
            else record_path.parent / path
        )

    return path if path.is_file() else record_path.parent / path.name


def _stl_files(
    record_path: Path, record: dict[str, Any], evidence: Path
) -> dict[str, Path]:
    """Each part's exported STL, found from the record's own paths."""

    if record_path.name == "candidate.json":
        # The candidate names its fixture; a snap shell's is a STEP only, with no STL.
        named = str(record.get("fixture_artifact_path") or "")
        fixture = _locate(named, record_path, evidence) if named else None
        return (
            {"fixture": fixture}
            if fixture and fixture.suffix == ".stl" and fixture.is_file()
            else {}
        )

    found = {}
    parts = dict(record.get("parts") or {})

    # A stack build keeps each item's part under its name.
    for name, item in (record.get("items") or {}).items():
        if isinstance(item, dict) and isinstance(item.get("part"), dict):
            parts[name] = item["part"]

    for name, part in parts.items():
        if isinstance(part, dict) and "stl_path" in part:
            stl = _locate(str(part["stl_path"]), record_path, evidence)

            if stl.is_file():
                found[name] = stl

    return found


def _checks(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks the build passed, and the checks a trial asks."""

    built: list[dict[str, Any]] = []
    asked: list[str] = []

    for source in (record.get("fit_checks"), record.get("checks")):
        if isinstance(source, dict):
            for name, value in source.items():
                if isinstance(value, dict):
                    built.append(
                        {
                            "name": name,
                            "passed": value.get("passed"),
                            "detail": str(value.get("detail", "")),
                        }
                    )
                elif isinstance(value, bool):
                    built.append({"name": name, "passed": value, "detail": ""})
        elif isinstance(source, list):
            asked.extend(str(name) for name in source)

    return built, asked


def _slices(folder: Path) -> list[dict[str, Any]]:
    plates = []

    for summary_path in sorted((folder / "slice").rglob("slice-summary.json")):
        summary = _read(summary_path)
        plates.append(
            {
                "plate": summary_path.parent.relative_to(folder).as_posix(),
                "minutes": round(summary["estimated_print_time_seconds"] / 60, 1),
                "grams": round(summary["filament_used_g"], 2),
                "warning": summary.get("slicer_warning", ""),
                "rebuild": summary.get("rebuild"),
                "commit": (summary.get("source") or {}).get("git_commit"),
            }
        )

    return plates


def _trials(folder: Path, trial_record: str) -> list[dict[str, Any]]:
    """Each trial folder: completed (its disposition) or open."""

    trials = []

    for trial in sorted((folder / "trials").glob("trial-*")):
        record_path = trial / trial_record
        pending_path = trial / "physical-validation.json"

        if record_path.is_file():
            record = _read(record_path)
            disposition = record.get("disposition")

            if disposition is None and pending_path.is_file():
                disposition = _read(pending_path).get("disposition")

            trials.append(
                {
                    "trial": trial.name,
                    "complete": True,
                    "disposition": disposition or "measured",
                    "record": record_path,
                }
            )
        elif pending_path.is_file() and not _read(pending_path).get("pending", True):
            trials.append(
                {
                    "trial": trial.name,
                    "complete": True,
                    "disposition": _read(pending_path).get("disposition"),
                    "record": pending_path,
                }
            )
        else:
            trials.append(
                {
                    "trial": trial.name,
                    "complete": False,
                    "disposition": "pending",
                    "record": trial,
                }
            )

    return trials


def _verified(record_path: Path) -> bool:
    """The kind's own verification rule, where it has one."""

    if record_path.name != "gridfinity.json":
        return False

    from zcad_core.features.gridfinity_trial import gridfinity_verification

    return bool(gridfinity_verification(record_path)["verified"])


def _lineage(
    record_path: Path, record: dict[str, Any], records: dict[Path, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """The design this one replaced, and the one that replaced it, by design id."""

    if record_path.name == "candidate.json":
        mine = record["candidate_id"]
        # Every relationship (supersedes, derived_from, adjusts_clearance_from) makes a new
        # revision from its parent, which it replaces.
        relationship = record_path.parent / "relationship.json"
        replaced = (
            _read(relationship).get("target_candidate_id")
            if relationship.is_file()
            else None
        )
        replaced_by = None

        for other in record_path.parent.parent.glob("*/relationship.json"):
            link = _read(other)

            if link.get("target_candidate_id") == mine:
                replaced_by = link.get("source_candidate_id")

        return replaced, replaced_by

    name = record.get("design_name")
    replaced = record.get("revision_of")
    replaced_by = next(
        (
            other.get("design_name") or path.parent.name
            for path, other in records.items()
            if path != record_path
            and other.get("revision_of")
            and other.get("revision_of") in (name, record_path.parent.name)
        ),
        None,
    )

    return (str(replaced) if replaced else None), replaced_by


def status_of(
    record_path: Path, record: dict[str, Any], records: dict[Path, dict[str, Any]]
) -> dict[str, Any]:
    """The design's status and the file that settled it."""

    folder = record_path.parent
    _, trial_record = KINDS.get(record_path.name, ("", ""))
    _, replaced_by = _lineage(record_path, record, records)

    if replaced_by:
        return {"status": "superseded", "by": replaced_by, "evidence": None}

    if (folder / "promotion.json").is_file():
        return {"status": "promoted", "evidence": folder / "promotion.json"}

    if _verified(record_path):
        return {"status": "verified", "evidence": record_path}

    trials = _trials(folder, trial_record) if trial_record else []
    completed = [trial for trial in trials if trial["complete"]]

    if completed:
        last = completed[-1]
        return {
            "status": "trial recorded",
            "disposition": last["disposition"],
            "evidence": last["record"],
        }

    if trials:
        return {"status": "on print day", "evidence": trials[-1]["record"]}

    if (folder / "visual-review.json").is_file():
        review = _read(folder / "visual-review.json")
        return {
            "status": "reviewed",
            "disposition": review.get("disposition"),
            "evidence": folder / "visual-review.json",
        }

    return {"status": "built", "evidence": record_path}


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
            f"{_relative(record_path.parent.parent / parent, record_path.parents[4])} "
            f'--revision {record["revision"]} --reason "<why>"'
        )

    return None


def _subject(record: dict[str, Any]) -> str | None:
    """What the design is for: a candidate's target, or an enclosure's board."""

    if record.get("target_id"):
        return str(record["target_id"])

    board = record.get("board")

    if isinstance(board, dict):
        return str(board.get("name") or board.get("id") or "") or None

    return str(board) if board else None


def _relative(path: Path | None, evidence: Path) -> str | None:
    if path is None:
        return None

    try:
        return "evidence/" + path.relative_to(evidence).as_posix()
    except ValueError:
        return str(path)


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
    built, asked = _checks(record)
    plates = _slices(folder)
    replaced, replaced_by = _lineage(record_path, record, records)
    status: dict[str, Any] = (
        {"status": "example", "evidence": record_path}
        if design_id.split("/")[0] == EXAMPLES
        else status_of(record_path, record, records)
    )
    model_files = []

    for part, stl in _stl_files(record_path, record, evidence).items():
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
        "name": record.get("candidate_id") or record.get("design_name") or folder.name,
        "for": _subject(record),
        "built_at_utc": record.get("built_at_utc") or record.get("created_at_utc"),
        "commit": record.get("git_commit")
        or next((plate["commit"] for plate in plates if plate.get("commit")), None),
        "generator_version": record.get("generator_version"),
        "printer_profile_id": record.get("printer_profile_id"),
        "size_mm": record.get("size_mm") or record.get("outer_size_mm"),
        "settings": record.get("settings"),
        "checks": built,
        "trial_asks": asked,
        "warnings": list(record.get("warnings") or []),
        "nominal_measurements_mm": record.get("nominal_measurements_mm") or {},
        "slices": [
            {k: v for k, v in plate.items() if k != "rebuild"} for plate in plates
        ],
        "models": model_files,
        "replaces": replaced,
        "replaced_by": replaced_by,
        "status": status["status"],
        "status_detail": status.get("disposition") or status.get("by"),
        "status_evidence": _relative(status.get("evidence"), evidence),
        "rebuild": _rebuild(record_path, record, plates),
        "folder": "evidence/" + design_id,
    }


def _commit(directory: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


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
        "repository_commit": _commit(REPOSITORY),
        "evidence_commit": _commit(evidence),
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

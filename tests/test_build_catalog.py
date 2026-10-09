"""The z-cadalog: every build record under evidence/, its status read from the files beside it."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-catalog.py"
STL = "solid part\nendsolid part\n"


def catalogue() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_catalog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, payload: dict[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )


def candidate(evidence: Path, target: str, revision: str, **files: Any) -> Path:
    folder = evidence / target / "validation-lab" / "candidates" / revision
    write(
        folder / "candidate.json",
        {
            "candidate_id": f"{target}-corner-capture-{revision}",
            "target_id": target,
            "revision": revision,
            "generator_version": "1.5.0",
            "git_commit": "abc1234",
            "created_at_utc": "2026-10-07T00:00:00+00:00",
            "fixture_artifact_path": f"evidence/{target}/validation-lab/candidates/{revision}/fixture.stl",
        },
    )
    write(folder / "fixture.stl", STL)

    for name, payload in files.items():
        write(folder / name.replace("__", "/"), payload)

    return folder


def build(evidence: Path, kind: str, name: str, record: str, **extra: Any) -> Path:
    folder = evidence / kind / name
    write(folder / f"{name}-part.stl", STL)
    write(
        folder / record,
        {
            "design_name": name,
            "parts": {"part": {"stl_path": f"evidence/{kind}/{name}/{name}-part.stl"}},
            **extra,
        },
    )
    return folder


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    candidate(root, "board-a", "r001")
    candidate(
        root,
        "board-a",
        "r002",
        **{
            "relationship.json": {
                "relationship": "supersedes",
                "source_candidate_id": "board-a-corner-capture-r002",
                "target_candidate_id": "board-a-corner-capture-r001",
            },
            "visual-review.json": {"disposition": "pass_with_reservations"},
            "trials__trial-001__physical-validation.json": {
                "pending": True,
                "disposition": "pending",
            },
        },
    )
    candidate(
        root,
        "board-b",
        "r001",
        **{"visual-review.json": {"disposition": "pass_with_reservations"}},
    )
    coupon = build(root, "coupons", "c1", "coupon.json")
    write(coupon / "trials/trial-001/calibration-coupon-trial.json", {"features": []})
    joint = build(root, "joints", "fit-01", "joint-coupon.json")
    write(joint / "trials/trial-001/joint-coupon-trial.json", {"readings": []})
    build(root, "enclosures", "e1", "enclosure.json", checks=["board_seats"])
    build(
        root,
        "enclosures",
        "e2",
        "enclosure.json",
        revision_of="e1",
        fit_checks={"one_solid": True, "fits_bed": False},
    )
    build(root, "widgets", "w1", "widget.json")
    # An example: built from a template's readings, even with a trial opened beside it.
    holder = build(root, "examples/holders", "h1", "holder.json")
    (holder / "trials" / "trial-001").mkdir(parents=True)

    return root


def by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {design["id"]: design for design in catalog["designs"]}


def test_every_record_is_found_and_its_status_read_from_beside_it(
    evidence: Path, tmp_path: Path
) -> None:
    designs = by_id(catalogue().build_catalog(evidence, tmp_path / "catalog"))
    status = {key: (d["status"], d["status_detail"]) for key, d in designs.items()}

    assert status == {
        "board-a/validation-lab/candidates/r001": (
            "superseded",
            "board-a-corner-capture-r002",
        ),
        "board-a/validation-lab/candidates/r002": ("on print day", None),
        "board-b/validation-lab/candidates/r001": (
            "reviewed",
            "pass_with_reservations",
        ),
        "coupons/c1": ("trial recorded", "measured"),
        "joints/fit-01": ("trial recorded", "measured"),
        "enclosures/e1": ("superseded", "e2"),
        "enclosures/e2": ("built", None),
        "widgets/w1": ("built", None),
        "examples/holders/h1": ("example", None),
    }
    pending = designs["board-a/validation-lab/candidates/r002"]
    assert pending["status_evidence"] == (
        "evidence/board-a/validation-lab/candidates/r002/trials/trial-001"
    )
    assert pending["replaces"] == "board-a-corner-capture-r001"
    assert "candidates/r001 --revision r002" in pending["rebuild"]


def test_a_record_of_an_unknown_kind_is_listed_by_its_path(
    evidence: Path, tmp_path: Path
) -> None:
    widget = by_id(catalogue().build_catalog(evidence, tmp_path / "catalog"))[
        "widgets/w1"
    ]

    assert widget["kind"] == "Other (widget.json)"
    assert widget["known_kind"] is False
    assert widget["folder"] == "evidence/widgets/w1"


def test_each_part_is_written_beside_the_catalogue_for_its_viewer(
    evidence: Path, tmp_path: Path
) -> None:
    output = tmp_path / "catalog"
    designs = by_id(catalogue().build_catalog(evidence, output))
    e2 = designs["enclosures/e2"]

    # As base64 in JSON: a published page serves only web file types, and STL is not one.
    assert e2["models"] == [{"part": "part", "file": "models/enclosures/e2/part.json"}]
    model = json.loads((output / e2["models"][0]["file"]).read_text())
    assert (model["part"], model["format"]) == ("part", "stl")
    assert base64.b64decode(model["base64"]).decode() == STL
    assert (output / "index.html").is_file()
    assert e2["checks"] == [
        {"name": "one_solid", "passed": True, "detail": ""},
        {"name": "fits_bed", "passed": False, "detail": ""},
    ]
    assert designs["enclosures/e1"]["trial_asks"] == ["board_seats"]


def test_the_catalogue_says_whether_its_published_page_is_behind(
    evidence: Path, tmp_path: Path
) -> None:
    module = catalogue()
    output = tmp_path / "catalog"

    assert "is not in git" in module.summary(
        output, module.build_catalog(evidence, output)
    )

    # Real evidence is a git repository, which the published page is pinned to.
    for command in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "Evidence"]):
        subprocess.run(
            ["git", "-C", str(evidence), *command],
            check=True,
            capture_output=True,
            env={
                **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            },
        )
    catalog = module.build_catalog(evidence, output)

    assert "not published from this checkout" in module.summary(output, catalog)

    url = "https://claude.ai/artifact/example"
    module.mark_published(output, url)

    assert module.summary(output, catalog).endswith(f"({url}) is current")
    assert (tmp_path / ".catalog-published.json").is_file()

    moved_on = {**catalog, "evidence_commit": "f00dfee"}
    assert "republish it" in module.summary(output, moved_on)


def test_the_catalogue_is_regenerated_and_never_replaces_anything_else(
    evidence: Path, tmp_path: Path
) -> None:
    module = catalogue()
    output = tmp_path / "catalog"
    first = module.build_catalog(evidence, output)
    second = module.build_catalog(evidence, output)

    assert first["designs"] == second["designs"]

    elsewhere = tmp_path / "notes"
    write(elsewhere / "keep.txt", "mine")

    with pytest.raises(FileExistsError, match="not a catalog"):
        module.build_catalog(evidence, elsewhere)

    assert (elsewhere / "keep.txt").read_text() == "mine"

"""The Tandem Mobi snap-shell script: the first revision, and later ones."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "scripts" / "build-tandem-mobi-snap-shell-candidate.py"
CANDIDATES = Path("evidence/tandem-mobi-pump/validation-lab/candidates")


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_tandem_snap_shell", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up while the module is still loading.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "git_commit", lambda root: "c" * 40)
    return module


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "profiles").symlink_to(REPOSITORY / "profiles")
    # Export validation reads the candidate's paths from the working
    # directory, as the script does when run from the repository root.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_a_later_revision_records_its_parent_and_leaves_it_alone(
    script: ModuleType, root: Path
) -> None:
    script.main([], root=root)
    first = snapshot(root / "evidence")

    script.main(
        ["--revision", "r002", "--parent", "r001", "--reason", "Corrected width"],
        root=root,
    )

    after = snapshot(root / "evidence")
    assert {path: after[path] for path in first} == first
    relationship = json.loads(
        (root / CANDIDATES / "r002" / "relationship.json").read_text("utf-8")
    )
    assert relationship["relationship"] == "supersedes"
    assert relationship["target_candidate_id"] == "tandem-mobi-pump-snap-shell-r001"
    assert relationship["reason"] == "Corrected width"
    report = json.loads(
        (root / CANDIDATES / "r002" / "automated-validation.json").read_text("utf-8")
    )
    assert report["source"]["step_path"].endswith("placeholder-envelope-r002.step")
    assert (root / CANDIDATES / "r002" / "parameter-delta.json").is_file()


def test_rerunning_a_revision_is_refused_before_anything_is_written(
    script: ModuleType, root: Path
) -> None:
    script.main([], root=root)
    before = snapshot(root / "evidence")

    with pytest.raises(SystemExit, match="Refusing to regenerate over pinned files"):
        script.main([], root=root)

    assert snapshot(root / "evidence") == before


def test_a_later_revision_needs_a_registered_parent(
    script: ModuleType, root: Path
) -> None:
    with pytest.raises(SystemExit, match="needs its target and parent registered"):
        script.main(
            ["--revision", "r002", "--parent", "r001", "--reason", "Corrected width"],
            root=root,
        )

    assert not (root / "evidence" / "tandem-mobi-pump" / "step").exists()


@pytest.mark.parametrize(
    "argv",
    [["--revision", "r002"], ["--parent", "r001", "--reason", "No parent for r001"]],
)
def test_revision_arguments_must_agree(
    script: ModuleType, root: Path, argv: list[str]
) -> None:
    with pytest.raises(SystemExit):
        script.main(argv, root=root)

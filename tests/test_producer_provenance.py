"""Producer identity stays distinct from consumer and unknown source states."""

import subprocess
from pathlib import Path

import pytest

from zcad_core.metadata import producer
from zcad_core.metadata.git import git_environment


def test_loaded_core_clean_dirty_and_hook_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "core"
    module = root / "src/zcad_core/__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("# fixture\n")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            env=git_environment(),
        ).stdout.strip()

    git("init", "-q")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = git("rev-parse", "HEAD")
    monkeypatch.setattr(producer.zcad_core, "__file__", str(module))
    monkeypatch.setattr(producer, "version", lambda name: "0.fixture")
    monkeypatch.setenv("GIT_DIR", "/unrelated/consumer/.git")
    record = producer.producer_provenance()
    assert record == {
        "name": "zcad-core",
        "distribution_version": "0.fixture",
        "git_commit": commit,
        "tracked_worktree_state": "clean",
    }
    (root / "untracked.txt").write_text("ignored by provenance")
    assert producer.producer_provenance()["tracked_worktree_state"] == "clean"
    module.write_text("# changed\n")
    assert producer.producer_provenance()["tracked_worktree_state"] == "dirty"


def test_non_git_install_and_git_failure_are_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "installed/zcad_core/__init__.py"
    module.parent.mkdir(parents=True)
    module.touch()
    monkeypatch.setattr(producer.zcad_core, "__file__", str(module))
    monkeypatch.setattr(producer, "version", lambda name: "1.2.3")
    assert producer.producer_provenance() == {
        "name": "zcad-core",
        "distribution_version": "1.2.3",
        "git_commit": None,
        "tracked_worktree_state": "unknown",
    }

    def fail(*args: object) -> str:
        raise subprocess.TimeoutExpired("git", 3)

    monkeypatch.setattr(producer, "_git", fail)
    assert producer.producer_provenance()["tracked_worktree_state"] == "unknown"


def test_untracked_module_does_not_borrow_enclosing_git_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(name: str) -> str:
        raise producer.PackageNotFoundError(name)

    def git(directory: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return str(Path(producer.zcad_core.__file__).resolve().parents[3])
        raise subprocess.CalledProcessError(1, "git ls-files")

    monkeypatch.setattr(producer, "version", missing_version)
    monkeypatch.setattr(producer, "_git", git)
    assert producer.producer_provenance() == {
        "name": "zcad-core",
        "distribution_version": None,
        "git_commit": None,
        "tracked_worktree_state": "unknown",
    }

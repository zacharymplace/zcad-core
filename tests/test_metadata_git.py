"""Git calls that a hook's environment cannot redirect."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from zcad_core.metadata.build_record import current_git_commit
from zcad_core.metadata.git import REPOSITORY_VARIABLES, git_environment

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def scratch_repository(path: Path) -> str:
    """A one-commit repository at ``path``, made without writing any config."""

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *arguments],
            capture_output=True,
            text=True,
            check=True,
            env=git_environment(),
        ).stdout.strip()

    git("init", "-q")
    (path / "README.md").write_text("scratch\n", encoding="utf-8")
    git("add", "README.md")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "Start",
    )

    return git("rev-parse", "HEAD")


def test_the_environment_drops_what_points_git_at_a_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in REPOSITORY_VARIABLES:
        monkeypatch.setenv(name, "/elsewhere")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Kept")

    environment = git_environment()

    assert not REPOSITORY_VARIABLES & set(environment)
    assert environment["GIT_AUTHOR_NAME"] == "Kept"


def test_a_build_record_names_its_own_repositorys_commit_under_a_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    ours.mkdir()
    theirs.mkdir()
    commit = scratch_repository(ours)
    scratch_repository(theirs)
    # As a pre-push hook leaves it for the tests it runs.
    monkeypatch.setenv("GIT_DIR", str(theirs / ".git"))

    assert current_git_commit(ours) == commit


def test_the_gate_script_unsets_every_repository_variable() -> None:
    script = (REPOSITORY_ROOT / "scripts/check.sh").read_text(encoding="utf-8")
    match = re.search(r"^unset ((?:[^\n]*\\\n)*[^\n]*)$", script, re.MULTILINE)

    assert match is not None
    assert set(match.group(1).replace("\\\n", " ").split()) == REPOSITORY_VARIABLES

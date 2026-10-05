""".githooks/pre-push: which pushes it gates, passes, or refuses."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-push"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}
ZERO = "0" * 40
# The bash first on PATH, and macOS's own, which is 3.2.
SHELLS = ["bash"] + (["/bin/bash"] if Path("/bin/bash").exists() else [])


def environment() -> dict[str, str]:
    # This test runs under the real pre-push hook, which exports GIT_DIR and
    # friends; they would point every git command here at this repository.
    clean = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    return {**clean, **IDENTITY}


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment(),
    ).stdout.strip()


@pytest.fixture(params=SHELLS)
def shell(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A checkout with the hook and a stand-in for the gates, whose main is
    already on its remote, and a newer commit checked out on a branch."""

    checkout = tmp_path / "checkout"
    (checkout / ".githooks").mkdir(parents=True)
    (checkout / "scripts").mkdir()
    shutil.copy(HOOK, checkout / ".githooks" / "pre-push")
    gates = checkout / "scripts" / "check.sh"
    gates.write_text('#!/usr/bin/env bash\ntouch "$(dirname "$0")/../gates-ran"\n')
    gates.chmod(0o755)
    (checkout / ".gitignore").write_text("gates-ran\n")

    git(tmp_path, "init", "-q", "--bare", "-b", "main", "remote.git")
    git(checkout, "init", "-q", "-b", "main")
    git(checkout, "remote", "add", "origin", str(tmp_path / "remote.git"))
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "On the remote")
    git(checkout, "push", "-q", "-u", "origin", "main")
    git(checkout, "switch", "-q", "-c", "work")
    git(checkout, "commit", "-q", "--allow-empty", "-m", "Not pushed")

    return checkout


def push(
    repository: Path, shell: str, ref: str, sha: str
) -> subprocess.CompletedProcess[str]:
    """Run the hook as git would for one ref."""

    return subprocess.run(
        [shell, str(repository / ".githooks" / "pre-push"), "origin", "remote.git"],
        input=f"{ref} {sha} {ref} {ZERO}\n",
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=environment(),
    )


def gated(repository: Path) -> bool:
    return (repository / "gates-ran").exists()


def test_an_annotated_tag_on_the_checked_out_commit_is_gated(
    repository: Path, shell: str
) -> None:
    git(repository, "tag", "-a", "v1", "-m", "v1")

    result = push(repository, shell, "refs/tags/v1", git(repository, "rev-parse", "v1"))

    assert result.returncode == 0, result.stderr
    assert gated(repository)


def test_a_tag_on_a_commit_the_remote_has_passes_without_gates(
    repository: Path, shell: str
) -> None:
    # The release tag on main's merge commit, pushed from another branch.
    git(repository, "tag", "-a", "v1", "-m", "v1", "main")

    result = push(repository, shell, "refs/tags/v1", git(repository, "rev-parse", "v1"))

    assert result.returncode == 0, result.stderr
    assert not gated(repository)


def test_a_tag_on_an_unpushed_commit_that_is_not_checked_out_is_refused(
    repository: Path, shell: str
) -> None:
    git(repository, "commit", "-q", "--allow-empty", "-m", "Newer still")
    git(repository, "tag", "-a", "v1", "-m", "v1", "HEAD~1")

    result = push(repository, shell, "refs/tags/v1", git(repository, "rev-parse", "v1"))

    assert result.returncode == 1
    assert "not the checked-out commit" in result.stderr
    assert not gated(repository)


def test_a_branch_must_still_be_the_checked_out_commit(
    repository: Path, shell: str
) -> None:
    # main is on the remote, but a branch is only ever pushed from its checkout.
    result = push(
        repository, shell, "refs/heads/main", git(repository, "rev-parse", "main")
    )

    assert result.returncode == 1
    assert "not the checked-out commit" in result.stderr


def test_a_deletion_needs_no_gates(repository: Path, shell: str) -> None:
    result = push(repository, shell, "refs/tags/v1", ZERO)

    assert result.returncode == 0, result.stderr
    assert not gated(repository)

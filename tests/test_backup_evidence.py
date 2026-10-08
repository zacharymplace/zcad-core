"""scripts/backup-evidence.sh refuses a template that is not filled in."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-evidence.sh"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def environment() -> dict[str, str]:
    # The pre-push hook exports GIT_DIR and friends, which would point every
    # git command here at this repository instead of the scratch ones.
    clean = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    return {**clean, **IDENTITY}


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment(),
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout with the script, and evidence/ with a remote to push to."""

    repository = tmp_path / "checkout"
    (repository / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repository / "scripts" / SCRIPT.name)
    git(repository, "init", "-q", "-b", "main")

    remote = tmp_path / "evidence.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    evidence = repository / "evidence"
    evidence.mkdir()
    git(evidence, "init", "-q", "-b", "main")
    git(evidence, "remote", "add", "origin", str(remote))
    (evidence / "kept.json").write_text('{"kept": true}\n', encoding="utf-8")
    git(evidence, "add", "-A")
    git(evidence, "commit", "-q", "-m", "First")
    git(evidence, "push", "-q", "-u", "origin", "main")

    return repository


# The bash first on PATH, and macOS's own, which is 3.2 and stricter about
# empty arrays under `set -u`.
SHELLS = ["bash"] + (["/bin/bash"] if Path("/bin/bash").exists() else [])


@pytest.fixture(params=SHELLS)
def shell(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def back_up(
    checkout: Path, shell: str, **variables: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shell, str(checkout / "scripts" / SCRIPT.name)],
        # The tests assert on the exit status, including a refusal.
        check=False,
        capture_output=True,
        text=True,
        env={**environment(), **variables},
    )


def test_a_template_still_saying_needs_review_is_not_backed_up(
    checkout: Path, shell: str
) -> None:
    evidence = checkout / "evidence"
    before = git(evidence, "rev-parse", "HEAD")
    (evidence / "mobi.json").write_text(
        '{"needs_review": "EXAMPLE ONLY", "length_mm": [51.3]}\n', encoding="utf-8"
    )
    (evidence / "filled.json").write_text('{"length_mm": [51.2]}\n', encoding="utf-8")

    result = back_up(checkout, shell)

    assert result.returncode == 1
    assert "mobi.json" in result.stderr
    assert "filled.json" not in result.stderr
    # Nothing committed or pushed, not even the filled-in file.
    assert git(evidence, "rev-parse", "HEAD") == before
    assert git(evidence, "status", "--porcelain").count("??") == 2


def test_filled_in_evidence_is_committed_and_pushed(checkout: Path, shell: str) -> None:
    evidence = checkout / "evidence"
    (evidence / "filled.json").write_text('{"length_mm": [51.2]}\n', encoding="utf-8")
    # A deleted file has nothing to check and must not trip the guard.
    (evidence / "kept.json").unlink()

    result = back_up(checkout, shell)

    assert result.returncode == 0, result.stderr
    assert "backup-evidence: pushed" in result.stdout
    assert git(evidence, "status", "--porcelain") == ""
    assert git(evidence, "rev-parse", "HEAD") == git(
        evidence, "rev-parse", "origin/main"
    )


def test_a_file_too_large_for_git_and_not_in_lfs_is_not_backed_up(
    checkout: Path, shell: str
) -> None:
    evidence = checkout / "evidence"
    before = git(evidence, "rev-parse", "HEAD")
    (evidence / "board.step").write_bytes(b"ISO-10303-21;\n" * 100)
    (evidence / "small.json").write_text("{}\n", encoding="utf-8")

    result = back_up(checkout, shell, EVIDENCE_GIT_FILE_LIMIT_BYTES="1000")

    assert result.returncode == 1
    assert "board.step" in result.stderr
    assert "small.json" not in result.stderr
    assert git(evidence, "rev-parse", "HEAD") == before


@pytest.mark.skipif(shutil.which("git-lfs") is None, reason="needs git-lfs")
def test_a_large_file_tracked_by_lfs_is_backed_up_as_a_pointer(
    checkout: Path, shell: str
) -> None:
    evidence = checkout / "evidence"
    git(evidence, "lfs", "install", "--local")
    git(evidence, "lfs", "track", "*.step")
    (evidence / "board.step").write_bytes(b"ISO-10303-21;\n" * 100)

    result = back_up(checkout, shell, EVIDENCE_GIT_FILE_LIMIT_BYTES="1000")

    assert result.returncode == 0, result.stderr
    assert git(evidence, "lfs", "ls-files", "--name-only") == "board.step"
    pointer = git(evidence, "cat-file", "-p", "HEAD:board.step")
    assert pointer.startswith("version https://git-lfs.github.com/spec/v1")


def test_a_backup_rebuilds_the_catalogue_and_says_if_its_page_is_behind(
    checkout: Path, shell: str
) -> None:
    scripts = SCRIPT.parent
    shutil.copy(scripts / "build-catalog.py", checkout / "scripts" / "build-catalog.py")
    (checkout / "scripts" / "catalog").mkdir()
    shutil.copy(
        scripts / "catalog" / "page.html",
        checkout / "scripts" / "catalog" / "page.html",
    )
    (checkout / "evidence" / "filled.json").write_text("{}\n", encoding="utf-8")

    result = back_up(checkout, shell)

    assert result.returncode == 0, result.stderr
    assert "backup-evidence: pushed" in result.stdout
    assert "catalog: 0 designs at evidence" in result.stdout
    assert "not published from this checkout" in result.stdout
    assert (checkout / "catalog" / "catalog.json").is_file()


def test_unchanged_evidence_needs_no_backup(checkout: Path, shell: str) -> None:
    result = back_up(checkout, shell)

    assert result.returncode == 0
    assert "no new evidence" in result.stdout

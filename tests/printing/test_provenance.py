"""Recording the source a slice was cut from, and checking it has not moved."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from zcad_core.metadata.git import git_environment
from zcad_core.printing import slice_freshness, source_provenance


def git(repository: Path, *arguments: str) -> str:
    # The pre-push hook runs these tests with GIT_DIR set; without clearing
    # it, git would act on the project's repository instead of this one.
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
        env=git_environment(),
    ).stdout.strip()


def commit(repository: Path, path: str, text: str, message: str) -> str:
    file = repository / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    git(repository, "add", path)
    git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-q",
        "-m",
        message,
    )

    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "src/zcad_core/lid.py", "RIDGE = 0.3\n", "Add the lid")
    commit(tmp_path, "profiles/printer.json", "{}\n", "Add a printer")

    return tmp_path


def sliced_at(repository: Path) -> dict[str, object]:
    return {"source": source_provenance(repository)}


def test_a_slice_records_its_commit_and_a_clean_tree(repository: Path) -> None:
    source = source_provenance(repository)

    assert source == {
        "git_commit": git(repository, "rev-parse", "HEAD"),
        "uncommitted_changes": False,
    }


def test_a_slice_of_uncommitted_geometry_cannot_be_vouched_for(
    repository: Path,
) -> None:
    (repository / "src/zcad_core/lid.py").write_text("RIDGE = 0.4\n", "utf-8")
    summary = sliced_at(repository)

    assert summary["source"]["uncommitted_changes"] is True  # type: ignore[index]
    freshness = slice_freshness(summary, repository)
    assert freshness.status == "unknown"
    assert "uncommitted changes" in freshness.reason


def test_a_slice_stays_current_until_the_geometry_changes(repository: Path) -> None:
    summary = sliced_at(repository)
    commit(repository, "docs/guide.md", "# Guide\n", "Write the guide")

    assert slice_freshness(summary, repository).status == "current"

    commit(repository, "src/zcad_core/lid.py", "RIDGE = 0.4\n", "Deepen the ridge")
    freshness = slice_freshness(summary, repository)

    assert freshness.status == "stale"
    assert [change.split(" ", 1)[1] for change in freshness.changes] == [
        "Deepen the ridge"
    ]


def test_a_profile_change_also_makes_a_slice_stale(repository: Path) -> None:
    summary = sliced_at(repository)
    commit(repository, "profiles/printer.json", '{"nozzle": 0.4}\n', "Set nozzle")

    assert slice_freshness(summary, repository).status == "stale"


def test_a_rebased_branch_compares_by_content(repository: Path) -> None:
    git(repository, "checkout", "-q", "-b", "feature")
    commit(repository, "src/zcad_core/lid.py", "RIDGE = 0.5\n", "Deepen the ridge")
    summary = sliced_at(repository)
    # The same change lands on main as a different commit, as a rebase-merge
    # would leave it, and the branch is dropped.
    git(repository, "checkout", "-q", "main")
    commit(repository, "src/zcad_core/lid.py", "RIDGE = 0.5\n", "Deepen the ridge (#7)")
    git(repository, "branch", "-q", "-D", "feature")
    assert git(repository, "rev-parse", "HEAD") != summary["source"]["git_commit"]  # type: ignore[index]

    assert slice_freshness(summary, repository).status == "current"

    commit(repository, "src/zcad_core/lid.py", "RIDGE = 0.6\n", "Deepen it again")
    freshness = slice_freshness(summary, repository)

    # Not an ancestor, so the changed files stand in for the commits.
    assert freshness.status == "stale"
    assert freshness.changes == ("src/zcad_core/lid.py",)


def test_a_slice_without_a_source_is_unknown(repository: Path) -> None:
    freshness = slice_freshness({"schema_version": "1.1.0"}, repository)

    assert freshness.status == "unknown"
    assert "no source commit" in freshness.reason


def test_a_commit_missing_from_the_repository_is_unknown(repository: Path) -> None:
    summary = {"source": {"git_commit": "0" * 40, "uncommitted_changes": False}}

    assert slice_freshness(summary, repository).status == "unknown"


def test_outside_a_git_checkout_nothing_is_recorded(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    assert source_provenance(outside) == {
        "git_commit": None,
        "uncommitted_changes": None,
    }


def test_a_hooks_git_dir_does_not_redirect_to_another_repository(
    repository: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = tmp_path_factory.mktemp("other")
    git(other, "init", "-q", "-b", "main")
    commit(other, "README.md", "other\n", "Other repository")
    config = (other / ".git" / "config").read_text("utf-8")
    # As a pre-push hook leaves it for the tests it runs.
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    assert source_provenance(repository)["git_commit"] == git(
        repository, "rev-parse", "HEAD"
    )
    assert (other / ".git" / "config").read_text("utf-8") == config

"""Which source a slice was cut from, and whether that source has moved on.

A slice is printed from G-code, not from the code that shaped it, so a fix
to the geometry does nothing for a slice made before it. When it slices,
the builder records the git commit it ran from and whether the geometry
sources had uncommitted changes. ``slice_freshness`` later compares that
commit with the current tree: any change to the sources since then makes
the slice stale, and one with no source recorded, or cut from uncommitted
changes, cannot be vouched for.

The comparison is by content, not ancestry, so a slice made on a branch
that was later rebased onto main still compares cleanly.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Everything that shapes a part or how it is sliced.
GEOMETRY_PATHS = ("src/zcad_core", "profiles")
_PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1]
_REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
    }
)

SliceStatus = Literal["current", "stale", "unknown"]


@dataclass(frozen=True)
class SliceFreshness:
    """Whether a slice still matches the source that would build it now."""

    status: SliceStatus
    reason: str
    # For a stale slice: the commits since, or the files, that changed.
    changes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "changes": list(self.changes),
        }


def repository_root(start: Path = _PACKAGE_DIRECTORY) -> Path | None:
    """The git checkout holding ``start``, or None outside one."""

    result = _git(start, "rev-parse", "--show-toplevel")

    return Path(result) if result is not None else None


def source_provenance(repository: Path | None = None) -> dict[str, Any]:
    """The commit the geometry sources are at and whether they carry
    uncommitted changes; nulls outside a git checkout."""

    root = repository or repository_root()
    commit = _git(root, "rev-parse", "HEAD") if root is not None else None

    if root is None or commit is None:
        return {"git_commit": None, "uncommitted_changes": None}

    status = _git(root, "status", "--porcelain", "--", *GEOMETRY_PATHS)

    return {"git_commit": commit, "uncommitted_changes": bool(status)}


def slice_freshness(
    summary: dict[str, Any], repository: Path | None = None
) -> SliceFreshness:
    """Compare the source a slice summary records with the current tree."""

    source = summary.get("source") or {}
    commit = source.get("git_commit")

    if not commit:
        return SliceFreshness("unknown", "the slice records no source commit")

    if source.get("uncommitted_changes"):
        return SliceFreshness(
            "unknown", f"it was sliced from uncommitted changes on {commit[:7]}"
        )

    root = repository or repository_root()

    if root is None:
        return SliceFreshness("unknown", "there is no git checkout to compare with")

    if _git(root, "cat-file", "-e", f"{commit}^{{commit}}") is None:
        return SliceFreshness(
            "unknown", f"commit {commit[:7]} is not in this repository"
        )

    changed = _git(root, "diff", "--name-only", commit, "--", *GEOMETRY_PATHS)

    if changed is None:
        return SliceFreshness("unknown", f"git could not compare with {commit[:7]}")

    if not changed:
        return SliceFreshness("current", f"the sources match {commit[:7]}")

    return SliceFreshness(
        "stale",
        f"the sources changed since {commit[:7]}; rebuild and slice again",
        _commits_since(root, commit) or tuple(changed.splitlines()),
    )


def _commits_since(root: Path, commit: str) -> tuple[str, ...]:
    """The commits touching the sources since ``commit``, when it is an
    ancestor of HEAD; empty otherwise, such as after a rebase."""

    if _git(root, "merge-base", "--is-ancestor", commit, "HEAD") is None:
        return ()

    log = _git(root, "log", "--format=%h %s", f"{commit}..HEAD", "--", *GEOMETRY_PATHS)

    return tuple(log.splitlines()) if log else ()


def git_environment() -> dict[str, str]:
    """This process's environment without the variables that point git at a
    repository. A git hook sets ``GIT_DIR``, which overrides ``-C``: left in,
    git would read, or write, the repository running the hook instead."""

    return {
        name: value
        for name, value in os.environ.items()
        if name not in _REPOSITORY_VARIABLES
    }


def _git(directory: Path, *arguments: str) -> str | None:
    """Run git in ``directory``: its trimmed output, or None when it fails."""

    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=git_environment(),
        )
    except OSError:
        return None

    return result.stdout.strip() if result.returncode == 0 else None

"""Best-effort provenance for the loaded core, never the caller's checkout."""

import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import zcad_core
from zcad_core.metadata.git import git_environment


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(directory), *arguments],
        capture_output=True,
        text=True,
        check=True,
        timeout=3,
        env=git_environment(),
    )
    return result.stdout.strip()


def producer_provenance() -> dict[str, str | None]:
    """Unknown source state is explicit; no paths or file contents are emitted.

    Tracked state is not a fingerprint of untracked files, dependencies or inputs.
    Distribution version describes installed metadata, not proof of source parity.
    """
    record: dict[str, str | None] = {
        "name": "zcad-core",
        "distribution_version": None,
        "git_commit": None,
        "tracked_worktree_state": "unknown",
    }
    try:
        record["distribution_version"] = version("zcad-core")
    except PackageNotFoundError:
        pass
    try:
        module = Path(zcad_core.__file__).resolve()
        root = Path(_git(module.parent, "rev-parse", "--show-toplevel")).resolve()
        relative = module.relative_to(root).as_posix()
        _git(root, "ls-files", "--error-unmatch", "--", relative)
        commit = _git(root, "rev-parse", "HEAD")
        state = _git(root, "status", "--porcelain", "--untracked-files=no")
        record["git_commit"] = commit
        record["tracked_worktree_state"] = "dirty" if state else "clean"
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass
    return record

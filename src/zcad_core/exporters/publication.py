"""Publish a prepared file set with rollback for caught failures.

Single-writer contract; not crash-atomic or isolated from concurrent readers.
"""

import os
import shutil
import tempfile
from pathlib import Path


def _published_names(staged: Path, output: Path) -> list[str]:
    """The staged file names, once every destination is safe to replace."""

    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("Export output must be a real directory")

    names = sorted(p.name for p in staged.iterdir())

    for name in names:
        target = output / name

        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Export target must be a regular file: {target}")

    return names


def _stage(
    names: list[str], staged: Path, output: Path, incoming: Path, backup: Path
) -> set[str]:
    """Copy the new files in and back up the ones they replace."""

    previous = set()

    for name in names:
        shutil.copy2(staged / name, incoming / name)
        target = output / name

        if target.exists():
            shutil.copy2(target, backup / name)
            previous.add(name)

    return previous


def _roll_back(
    applied: list[str],
    previous: set[str],
    backup: Path,
    output: Path,
    *,
    created: bool,
) -> list[str]:
    """Undo applied replacements, newest first; return what could not be undone."""

    failures = []

    for name in reversed(applied):
        try:
            if name in previous:
                os.replace(backup / name, output / name)
            else:
                (output / name).unlink()
        # Keep restoring remaining files; every failure is reported.
        except BaseException as rollback_error:  # noqa: BLE001
            failures.append(f"{name}: {rollback_error}")

    if created:
        try:
            output.rmdir()
        except OSError as rollback_error:
            failures.append(str(rollback_error))

    return failures


def publish_files(staged: Path, output: Path) -> None:
    """Preserve unrelated files and restore replaced files on publication errors."""
    names = _published_names(staged, output)

    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".zcad-publish-", dir=output.parent))
    retain = False
    applied: list[str] = []

    try:
        incoming = work / "incoming"
        backup = work / "backup"
        incoming.mkdir()
        backup.mkdir()
        previous = _stage(names, staged, output, incoming, backup)
        created = not output.exists()

        if created:
            output.mkdir()

        try:
            for name in names:
                os.replace(incoming / name, output / name)
                applied.append(name)
        except BaseException as error:
            failures = _roll_back(applied, previous, backup, output, created=created)

            if failures:
                retain = True
                raise RuntimeError(
                    f"Export rollback incomplete; recovery files retained at {work}: "
                    + "; ".join(failures)
                ) from error

            raise
    finally:
        if not retain:
            shutil.rmtree(work)

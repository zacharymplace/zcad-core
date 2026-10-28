"""Opt-in, read-only byte checks for one part's exported artifact bindings."""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ArtifactKind = Literal["step", "stl"]
BindingStatus = Literal["matched", "missing", "mismatched", "not-verifiable"]


@dataclass(frozen=True)
class ArtifactBindingCheck:
    """One artifact's scoped result; never a geometry or authenticity verdict."""

    kind: ArtifactKind
    status: BindingStatus
    reason: str
    filename: str | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    expected_size_bytes: int | None = None
    actual_size_bytes: int | None = None


def _binding_error(binding: object) -> str | None:
    if not isinstance(binding, dict):
        return "Artifact binding missing or malformed."
    name = binding.get("filename")
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or any(c in name for c in ("/", "\\", ":", "\x00"))
    ):
        return "Artifact filename must be a safe sibling basename."
    digest, size = binding.get("sha256"), binding.get("size_bytes")
    if not isinstance(digest, str) or re.fullmatch("[a-f0-9]{64}", digest) is None:
        return "Artifact SHA-256 must be 64 lowercase hexadecimal characters."
    if type(size) is not int or size < 0:
        return "Artifact byte size must be a nonnegative integer."
    return None


def _read_bytes_identity(path: Path) -> tuple[str, int]:
    """Stream regular files only, without following artifact symlinks."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Artifact is not a regular file; symlinks are not followed.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        initial = os.fstat(handle.fileno())
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError("Artifact is not a regular file.")
        digest, size = hashlib.sha256(), 0
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        final = os.fstat(handle.fileno())
        if (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            raise ValueError("Artifact changed while reading; retry when stable.")
    return digest.hexdigest(), size


def _check_binding(
    kind: ArtifactKind, binding: object, directory: Path
) -> ArtifactBindingCheck:
    error = _binding_error(binding)
    if error:
        return ArtifactBindingCheck(kind, "not-verifiable", error)
    assert isinstance(binding, dict)
    name, expected_hash, expected_size = (
        binding["filename"],
        binding["sha256"],
        binding["size_bytes"],
    )
    try:
        actual_hash, actual_size = _read_bytes_identity(directory / name)
    except FileNotFoundError:
        return ArtifactBindingCheck(kind, "missing", "Artifact file missing.", name)
    except (OSError, ValueError) as exc:
        return ArtifactBindingCheck(kind, "not-verifiable", str(exc), name)
    matched = actual_hash == expected_hash and actual_size == expected_size
    return ArtifactBindingCheck(
        kind,
        "matched" if matched else "mismatched",
        "SHA-256 and byte size match."
        if matched
        else "SHA-256 or byte size differs from the recorded binding.",
        name,
        expected_hash,
        actual_hash,
        expected_size,
        actual_size,
    )


def verify_artifact_bindings(metadata_path: Path) -> tuple[ArtifactBindingCheck, ...]:
    """Check STEP/STL siblings without exporting, writing, or trusting outputs paths.

    Missing/legacy/malformed metadata is not verifiable, never a successful check.
    Results describe byte identity only. No aggregate verdict is inferred.
    """
    kinds: tuple[ArtifactKind, ...] = ("step", "stl")
    try:
        path = metadata_path.resolve(strict=True)
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        return tuple(
            ArtifactBindingCheck(kind, "not-verifiable", f"Cannot read metadata: {exc}")
            for kind in kinds
        )
    bindings = record.get("artifacts") if isinstance(record, dict) else None
    if not isinstance(bindings, dict):
        return tuple(
            ArtifactBindingCheck(
                kind, "not-verifiable", "No artifact bindings recorded."
            )
            for kind in kinds
        )
    return tuple(
        _check_binding(kind, bindings.get(kind), path.parent) for kind in kinds
    )
